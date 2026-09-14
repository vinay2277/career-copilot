"""`/api/employer/*` — recruiters creating and managing postings.

Every route is scoped to the caller's own organization. A recruiter can only
ever see or change postings their organization published, and the check is on
the query rather than after it — an authorization test that runs on a row you
have already loaded is one somebody will eventually forget.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
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
    JobPosting,
    Organization,
    PostingApplication,
    PostingRequirement,
    PostingSource,
    PostingStatus,
)
from app.schemas_posting import (
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
