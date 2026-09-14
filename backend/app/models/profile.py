"""Candidate profile, skills, preferences, and resumes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import EnumStr
from app.models.enums import Proficiency

if TYPE_CHECKING:
    from app.models.account import Account


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Profile(Base):
    """A student's career profile. One per student account."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The tenant boundary. Unique because a student has exactly one profile,
    # and the database should be the thing that guarantees it rather than
    # every call site remembering to check.
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), unique=True, index=True
    )

    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(300), nullable=True)
    years_experience: Mapped[float] = mapped_column(Float, default=0.0)

    # Free-text career goal. Feeds the career intelligence agent's prompt.
    career_goal: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Recruiter visibility ---
    # Off by default, and deliberately so. Uploading a résumé to get job matches
    # is not the same act as agreeing to appear in a stranger's candidate
    # search, and treating them as one is how a platform loses trust.
    visible_to_recruiters: Mapped[bool] = mapped_column(default=False)
    open_to_work: Mapped[bool] = mapped_column(default=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    account: Mapped[Account] = relationship(back_populates="profile")

    skills: Mapped[list[ProfileSkill]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", lazy="selectin"
    )
    preferences: Mapped[Preferences | None] = relationship(
        back_populates="profile", cascade="all, delete-orphan", uselist=False
    )
    resumes: Mapped[list[Resume]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class ProfileSkill(Base):
    """One skill the candidate claims, at a stated proficiency."""

    __tablename__ = "profile_skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)

    # Stored lowercase and trimmed. Matching is exact on this column plus the
    # alias table, never fuzzy — see services/analytics/alignment.py.
    name: Mapped[str] = mapped_column(String(120), index=True)
    proficiency: Mapped[Proficiency] = mapped_column(
        EnumStr(Proficiency), default=Proficiency.WORKING
    )
    years: Mapped[float] = mapped_column(Float, default=0.0)

    profile: Mapped[Profile] = relationship(back_populates="skills")


class Preferences(Base):
    """What the candidate wants. Drives the 30% preference half of alignment."""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), unique=True)

    # Each list is stored as JSON; order is meaningless, membership is what counts.
    target_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote_ok: Mapped[bool] = mapped_column(default=True)
    seniority: Mapped[str | None] = mapped_column(String(60), nullable=True)
    min_salary: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    company_sizes: Mapped[list[str]] = mapped_column(JSON, default=list)
    industries: Mapped[list[str]] = mapped_column(JSON, default=list)

    profile: Mapped[Profile] = relationship(back_populates="preferences")


class Resume(Base):
    """An uploaded resume plus the analysis agent's verdict on it."""

    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)

    filename: Mapped[str] = mapped_column(String(300))
    raw_text: Mapped[str] = mapped_column(Text)

    # Populated by the resume analysis agent. Null until analysis runs.
    ats_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    strengths: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    gaps: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    analysis_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_primary: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    profile: Mapped[Profile] = relationship(back_populates="resumes")
