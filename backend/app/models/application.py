"""Application tracking and status history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import EnumStr
from app.models.enums import ApplicationStatus

if TYPE_CHECKING:
    # Import-time only: job.py imports this module, so a runtime import here
    # would be circular. SQLAlchemy resolves the relationship by registry name.
    from app.models.job import JobPost


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Application(Base):
    """The candidate's pipeline entry for one job."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_posts.id"), unique=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)

    status: Mapped[ApplicationStatus] = mapped_column(
        EnumStr(ApplicationStatus), default=ApplicationStatus.SAVED, index=True
    )

    # Alignment score cached at the moment of saving, so the Kanban board and
    # the funnel analysis don't re-run scoring on every page load. Recomputed
    # when the profile or the job changes.
    alignment_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    job: Mapped[JobPost] = relationship(back_populates="application")
    events: Mapped[list[StatusEvent]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="StatusEvent.occurred_at",
        lazy="selectin",
    )


class StatusEvent(Base):
    """An append-only record of every status transition.

    The funnel and stagnation analytics read this table, not `Application.status`
    — current status alone can't tell you how long a stage took or whether a
    stage was skipped.
    """

    __tablename__ = "status_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), index=True
    )

    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        EnumStr(ApplicationStatus), nullable=True
    )
    to_status: Mapped[ApplicationStatus] = mapped_column(EnumStr(ApplicationStatus))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    application: Mapped[Application] = relationship(back_populates="events")
