"""`/api/board/*` — the student's view of published postings.

Everything here is read-only except applying. A student can see any open
posting; they cannot see drafts, closed roles, or anything about who else has
applied.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AI_ROUTE, get_profile
from app.db.session import get_db
from app.models import (
    InterviewSession,
    JobPosting,
    PostingApplication,
    PostingSource,
    Profile,
)
from app.schemas_posting import (
    ApplicationOut,
    ApplyIn,
    BoardEntryOut,
    BoardOut,
    MyApplicationOut,
    PostingOut,
    ScreeningOut,
    ScreeningSubmitIn,
    ScreeningTurnOut,
)
from app.services import screening
from app.services.postings import (
    alignment_summary,
    open_postings,
    score_posting,
)
from app.services.scoring import load_aliases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/board", tags=["board"])


def _entry(
    posting: JobPosting,
    profile: Profile,
    db: Session,
    aliases: dict[str, str],
    applied: dict[int, PostingApplication],
    *,
    with_breakdown: bool,
) -> BoardEntryOut:
    from app.api.routes.opportunities import _alignment_out

    result = score_posting(db, profile, posting, aliases)
    alignment = _alignment_out(result)
    if not with_breakdown:
        # The board only needs the total; the derivation roughly triples the
        # payload and is fetched on the detail view instead.
        alignment = alignment.model_copy(
            update={"requirements": [], "facets": [], "explanation": ""}
        )

    application = applied.get(posting.id)
    return BoardEntryOut(
        posting=PostingOut.model_validate(posting),
        alignment=alignment,
        applied=application is not None,
        application_status=application.status if application else None,
    )


@router.get("", response_model=BoardOut)
def read_board(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
    min_score: float | None = Query(default=None, ge=0, le=100),
    include_breakdown: bool = Query(default=False),
) -> BoardOut:
    """Open roles, newest first, split into the two sections.

    Scores are computed on read rather than cached: a student who has just
    updated their profile should see the board move.
    """
    aliases = load_aliases(db)
    postings = open_postings(db)

    applications = {
        a.posting_id: a
        for a in db.execute(
            select(PostingApplication).where(
                PostingApplication.profile_id == profile.id
            )
        ).scalars()
    }

    from_employers: list[BoardEntryOut] = []
    sourced: list[BoardEntryOut] = []

    for posting in postings:
        entry = _entry(
            posting,
            profile,
            db,
            aliases,
            applications,
            with_breakdown=include_breakdown,
        )
        if min_score is not None and (
            entry.alignment is None or entry.alignment.total < min_score
        ):
            continue

        if posting.source is PostingSource.EMPLOYER:
            from_employers.append(entry)
        else:
            sourced.append(entry)

    return BoardOut(from_employers=from_employers, sourced=sourced)


@router.get("/postings/{posting_id}", response_model=BoardEntryOut)
def read_posting(
    posting_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> BoardEntryOut:
    """One posting, always with the full score derivation."""
    posting = db.get(JobPosting, posting_id)
    if posting is None or not posting.is_open():
        # A closed posting is indistinguishable from a missing one here, on
        # purpose: a student has no business enumerating drafts.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such posting.")

    applications = {
        a.posting_id: a
        for a in db.execute(
            select(PostingApplication).where(
                PostingApplication.profile_id == profile.id,
                PostingApplication.posting_id == posting_id,
            )
        ).scalars()
    }

    return _entry(
        posting, profile, db, load_aliases(db), applications, with_breakdown=True
    )


@router.post(
    "/postings/{posting_id}/apply",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
)
def apply_to_posting(
    posting_id: int,
    payload: ApplyIn,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> PostingApplication:
    """Apply, freezing the alignment score as it stands now.

    The score is stored rather than recomputed later. A recruiter ranking
    candidates needs the number each applied with; recomputing would quietly
    reorder the list every time somebody edited their profile.
    """
    posting = db.get(JobPosting, posting_id)
    if posting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such posting.")
    if not posting.is_open():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This role is no longer accepting applications."
        )

    existing = db.execute(
        select(PostingApplication).where(
            PostingApplication.posting_id == posting_id,
            PostingApplication.profile_id == profile.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You have already applied to this role."
        )

    result = score_posting(db, profile, posting)
    application = PostingApplication(
        posting_id=posting.id,
        profile_id=profile.id,
        alignment_score=result.total,
        alignment_detail=alignment_summary(result),
        cover_note=payload.cover_note,
    )
    db.add(application)
    db.commit()
    db.refresh(application)

    logger.info(
        "profile %s applied to posting %s at %.1f alignment",
        profile.id,
        posting.id,
        result.total,
    )
    return application


@router.get("/applications", response_model=list[MyApplicationOut])
def my_applications(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> list[MyApplicationOut]:
    """Everything this student has applied to, newest first."""
    applications = list(
        db.execute(
            select(PostingApplication)
            .where(PostingApplication.profile_id == profile.id)
            .order_by(PostingApplication.applied_at.desc())
        ).scalars()
    )
    return [
        MyApplicationOut(
            application=ApplicationOut.model_validate(a),
            posting=PostingOut.model_validate(a.posting),
        )
        for a in applications
    ]


@router.delete(
    "/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT
)
def withdraw(
    application_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> None:
    """Withdraw an application.

    Deleted rather than marked withdrawn: a student who changes their mind
    before anyone has looked should not leave a permanent record in a
    recruiter's pipeline.
    """
    application = db.get(PostingApplication, application_id)
    if application is None or application.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application.")

    db.delete(application)
    db.commit()


# --------------------------------------------------------------------------- #
# Screening interviews
# --------------------------------------------------------------------------- #


def _own_application(
    db: Session, application_id: int, profile: Profile
) -> PostingApplication:
    application = db.get(PostingApplication, application_id)
    if application is None or application.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application.")
    return application


def _screening_out(
    session: InterviewSession, posting: JobPosting, *, include_feedback: bool
) -> ScreeningOut:
    """Render a round for one side or the other.

    `include_feedback` is false while the round is still open. Showing the
    candidate what a strong answer contains before they answer would make the
    score measure reading comprehension.
    """
    return ScreeningOut(
        id=session.id,
        application_id=session.application_id,
        posting_title=posting.title,
        overall_score=session.overall_score,
        summary=session.summary if include_feedback else None,
        completed_at=session.completed_at,
        turns=[
            ScreeningTurnOut(
                position=t.position,
                question=t.question,
                answer=t.answer,
                score=t.score if include_feedback else None,
                feedback=t.feedback if include_feedback else None,
                probes_skill=t.probes_skill,
            )
            for t in sorted(session.turns, key=lambda t: t.position)
        ],
    )


@router.post(
    "/applications/{application_id}/interview",
    response_model=ScreeningOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=AI_ROUTE,
)
def start_interview(
    application_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> ScreeningOut:
    """Open the screening round for an application that requires one."""
    application = _own_application(db, application_id, profile)
    posting = db.get(JobPosting, application.posting_id)
    if posting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such posting.")
    if not posting.interview_required:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This role does not ask for an interview."
        )

    try:
        session = screening.start(db, application, posting, profile)
    except screening.ScreeningError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    return _screening_out(session, posting, include_feedback=False)


@router.get("/applications/{application_id}/interview", response_model=ScreeningOut)
def read_interview(
    application_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> ScreeningOut:
    """The round as it stands — questions, and the result once submitted."""
    application = _own_application(db, application_id, profile)
    session = screening.existing_session(db, application.id)
    if session is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "You have not started this interview yet."
        )

    posting = db.get(JobPosting, application.posting_id)
    return _screening_out(
        session, posting, include_feedback=session.completed_at is not None
    )


@router.post(
    "/applications/{application_id}/interview/submit",
    response_model=ScreeningOut,
    dependencies=AI_ROUTE,
)
def submit_interview(
    application_id: int,
    payload: ScreeningSubmitIn,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> ScreeningOut:
    """Submit every answer at once and get the round graded.

    One submission, one grading pass. There is no going back afterwards — the
    employer reads this, and a round you could retake until the number suited
    you would not be worth their reading.
    """
    application = _own_application(db, application_id, profile)
    session = screening.existing_session(db, application.id)
    if session is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Start the interview before submitting it."
        )

    posting = db.get(JobPosting, application.posting_id)
    try:
        session = screening.submit(db, session, posting, payload.answers)
    except screening.ScreeningError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    return _screening_out(session, posting, include_feedback=True)
