"""`/api/employer/*` — recruiters creating and managing postings.

Every route is scoped to the caller's own organization. A recruiter can only
ever see or change postings their organization published, and the check is on
the query rather than after it — an authorization test that runs on a row you
have already loaded is one somebody will eventually forget.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.client import AgentError
from app.api.deps import (
    AI_ROUTE,
    get_organization,
    require_hr,
    require_verified_organization,
)
from app.db.session import get_db
from app.models import (
    Account,
    ApplicationStatus,
    InterviewSession,
    JobPosting,
    Organization,
    PostingApplication,
    PostingRequirement,
    PostingSource,
    PostingStatus,
    Profile,
)
from app.schemas_posting import (
    ApplicationDecisionIn,
    CandidateListOut,
    CandidateOut,
    CandidateSearchIn,
    CandidateSearchOut,
    CandidateSearchRowOut,
    PostingDraftIn,
    PostingDraftOut,
    PostingOut,
    PostingParseIn,
    PostingRequirementOut,
    PostingSummaryOut,
)
from app.services.ingestion import parsers
from app.services.ingestion.pipeline import ingest
from app.services.postings import requirements_from_extraction
from app.services.search import CandidateQuery, search_candidates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/employer", tags=["employer"])


def _owned(db: Session, posting_id: int, organization: Organization) -> JobPosting:
    """Fetch a posting the caller's organization owns, or 404.

    Filtered in the query, so another organization's posting is not merely
    rejected — it is never loaded. 404 rather than 403, so the existence of
    other organizations' postings isn't confirmable by probing ids.
    """
    posting = db.execute(
        select(JobPosting).where(
            JobPosting.id == posting_id,
            JobPosting.organization_id == organization.id,
        )
    ).scalar_one_or_none()

    if posting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such posting.")
    return posting


# --------------------------------------------------------------------------- #
# Drafting from a pasted description
# --------------------------------------------------------------------------- #


@router.post("/postings/parse", response_model=PostingDraftOut, dependencies=AI_ROUTE)
def parse_description(
    payload: PostingParseIn,
    organization: Organization = Depends(require_verified_organization),
) -> PostingDraftOut:
    """Turn a pasted job description into a draft.

    Reuses the student-side ingestion pipeline wholesale — extract, then
    validate — so a role a recruiter types in and one the pipeline sourced are
    read on identical terms and scored against identical requirements.

    Returns a draft rather than saving: the recruiter confirms first, which is
    what makes the validator's confidence worth computing.
    """
    from app.models.enums import SourceKind

    try:
        result = ingest(source_kind=SourceKind.TEXT, text=payload.text)
    except parsers.ParseError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    except AgentError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    extracted = result.extracted
    return PostingDraftOut(
        title=extracted.title,
        # The recruiter's own organization wins over whatever the text said —
        # they are publishing on their own behalf, not transcribing.
        company_name=organization.name,
        description=extracted.description,
        location=extracted.location,
        remote=extracted.remote,
        seniority=extracted.seniority,
        salary_min=extracted.salary_min,
        salary_max=extracted.salary_max,
        currency=extracted.currency,
        industry=extracted.industry,
        company_size=extracted.company_size,
        education=extracted.education,
        certifications=extracted.certifications,
        total_years_experience=extracted.total_years_experience,
        requirements=[
            PostingRequirementOut(
                name=r.name,
                necessity=r.necessity,
                min_years=r.min_years,
                evidence=r.evidence,
            )
            for r in requirements_from_extraction(extracted)
        ],
        raw_text=result.raw_text,
        confidence=result.report.confidence,
        unverified_fields=result.report.unverified_fields,
        validation_notes=result.report.notes,
    )


# --------------------------------------------------------------------------- #
# Postings
# --------------------------------------------------------------------------- #


def _apply_draft(posting: JobPosting, payload: PostingDraftIn) -> None:
    """Copy a draft onto a posting, replacing its requirements."""
    from app.services.analytics.canonical import canonicalize

    posting.title = payload.title
    posting.description = payload.description
    posting.location = payload.location
    posting.remote = payload.remote
    posting.seniority = payload.seniority
    posting.salary_min = payload.salary_min
    posting.salary_max = payload.salary_max
    posting.currency = payload.currency
    posting.industry = payload.industry
    posting.company_size = payload.company_size
    posting.education = payload.education
    posting.certifications = payload.certifications
    posting.total_years_experience = payload.total_years_experience
    posting.closes_at = payload.closes_at
    posting.interview_required = payload.interview_required
    posting.interview_question_count = payload.interview_question_count
    if payload.raw_text:
        posting.raw_text = payload.raw_text

    posting.requirements.clear()
    for r in payload.requirements:
        canonical = canonicalize(r.name)
        if not canonical:
            continue
        posting.requirements.append(
            PostingRequirement(
                name=canonical,
                necessity=r.necessity,
                min_years=r.min_years,
                evidence=r.evidence,
            )
        )


@router.post(
    "/postings", response_model=PostingOut, status_code=status.HTTP_201_CREATED
)
def create_posting(
    payload: PostingDraftIn,
    db: Session = Depends(get_db),
    account: Account = Depends(require_hr),
    organization: Organization = Depends(require_verified_organization),
) -> JobPosting:
    """Create a posting as a draft.

    Drafts are not visible to students. Publishing is a separate, deliberate
    action — see `/publish`.
    """
    posting = JobPosting(
        organization_id=organization.id,
        posted_by_id=account.id,
        source=PostingSource.EMPLOYER,
        status=PostingStatus.DRAFT,
        company_name=organization.name,
    )
    _apply_draft(posting, payload)

    db.add(posting)
    db.commit()
    db.refresh(posting)
    logger.info("org %s drafted posting %s", organization.id, posting.id)
    return posting


@router.get("/postings", response_model=list[PostingSummaryOut])
def list_postings(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization),
) -> list[PostingSummaryOut]:
    """The organization's postings, newest first, with application counts.

    Counted in one grouped query rather than per posting, so the dashboard
    stays two queries no matter how many roles are open.
    """
    postings = list(
        db.execute(
            select(JobPosting)
            .where(JobPosting.organization_id == organization.id)
            .order_by(JobPosting.created_at.desc())
        ).scalars()
    )

    counts = dict(
        db.execute(
            select(
                PostingApplication.posting_id, func.count(PostingApplication.id)
            )
            .join(JobPosting)
            .where(JobPosting.organization_id == organization.id)
            .group_by(PostingApplication.posting_id)
        ).all()
    )

    return [
        PostingSummaryOut(
            posting=PostingOut.model_validate(p),
            application_count=counts.get(p.id, 0),
            is_accepting=p.is_open(),
        )
        for p in postings
    ]


@router.get("/postings/{posting_id}", response_model=PostingSummaryOut)
def read_posting(
    posting_id: int,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization),
) -> PostingSummaryOut:
    posting = _owned(db, posting_id, organization)
    count = db.execute(
        select(func.count(PostingApplication.id)).where(
            PostingApplication.posting_id == posting.id
        )
    ).scalar_one()

    return PostingSummaryOut(
        posting=PostingOut.model_validate(posting),
        application_count=count,
        is_accepting=posting.is_open(),
    )


@router.put("/postings/{posting_id}", response_model=PostingOut)
def update_posting(
    posting_id: int,
    payload: PostingDraftIn,
    db: Session = Depends(get_db),
    organization: Organization = Depends(require_verified_organization),
) -> JobPosting:
    """Edit a posting.

    Editing requirements after applications exist would silently change what
    every applicant was scored against, so it is refused once anyone has
    applied — close the role and post a corrected one instead.
    """
    posting = _owned(db, posting_id, organization)

    applied = db.execute(
        select(func.count(PostingApplication.id)).where(
            PostingApplication.posting_id == posting.id
        )
    ).scalar_one()
    if applied:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{applied} candidate(s) have already applied and were scored "
            "against the current requirements. Close this role and post a "
            "corrected one rather than changing it underneath them.",
        )

    _apply_draft(posting, payload)
    db.commit()
    db.refresh(posting)
    return posting


@router.post("/postings/{posting_id}/publish", response_model=PostingOut)
def publish_posting(
    posting_id: int,
    db: Session = Depends(get_db),
    organization: Organization = Depends(require_verified_organization),
) -> JobPosting:
    """Make a posting visible to students."""
    posting = _owned(db, posting_id, organization)

    if not posting.requirements:
        # A posting with no requirements scores every candidate at zero, which
        # makes the board useless and the ranking meaningless.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Add at least one requirement before publishing — candidates are "
            "scored against them.",
        )

    posting.status = PostingStatus.OPEN
    posting.opens_at = posting.opens_at or datetime.now(UTC)
    db.commit()
    db.refresh(posting)
    logger.info("org %s published posting %s", organization.id, posting.id)
    return posting


@router.post("/postings/{posting_id}/close", response_model=PostingOut)
def close_posting(
    posting_id: int,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization),
) -> JobPosting:
    """Stop accepting applications.

    Not gated on verification: an organization whose verification lapses must
    still be able to take its roles down.
    """
    posting = _owned(db, posting_id, organization)
    posting.status = PostingStatus.CLOSED
    db.commit()
    db.refresh(posting)
    return posting


# --------------------------------------------------------------------------- #
# Candidate search
# --------------------------------------------------------------------------- #


@router.post("/candidates/search", response_model=CandidateSearchOut)
def search(
    payload: CandidateSearchIn,
    db: Session = Depends(get_db),
    organization: Organization = Depends(require_verified_organization),
) -> CandidateSearchOut:
    """Find candidates by skill among those who opted in.

    POST rather than GET because the query is a structured object with a list
    in it, and threading that through a query string would mean inventing an
    encoding for it. Nothing here mutates.

    `searchable_total` is returned so an empty result can tell the recruiter
    which kind of empty it is: a search too narrow, or a platform where nobody
    has opted into being found yet. Those need opposite responses and look
    identical without it.
    """
    matches = search_candidates(
        db,
        CandidateQuery(
            skills=payload.skills,
            min_years=payload.min_years,
            location=payload.location,
            remote_only=payload.remote_only,
            open_to_work_only=payload.open_to_work_only,
            limit=payload.limit,
        ),
    )

    searchable_total = db.execute(
        select(func.count())
        .select_from(Profile)
        .where(Profile.visible_to_recruiters.is_(True))
    ).scalar_one()

    logger.info(
        "org %s searched candidates (%s skills) — %s of %s searchable matched",
        organization.id,
        len(payload.skills),
        len(matches),
        searchable_total,
    )

    return CandidateSearchOut(
        results=[
            CandidateSearchRowOut(
                profile_id=m.profile.id,
                full_name=m.profile.full_name,
                email=m.profile.email,
                headline=m.profile.headline,
                location=m.profile.location,
                years_experience=m.profile.years_experience,
                open_to_work=m.profile.open_to_work,
                score=m.score,
                have=m.have,
                partial=m.partial,
                missing=m.missing,
                skills=sorted(s.name for s in m.profile.skills),
            )
            for m in matches
        ],
        searchable_total=searchable_total,
    )


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #


def _candidates(db: Session, posting: JobPosting) -> list[CandidateOut]:
    """The posting's applicants, best-scoring first.

    Ranked, never filtered. Every applicant appears however they scored — the
    score orders the list and explains itself, and a person decides what to do
    about it. Hiding candidates below a cut-off would make the ranking an
    automated rejection, which is exactly what this must not be.
    """
    # Account is joined rather than reached through `profile.account`, which
    # would be one extra query per candidate. Profile.skills is already
    # selectin-loaded on the model, so this is two queries for the whole list.
    rows = list(
        db.execute(
            select(PostingApplication, Profile, Account)
            .join(Profile, Profile.id == PostingApplication.profile_id)
            .join(Account, Account.id == Profile.account_id)
            .where(PostingApplication.posting_id == posting.id)
        ).all()
    )

    # One query for every screening round on this posting, rather than one per
    # candidate. Keyed by application so a candidate who has not sat theirs
    # simply has no entry.
    interviews = {
        s.application_id: s
        for s in db.execute(
            select(InterviewSession).where(
                InterviewSession.application_id.in_(
                    [application.id for application, _, _ in rows]
                )
            )
        ).scalars()
    }

    # A None score sorts last rather than crashing the comparison: applying with
    # an empty profile is allowed, and those rows still have to render.
    rows.sort(
        key=lambda row: (
            row[0].alignment_score is None,
            -(row[0].alignment_score or 0.0),
            row[0].applied_at,
        )
    )

    out: list[CandidateOut] = []
    for application, profile, account in rows:
        detail = application.alignment_detail or {}
        interview = interviews.get(application.id)
        if interview is None:
            interview_status = "required" if posting.interview_required else None
        elif interview.completed_at is None:
            interview_status = "in_progress"
        else:
            interview_status = "completed"

        out.append(
            CandidateOut(
                application_id=application.id,
                status=application.status,
                applied_at=application.applied_at,
                cover_note=application.cover_note,
                full_name=profile.full_name,
                email=profile.email or account.email,
                phone=profile.phone,
                headline=profile.headline,
                location=profile.location,
                years_experience=profile.years_experience,
                alignment_score=application.alignment_score,
                have=list(detail.get("have", [])),
                partial=list(detail.get("partial", [])),
                missing=list(detail.get("missing", [])),
                skills=sorted(s.name for s in profile.skills),
                interview_status=interview_status,
                interview_score=interview.overall_score if interview else None,
                interview_summary=interview.summary if interview else None,
            )
        )
    return out


@router.get("/postings/{posting_id}/applications", response_model=CandidateListOut)
def list_candidates(
    posting_id: int,
    db: Session = Depends(get_db),
    organization: Organization = Depends(require_verified_organization),
) -> CandidateListOut:
    """Who applied to this role.

    Gated on verification like posting is: an organization nobody has approved
    has no business reading students' contact details.
    """
    posting = _owned(db, posting_id, organization)
    candidates = _candidates(db, posting)

    counts: dict[str, int] = {}
    for candidate in candidates:
        key = candidate.status.value
        counts[key] = counts.get(key, 0) + 1

    return CandidateListOut(
        posting=PostingOut.model_validate(posting),
        candidates=candidates,
        status_counts=counts,
    )


@router.patch(
    "/postings/{posting_id}/applications/{application_id}",
    response_model=CandidateOut,
)
def decide_on_candidate(
    posting_id: int,
    application_id: int,
    payload: ApplicationDecisionIn,
    db: Session = Depends(get_db),
    organization: Organization = Depends(require_verified_organization),
) -> CandidateOut:
    """Move one candidate along — shortlist, interview, offer, or decline.

    The student sees this status on their own applications page, so it is not
    a private annotation: changing it tells them where they stand. That is the
    intent. Being rejected silently is the thing applicants hate most, and a
    status nobody can see would be no better than not having one.
    """
    posting = _owned(db, posting_id, organization)

    application = db.execute(
        select(PostingApplication).where(
            PostingApplication.id == application_id,
            PostingApplication.posting_id == posting.id,
        )
    ).scalar_one_or_none()

    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application.")

    if payload.status is ApplicationStatus.WITHDRAWN:
        # Withdrawing is the student's own act. A recruiter marking somebody
        # withdrawn would misrepresent what happened in the student's record.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only the candidate can withdraw an application. Use 'rejected' "
            "to decline it.",
        )

    application.status = payload.status
    db.commit()
    logger.info(
        "org %s moved application %s to %s",
        organization.id,
        application.id,
        payload.status.value,
    )

    updated = [c for c in _candidates(db, posting) if c.application_id == application_id]
    return updated[0]


#: What a stage is called in the product. The stored value for a shortlisted
#: candidate is "screening", which the student-side tracker has always used;
#: writing that into a recruiter's spreadsheet would use a different word for
#: the action than the button they clicked.
STAGE_LABELS = {
    ApplicationStatus.SAVED: "Saved",
    ApplicationStatus.APPLIED: "Applied",
    ApplicationStatus.SCREENING: "Shortlisted",
    ApplicationStatus.INTERVIEWING: "Interviewing",
    ApplicationStatus.OFFER: "Offer",
    ApplicationStatus.REJECTED: "Declined",
    ApplicationStatus.WITHDRAWN: "Withdrawn",
}


#: Order matters — this is the header row of the export, and recruiters read it
#: left to right: who, how to reach them, how they scored, where they stand.
CSV_COLUMNS = [
    "rank",
    "name",
    "email",
    "phone",
    "headline",
    "location",
    "years_experience",
    "alignment_score",
    "interview_score",
    "interview_status",
    "stage",
    "applied_at",
    "requirements_met",
    "requirements_partial",
    "requirements_missing",
    "all_skills",
    "cover_note",
]


@router.get(
    "/postings/{posting_id}/applications.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_candidates(
    posting_id: int,
    db: Session = Depends(get_db),
    organization: Organization = Depends(require_verified_organization),
) -> Response:
    """The candidate list as a spreadsheet.

    CSV rather than a real .xlsx: Excel, Sheets and Numbers all open it, and it
    needs no dependency — which matters, since a library installed locally but
    missing from requirements.txt has already broken one deploy here.

    Written with `utf-8-sig`. Without the BOM, Excel on Windows reads the file
    as the system codepage and mangles any name with an accent in it.
    """
    posting = _owned(db, posting_id, organization)
    candidates = _candidates(db, posting)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)

    for rank, c in enumerate(candidates, start=1):
        writer.writerow(
            [
                rank,
                c.full_name,
                c.email or "",
                c.phone or "",
                c.headline or "",
                c.location or "",
                f"{c.years_experience:g}",
                "" if c.alignment_score is None else f"{c.alignment_score:.1f}",
                "" if c.interview_score is None else f"{c.interview_score:.1f}",
                c.interview_status or "",
                STAGE_LABELS.get(c.status, c.status.value),
                c.applied_at.isoformat(timespec="seconds"),
                "; ".join(c.have),
                "; ".join(c.partial),
                "; ".join(c.missing),
                "; ".join(c.skills),
                (c.cover_note or "").replace("\r\n", " ").replace("\n", " "),
            ]
        )

    filename = _export_filename(posting)
    logger.info(
        "org %s exported %s candidates for posting %s",
        organization.id,
        len(candidates),
        posting.id,
    )
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _export_filename(posting: JobPosting) -> str:
    """A filename safe to put in a Content-Disposition header.

    Restricted to characters that cannot terminate the quoted string or inject
    a header — a job title is recruiter-supplied text, so it is not trusted to
    be well behaved.
    """
    stem = "".join(
        ch if ch.isalnum() or ch in "-_" else "-" for ch in posting.title.lower()
    ).strip("-")
    stem = re.sub(r"-{2,}", "-", stem) or "candidates"
    return f"{stem[:60]}-candidates-{datetime.now(UTC):%Y%m%d}.csv"


@router.delete("/postings/{posting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_posting(
    posting_id: int,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization),
) -> None:
    """Delete a draft.

    Only drafts. A published posting somebody applied to is part of their
    record, and deleting it would take their application with it.
    """
    posting = _owned(db, posting_id, organization)

    if posting.status is not PostingStatus.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only drafts can be deleted. Close this role instead — candidates "
            "who applied keep their record either way.",
        )

    db.delete(posting)
    db.commit()
