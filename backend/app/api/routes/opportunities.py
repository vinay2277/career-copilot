"""`/api/opportunities/*` — the board, and the applications on it."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_profile
from app.db.session import get_db
from app.models import JobPost, Profile, StatusEvent
from app.models.enums import ApplicationStatus
from app.schemas import (
    AlignmentOut,
    ApplicationUpdate,
    JobOut,
    OpportunityOut,
)
from app.services.analytics.alignment import AlignmentResult
from app.services.scoring import load_aliases, refresh_cached_score, score_job

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


def _alignment_out(result: AlignmentResult) -> AlignmentOut:
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


@router.get("", response_model=list[OpportunityOut])
def list_opportunities(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
    job_status: ApplicationStatus | None = Query(default=None, alias="status"),
    min_score: float | None = Query(default=None, ge=0, le=100),
    include_breakdown: bool = Query(
        default=False,
        description=(
            "Include the full per-requirement derivation. Off by default — the "
            "board only needs the total, and the breakdown roughly triples the "
            "payload."
        ),
    ),
) -> list[OpportunityOut]:
    """The whole board, newest first, with scores.

    Scores are recomputed on read rather than served from the cached column.
    The cache exists for sorting and for the funnel; serving it here would show
    a stale number after a profile edit, and the computation is cheap.
    """
    aliases = load_aliases(db)
    jobs = list(
        db.execute(select(JobPost).order_by(JobPost.created_at.desc())).scalars()
    )

    out: list[OpportunityOut] = []
    for job in jobs:
        application = job.application
        if job_status is not None and (
            application is None or application.status is not job_status
        ):
            continue

        result = score_job(db, profile, job, aliases)
        if min_score is not None and result.total < min_score:
            continue

        alignment = _alignment_out(result)
        if not include_breakdown:
            alignment = alignment.model_copy(
                update={"requirements": [], "facets": [], "explanation": ""}
            )

        out.append(
            OpportunityOut(
                job=JobOut.model_validate(job),
                alignment=alignment,
                application_id=application.id if application else None,
                status=application.status if application else None,
                applied_at=application.applied_at if application else None,
                deadline=application.deadline if application else None,
                notes=application.notes if application else None,
            )
        )
    return out


@router.get("/{job_id}", response_model=OpportunityOut)
def read_opportunity(
    job_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> OpportunityOut:
    """One job, always with the full score derivation."""
    job = db.get(JobPost, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job.")

    result = score_job(db, profile, job)
    application = job.application
    return OpportunityOut(
        job=JobOut.model_validate(job),
        alignment=_alignment_out(result),
        application_id=application.id if application else None,
        status=application.status if application else None,
        applied_at=application.applied_at if application else None,
        deadline=application.deadline if application else None,
        notes=application.notes if application else None,
    )


@router.patch("/{job_id}/application", response_model=OpportunityOut)
def update_application(
    job_id: int,
    payload: ApplicationUpdate,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> OpportunityOut:
    """Move a card, or edit its notes and deadline.

    A status change appends to `status_events` rather than only overwriting
    `status` — the funnel analytics read that history, so an untracked
    transition is a hole in every conversion rate.
    """
    job = db.get(JobPost, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job.")

    application = job.application
    if application is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That job has no application to update."
        )

    if payload.status is not None and payload.status is not application.status:
        previous = application.status
        application.status = payload.status
        db.add(
            StatusEvent(
                application_id=application.id,
                from_status=previous,
                to_status=payload.status,
            )
        )
        # Stamp the submission date the first time it reaches `applied`; later
        # transitions must not move it, or time-to-response goes wrong.
        if (
            payload.status is ApplicationStatus.APPLIED
            and application.applied_at is None
        ):
            application.applied_at = datetime.now(UTC)

    if payload.notes is not None:
        application.notes = payload.notes
    if payload.deadline is not None:
        application.deadline = payload.deadline

    refresh_cached_score(db, profile, application)
    db.commit()
    db.refresh(job)

    return read_opportunity(job_id, db, profile)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_opportunity(job_id: int, db: Session = Depends(get_db)) -> None:
    """Remove a job and its application. Cascades to requirements and events."""
    job = db.get(JobPost, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job.")
    db.delete(job)
    db.commit()
