"""Mock interviews, learning roadmaps, and tailored resumes.

These are the diagram-1 coaching features: everything downstream of the
career intelligence agent's three branches.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import EnumStr
from app.models.enums import InterviewKind

if TYPE_CHECKING:
    from app.models.profile import Profile


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
    #: Set when this is a screening interview attached to a real application,
    #: rather than the student practising on their own. One per application:
    #: a candidate does not get to re-sit a screen until they like the score.
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("posting_applications.id"), nullable=True, unique=True, index=True
    )
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


class ModuleProgress(Base):
    """One student's standing on one module of the Gen AI curriculum.

    A row exists only once somebody has attempted the module, so absence means
    "not started" and there is nothing to create when a student first opens the
    tab. The curriculum itself lives in `services/curriculum.py`, not here —
    content belongs in code where it can be reviewed, and only progress is
    anybody's data.
    """

    __tablename__ = "module_progress"
    __table_args__ = (
        # One row per student per module. The database enforces it because two
        # submissions racing would otherwise leave two conflicting records of
        # whether somebody passed.
        UniqueConstraint("profile_id", "module_slug", name="uq_module_progress"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)

    #: Matches `curriculum.Module.slug`. Stored rather than a foreign key
    #: because the curriculum is code: a slug that disappears in a later edit
    #: should leave an orphaned progress row, not break the schema.
    module_slug: Mapped[str] = mapped_column(String(80), index=True)

    #: Correct answers on the best attempt so far. Best rather than latest, so
    #: revisiting a passed module to re-read it cannot take the pass away.
    best_score: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    #: Set once, on the first passing attempt, and never cleared.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    profile: Mapped[Profile] = relationship()
