"""Job posts, their extracted requirements, and ingestion provenance."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import EnumStr
from app.models.enums import Necessity, SourceKind

if TYPE_CHECKING:
    # See the note in application.py — this pairing is mutually referential.
    from app.models.application import Application


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobPost(Base):
    """A job, after extraction and validation."""

    __tablename__ = "job_posts"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remote: Mapped[bool | None] = mapped_column(nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(60), nullable=True)

    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)

    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(60), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Provenance ---
    source_kind: Mapped[SourceKind] = mapped_column(EnumStr(SourceKind))
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # The text the extraction agent actually saw. Kept so a re-extraction after
    # a prompt change doesn't require re-uploading the original file.
    raw_text: Mapped[str] = mapped_column(Text)

    # --- Validation agent output ---
    # 0.0-1.0. Low confidence means the validator found fields it could not
    # ground in raw_text; the UI surfaces these for manual confirmation.
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # Field names the validator could not verify, e.g. ["salary_max"].
    unverified_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    requirements: Mapped[list[JobRequirement]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )
    application: Mapped[Application | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class JobRequirement(Base):
    """One skill or tool a job asks for, with how badly it wants it."""

    __tablename__ = "job_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posts.id"), index=True)

    # Stored lowercase and trimmed, to match ProfileSkill.name.
    name: Mapped[str] = mapped_column(String(120), index=True)
    necessity: Mapped[Necessity] = mapped_column(
        EnumStr(Necessity), default=Necessity.REQUIRED
    )
    min_years: Mapped[float] = mapped_column(Float, default=0.0)

    # Verbatim span from raw_text that justified this requirement. The
    # validation agent rejects requirements it cannot quote, which is what keeps
    # the extraction honest.
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[JobPost] = relationship(back_populates="requirements")


class SkillAlias(Base):
    """Maps spelling variants onto one canonical skill name.

    Exists so alignment scoring can stay exact-match and therefore reproducible:
    "postgres" and "postgresql" resolve to the same canonical name rather than
    relying on a similarity threshold that would drift between model versions.
    """

    __tablename__ = "skill_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    canonical: Mapped[str] = mapped_column(String(120), index=True)
