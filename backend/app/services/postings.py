"""Scoring and querying published postings.

The scoring here is the alignment engine with nothing changed. That reuse is
the point: the score a student sees on the board, the score a recruiter ranks
applicants by, and the score candidate search sorts on are all the same
function, so none of them can disagree about what a good fit is.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    JobPosting,
    PostingApplication,
    PostingRequirement,
    PostingStatus,
    Profile,
)
from app.models.enums import Necessity
from app.schemas import AlignmentOut
from app.services.analytics.alignment import (
    AlignmentResult,
    JobFacts,
    RequirementInput,
    score_alignment,
)
from app.services.scoring import load_aliases, preferences_of, skills_of


def requirements_of(posting: JobPosting) -> list[RequirementInput]:
    return [
        RequirementInput(
            name=r.name, necessity=Necessity(r.necessity), min_years=r.min_years
        )
        for r in posting.requirements
    ]


def facts_of(posting: JobPosting) -> JobFacts:
    return JobFacts(
        title=posting.title,
        location=posting.location,
        remote=posting.remote,
        seniority=posting.seniority,
        salary_min=posting.salary_min,
        salary_max=posting.salary_max,
        industry=posting.industry,
        company_size=posting.company_size,
    )


def score_posting(
    db: Session,
    profile: Profile,
    posting: JobPosting,
    aliases: dict[str, str] | None = None,
) -> AlignmentResult:
    """Score one posting for one student."""
    return score_alignment(
        requirements=requirements_of(posting),
        skills=skills_of(profile),
        prefs=preferences_of(profile.preferences),
        job=facts_of(posting),
        aliases=aliases if aliases is not None else load_aliases(db),
    )


def alignment_summary(result: AlignmentResult) -> dict:
    """A compact, storable record of why a score came out as it did.

    Frozen onto the application at apply time. A recruiter ranking candidates
    months later needs the reasoning as it stood then, not a recomputation
    against a profile the student has since edited.
    """
    return {
        "total": result.total,
        "requirements_fit": result.requirements_fit,
        "preference_fit": result.preference_fit,
        "have": [r.name for r in result.have],
        "partial": [r.name for r in result.partial],
        "missing": [r.name for r in result.missing],
    }


def open_postings(db: Session, *, now: datetime | None = None) -> list[JobPosting]:
    """Every posting a student may currently apply to, newest first.

    Date filtering happens in Python rather than SQL because `is_open` also has
    to reason about naive timestamps out of SQLite, and having one definition
    of "open" matters more here than the query cost — a board is tens of rows,
    not millions.
    """
    now = now or datetime.now(UTC)
    postings = list(
        db.execute(
            select(JobPosting)
            .where(JobPosting.status == PostingStatus.OPEN)
            .order_by(JobPosting.created_at.desc())
        ).scalars()
    )
    return [p for p in postings if p.is_open(now=now)]


def applied_posting_ids(db: Session, profile: Profile) -> set[int]:
    """Postings this student has already applied to.

    Fetched once for the whole board rather than per card, so rendering it is
    two queries regardless of how many postings there are.
    """
    rows = db.execute(
        select(PostingApplication.posting_id).where(
            PostingApplication.profile_id == profile.id
        )
    ).scalars()
    return set(rows)


def requirements_from_extraction(extracted) -> list[PostingRequirement]:
    """Turn an ingestion-pipeline result into posting requirements.

    Shared by the HR posting form and by sourced ingestion, so a role typed in
    by a recruiter and one the pipeline found are scored on identical terms.
    """
    from app.services.analytics.canonical import canonicalize

    rows: list[PostingRequirement] = []
    for r in extracted.requirements:
        canonical = canonicalize(r.name)
        if not canonical:
            continue
        try:
            necessity = Necessity(str(r.necessity).strip().lower())
        except ValueError:
            # An unrecognized value is read as `required`: over-weighting makes
            # a role look harder than it is, which is the safer error.
            necessity = Necessity.REQUIRED

        rows.append(
            PostingRequirement(
                name=canonical,
                necessity=necessity,
                min_years=r.min_years,
                evidence=r.evidence,
            )
        )
    return rows


def posting_for_student(db, posting_id: int):
    """A posting a student may prepare against, or None.

    Any open posting — preparing for a role you have not applied to yet is the
    normal case, and gating it behind having applied would put the interview
    practice after the interview.
    """
    from app.models import JobPosting

    posting = db.get(JobPosting, posting_id)
    if posting is None or not posting.is_open():
        return None
    return posting


def posting_text_for_agents(posting) -> str:
    """The prose an agent should read about a role.

    Prefers what was extracted from; falls back to assembling the structured
    fields, because a posting typed into the form by hand has no source text
    and would otherwise reach the agent as an empty string.
    """
    if posting.raw_text and len(posting.raw_text) > 80:
        return posting.raw_text
    parts = [
        f"{posting.title} at {posting.company_name}",
        posting.description or "",
        "Requirements: "
        + ", ".join(
            r.name + (f" ({r.min_years:g}+ years)" if r.min_years else "")
            for r in posting.requirements
        ),
    ]
    return "\n\n".join(p for p in parts if p)


def alignment_out(result: AlignmentResult) -> AlignmentOut:
    """Render a scoring result for the API.

    Lived in the student's job-tracker routes until those were removed. It is
    the board's now, and belongs beside the other posting services rather than
    in a route module nothing reaches.
    """
    return AlignmentOut(
        total=result.total,
        requirements_fit=result.requirements_fit,
        preference_fit=result.preference_fit,
        requirements=[
            {
                "name": r.name,
                "necessity": r.necessity,
                "coverage": r.coverage,
                "weight": r.weight,
                "credit": r.credit,
                "reason": r.reason,
            }
            for r in result.requirements
        ],
        facets=[
            {"name": f.name, "matched": f.matched, "detail": f.detail}
            for f in result.facets
        ],
        explanation=result.explain(),
    )
