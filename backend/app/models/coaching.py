"""Mock interviews, learning roadmaps, and tailored resumes.

These are the diagram-1 coaching features: everything downstream of the
career intelligence agent's three branches.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import EnumStr
from app.models.enums import InterviewKind


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Interview prep
# --------------------------------------------------------------------------- #


class InterviewSession(Base):
    """One mock interview run against one job."""

    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_posts.id"), nullable=True, index=True
    )

    kind: Mapped[InterviewKind] = mapped_column(
        EnumStr(InterviewKind), default=InterviewKind.BEHAVIORAL
    )
    # Null until the session is graded.
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    turns: Mapped[list[InterviewTurn]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="InterviewTurn.position",
        lazy="selectin",
    )


class InterviewTurn(Base):
    """A question, the candidate's answer, and the feedback on it."""

    __tablename__ = "interview_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("interview_sessions.id"), index=True
    )

    position: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)

    # Null while the question is still outstanding.
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Concrete rewrite suggestions, e.g. "quantify the impact in the last line".
    improvements: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Which job requirement this question probes, if any. Lets interview prep
    # target the same gaps the alignment scorer found.
    probes_skill: Mapped[str | None] = mapped_column(String(120), nullable=True)

    session: Mapped[InterviewSession] = relationship(back_populates="turns")


# --------------------------------------------------------------------------- #
# Learning roadmap
# --------------------------------------------------------------------------- #


class LearningPath(Base):
    """A sequenced plan for closing one or more skill gaps."""

    __tablename__ = "learning_paths"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)

    title: Mapped[str] = mapped_column(String(300))
    # The skills this path closes. Cross-referenced against the skill ROI engine
    # so the UI can show what each path unlocks.
    target_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    steps: Mapped[list[LearningStep]] = relationship(
        back_populates="path",
        cascade="all, delete-orphan",
        order_by="LearningStep.position",
        lazy="selectin",
    )


class LearningStep(Base):
    """One unit of study in a path."""

    __tablename__ = "learning_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    path_id: Mapped[int] = mapped_column(ForeignKey("learning_paths.id"), index=True)

    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    skill: Mapped[str] = mapped_column(String(120))
    estimated_hours: Mapped[float] = mapped_column(Float, default=0.0)
    resource_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # How the candidate proves to themselves the step is done.
    proof_of_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed: Mapped[bool] = mapped_column(default=False)

    path: Mapped[LearningPath] = relationship(back_populates="steps")


# --------------------------------------------------------------------------- #
# Resume tailoring
# --------------------------------------------------------------------------- #


class TailoredResume(Base):
    """A job-specific rewrite of the candidate's primary resume."""

    __tablename__ = "tailored_resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posts.id"), index=True)
    source_resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"))

    content: Mapped[str] = mapped_column(Text)
    # Requirement names the rewrite now surfaces that the original buried.
    emphasized_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Human-readable diff summary, so the candidate can see what changed and
    # confirm nothing was fabricated.
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
