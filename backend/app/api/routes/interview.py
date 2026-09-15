"""`/api/interview/*` — mock interviews and answer feedback."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.client import AgentError
from app.agents.interview import generate_questions, grade_answer, summarize_session
from app.api.deps import get_profile
from app.core.security import rate_limit_ai
from app.db.session import get_db
from app.models import InterviewSession, InterviewTurn, Profile
from app.schemas import AnswerIn, InterviewSessionOut, InterviewStartIn, TurnOut
from app.services.postings import (
    posting_for_student,
    posting_text_for_agents,
    score_posting,
)

router = APIRouter(prefix="/api/interview", tags=["interview"])

#: Routes that call a model. Listing and reading sessions do not.
AI = [Depends(rate_limit_ai)]

#: What a strong answer contains, per question. Generated alongside the
#: question and needed again at grading time, but not worth its own column —
#: it is regenerated context, not user data, so it lives in the turn's
#: feedback field prefix until the answer arrives.
_LOOKING_FOR_PREFIX = "Looking for: "


@router.get("", response_model=list[InterviewSessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> list[InterviewSession]:
    return list(
        db.execute(
            select(InterviewSession)
            .where(InterviewSession.profile_id == profile.id)
            .order_by(InterviewSession.created_at.desc())
        ).scalars()
    )


@router.post(
    "",
    response_model=InterviewSessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=AI,
)
def start_session(
    payload: InterviewStartIn,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> InterviewSession:
    """Generate a mock round for one job.

    Questions are weighted toward the gaps the alignment scorer found, because
    that is where a real interview will press hardest.
    """
    job = posting_for_student(db, payload.job_id)
    if job is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No such open role on the board."
        )

    alignment = score_posting(db, profile, job)
    gaps = [r.name for r in alignment.missing + alignment.partial]

    try:
        generated = generate_questions(
            job_text=posting_text_for_agents(job),
            kind=payload.kind.value,
            missing_skills=gaps,
            count=payload.question_count,
        )
    except AgentError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    session = InterviewSession(
        profile_id=profile.id,
        job_id=job.id,
        kind=payload.kind,
        summary=generated.opening_note,
    )
    for i, q in enumerate(generated.questions):
        session.turns.append(
            InterviewTurn(
                position=i,
                question=q.question,
                probes_skill=q.probes_skill,
                # Stashed here so grading has the rubric without a second
                # generation call; overwritten by real feedback on answer.
                feedback=f"{_LOOKING_FOR_PREFIX}{q.looking_for}",
            )
        )

    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/{session_id}", response_model=InterviewSessionOut)
def read_session(
    session_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None or session.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session.")
    return session


@router.post(
    "/{session_id}/turns/{position}/answer",
    response_model=TurnOut,
    dependencies=AI,
)
def submit_answer(
    session_id: int,
    position: int,
    payload: AnswerIn,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> InterviewTurn:
    """Answer one question and get it graded."""
    session = db.get(InterviewSession, session_id)
    if session is None or session.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session.")

    turn = next((t for t in session.turns if t.position == position), None)
    if turn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such question.")

    rubric = ""
    if turn.feedback and turn.feedback.startswith(_LOOKING_FOR_PREFIX):
        rubric = turn.feedback[len(_LOOKING_FOR_PREFIX) :]

    try:
        graded = grade_answer(
            question=turn.question, looking_for=rubric, answer=payload.answer
        )
    except AgentError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    turn.answer = payload.answer
    turn.score = graded.score
    turn.feedback = graded.feedback
    turn.improvements = graded.improvements
    if not graded.answered_the_question:
        turn.improvements = [
            "This didn't answer what was asked — reread the question first.",
            *(graded.improvements or []),
        ]

    db.commit()
    db.refresh(turn)
    return turn


@router.post(
    "/{session_id}/complete", response_model=InterviewSessionOut, dependencies=AI
)
def complete_session(
    session_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> InterviewSession:
    """Grade the session as a whole once the answers are in.

    Unanswered questions are excluded rather than scored zero — a session the
    user stopped halfway through should report on what they did, not punish them
    for stopping.
    """
    session = db.get(InterviewSession, session_id)
    if session is None or session.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session.")

    answered = [t for t in session.turns if t.answer and t.score is not None]
    if not answered:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No answers to summarize yet."
        )

    try:
        summary = summarize_session(
            [
                {
                    "question": t.question,
                    "answer": t.answer,
                    "score": t.score,
                    "feedback": t.feedback or "",
                }
                for t in answered
            ]
        )
    except AgentError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    session.overall_score = summary.overall_score
    session.summary = summary.summary
    if summary.focus_before_the_real_thing:
        session.summary += "\n\nBefore the real round:\n" + "\n".join(
            f"- {item}" for item in summary.focus_before_the_real_thing
        )
    session.completed_at = datetime.now(UTC)

    db.commit()
    db.refresh(session)
    return session
