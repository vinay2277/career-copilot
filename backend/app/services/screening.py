"""Screening interviews attached to an application.

A recruiter can require a short interview on a posting. A student who applies
then answers it in the app, and the recruiter sees a score, a recommendation,
and the full transcript alongside the alignment score.

Two rules shape everything here.

**The interview informs; it never decides.** The model scores the round and
writes a recommendation for the recruiter to argue with. It does not change an
application's status, and nothing in this module can. Every advance and every
rejection stays a person's action, for the same reason the alignment score
ranks a candidate list rather than trimming it.

**Two model calls per candidate, not seven.** Questions are generated once when
the interview starts; the whole round is graded in one pass when it is
submitted. Per-answer grading would cost three times as much and would stop the
model from seeing the round as a round, which is the thing a recruiter is
actually asking about.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.interview import generate_questions, grade_screening
from app.models import (
    InterviewKind,
    InterviewSession,
    InterviewTurn,
    JobPosting,
    PostingApplication,
    Profile,
)

logger = logging.getLogger(__name__)

#: Hard ceiling regardless of what a posting asks for. A screening round is a
#: filter, not the interview — and every question is transcript the model has to
#: read back when grading, so the cost grows with the square of ambition.
MAX_INTERVIEW_QUESTIONS = 8
MIN_INTERVIEW_QUESTIONS = 2

#: Below this, an answer is treated as not given. Catches "ok", "n/a" and the
#: empty string without needing the model to spend a judgement on them.
MIN_ANSWER_CHARS = 10


class ScreeningError(RuntimeError):
    """Something the caller should turn into a 4xx with this message."""


def existing_session(db: Session, application_id: int) -> InterviewSession | None:
    return db.execute(
        select(InterviewSession).where(
            InterviewSession.application_id == application_id
        )
    ).scalar_one_or_none()


def posting_text(posting: JobPosting) -> str:
    """What the question generator reads.

    Prefers the original description over the extracted fields: the generator
    writes better questions from prose than from a requirement list, and the
    list is already reflected in the requirements it is told to probe.
    """
    if posting.raw_text and len(posting.raw_text) > 80:
        return posting.raw_text
    parts = [
        f"{posting.title} at {posting.company_name}",
        posting.description or "",
        "Requirements: "
        + ", ".join(
            f"{r.name}"
            + (f" ({r.min_years:g}+ years)" if r.min_years else "")
            + f" [{r.necessity.value}]"
            for r in posting.requirements
        ),
    ]
    return "\n\n".join(p for p in parts if p)


def start(
    db: Session,
    application: PostingApplication,
    posting: JobPosting,
    profile: Profile,
) -> InterviewSession:
    """Generate the questions and open the round.

    Refuses to start a second time. A candidate who could re-sit until the
    score came out right would make the score meaningless, and the recruiter
    would have no way to tell which attempt they were reading.
    """
    if existing_session(db, application.id) is not None:
        raise ScreeningError(
            "You have already started this interview. Open it from your "
            "applications to continue."
        )

    count = max(
        MIN_INTERVIEW_QUESTIONS,
        min(posting.interview_question_count, MAX_INTERVIEW_QUESTIONS),
    )

    # What the candidate is weakest on, so the round probes what the alignment
    # score could not settle. Falls back to the required skills when the
    # application carries no breakdown.
    detail = application.alignment_detail or {}
    probe = list(detail.get("partial", [])) + list(detail.get("missing", []))
    if not probe:
        probe = [r.name for r in posting.requirements]

    generated = generate_questions(
        job_text=posting_text(posting),
        kind=InterviewKind.SCREENING.value,
        missing_skills=probe[:6],
        count=count,
    )

    session = InterviewSession(
        profile_id=profile.id,
        application_id=application.id,
        job_id=None,
        kind=InterviewKind.SCREENING,
    )
    for i, question in enumerate(generated.questions[:count], start=1):
        session.turns.append(
            InterviewTurn(
                position=i,
                question=question.question,
                # `looking_for` has nowhere of its own on the model and the
                # grader needs it, so it rides in `feedback` until the round is
                # graded and real feedback replaces it. Documented rather than
                # migrated for a field that lives for one round.
                feedback=question.looking_for,
                probes_skill=question.probes_skill,
            )
        )

    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info(
        "screening %s opened for application %s (%s questions)",
        session.id,
        application.id,
        len(session.turns),
    )
    return session


def submit(
    db: Session,
    session: InterviewSession,
    posting: JobPosting,
    answers: dict[int, str],
) -> InterviewSession:
    """Record the answers, grade the round, and close it.

    Unanswered questions are graded too, as unanswered. Letting a candidate
    skip the questions they cannot answer and be scored only on the rest would
    reward exactly the wrong thing.
    """
    if session.completed_at is not None:
        raise ScreeningError("This interview has already been submitted.")

    turns = sorted(session.turns, key=lambda t: t.position)
    if not turns:
        raise ScreeningError("This interview has no questions.")

    given = 0
    payload = []
    for turn in turns:
        answer = (answers.get(turn.position) or "").strip()
        if len(answer) < MIN_ANSWER_CHARS:
            answer = ""
        else:
            given += 1
        payload.append(
            {
                "position": turn.position,
                "question": turn.question,
                # Still holding `looking_for` at this point — see start().
                "looking_for": turn.feedback or "",
                "answer": answer,
            }
        )
        turn.answer = answer or None

    if given == 0:
        raise ScreeningError(
            "Answer at least one question before submitting. A blank round "
            "tells the employer nothing and cannot be retaken."
        )

    result = grade_screening(job_text=posting_text(posting), answers=payload)

    by_position = {g.position: g for g in result.grades}
    for turn in turns:
        grade = by_position.get(turn.position)
        if grade is None:
            # The model skipped one. Better an unscored turn with its answer
            # intact than a number nobody can trace to a judgement.
            turn.feedback = None
            continue
        turn.score = grade.score
        turn.feedback = grade.feedback

    session.overall_score = result.overall_score
    session.summary = _summary(result)
    session.completed_at = datetime.now(UTC)

    db.commit()
    db.refresh(session)
    logger.info(
        "screening %s submitted, scored %.1f", session.id, session.overall_score
    )
    return session


def _summary(result) -> str:
    """Flatten the model's read into the one text column the session has."""
    parts = [result.recommendation.strip()]
    if result.strengths:
        parts.append("Strengths: " + "; ".join(result.strengths))
    if result.concerns:
        parts.append("Concerns: " + "; ".join(result.concerns))
    return "\n\n".join(parts)
