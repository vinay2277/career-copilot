"""Published job postings and the applications students make to them.

Distinct from `JobPost`, which is a student's own private tracker for a role
they pasted in themselves. A posting is published once and applied to by many
students, so it needs an owner, a lifecycle, and a fixed set of requirements
every applicant is scored against identically.

Keeping them separate rather than merging was deliberate: the private tracker
already holds real data and works, and the two have genuinely different
lifecycles — nobody closes a job they pasted into their own notes.
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
from app.models.enums import (
    ApplicationStatus,
    Necessity,
    PostingSource,
    PostingStatus,
)

if TYPE_CHECKING:
    from app.models.account import Account, Organization
    from app.models.profile import Profile


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobPosting(Base):
    """A role published on the platform."""

    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Null for a sourced posting — nobody here published it, we found it.
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    posted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True, index=True
    )

    #: Which of the two sections a student sees this under.
    source: Mapped[PostingSource] = mapped_column(
        EnumStr(PostingSource), default=PostingSource.EMPLOYER, index=True
    )
    status: Mapped[PostingStatus] = mapped_column(
        EnumStr(PostingStatus), default=PostingStatus.DRAFT, index=True
    )

    title: Mapped[str] = mapped_column(String(300))
    #: Denormalized so a sourced posting can name a company we have no
    #: organization row for, and so the board doesn't join on every render.
    company_name: Mapped[str] = mapped_column(String(200))

    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remote: Mapped[bool | None] = mapped_column(nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(60), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(60), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What the extraction agent read, kept for re-extraction and for the
    #: interview generator in phase 3.
    raw_text: Mapped[str] = mapped_column(Text, default="")

    # Screening criteria, held apart from requirements so they never reach the
    # scorer — a degree is not a skill anyone can be matched on.
    education: Mapped[str | None] = mapped_column(String(300), nullable=True)
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    total_years_experience: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    extraction_confidence: Mapped[float] = mapped_column(Float, default=1.0)

    # --- Screening interview ---
    # Off by default. Every interview costs two model calls, so turning this on
    # for a role that will draw hundreds of applicants is a spending decision
    # the recruiter should make deliberately rather than inherit.
    interview_required: Mapped[bool] = mapped_column(default=False)
    #: Capped low on purpose — see `MAX_INTERVIEW_QUESTIONS`. Five good
    #: questions tell you more than twelve that nobody finishes.
    interview_question_count: Mapped[int] = mapped_column(Integer, default=4)

    opens_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: After this the posting stops accepting applications. A board that
    #: silently fills with filled roles is worse than an empty one.
    closes_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    organization: Mapped[Organization | None] = relationship()
    posted_by: Mapped[Account | None] = relationship()
    requirements: Mapped[list[PostingRequirement]] = relationship(
        back_populates="posting", cascade="all, delete-orphan", lazy="selectin"
    )
    applications: Mapped[list[PostingApplication]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )

    def is_open(self, *, now: datetime | None = None) -> bool:
        """Whether a student can apply right now.

        Status and dates both have to agree: a posting left OPEN past its
        closing date is closed in every sense that matters to an applicant.
        """
        if self.status is not PostingStatus.OPEN:
            return False

        now = now or datetime.now(UTC)
        # SQLite hands back naive datetimes; assume UTC rather than crash on a
        # mixed-awareness comparison.
        for boundary, closed_when_past in ((self.opens_at, False), (self.closes_at, True)):
            if boundary is None:
                continue
            aware = boundary if boundary.tzinfo else boundary.replace(tzinfo=UTC)
            if closed_when_past and now > aware:
                return False
            if not closed_when_past and now < aware:
                return False
        return True


class PostingRequirement(Base):
    """One skill a posting asks for.

    Separate from `JobRequirement` because that belongs to a student's private
    tracker. Same shape, different owner.
    """

    __tablename__ = "posting_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_postings.id"), index=True
    )

    name: Mapped[str] = mapped_column(String(120), index=True)
    necessity: Mapped[Necessity] = mapped_column(
        EnumStr(Necessity), default=Necessity.REQUIRED
    )
    min_years: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    posting: Mapped[JobPosting] = relationship(back_populates="requirements")


class PostingApplication(Base):
    """A student's application to a published posting."""

    __tablename__ = "posting_applications"
    __table_args__ = (
        # One application per student per posting. Enforced by the database
        # because a double-click is otherwise enough to create two.
        UniqueConstraint("posting_id", "profile_id", name="uq_application_once"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id"), index=True)

    status: Mapped[ApplicationStatus] = mapped_column(
        EnumStr(ApplicationStatus), default=ApplicationStatus.APPLIED, index=True
    )

    #: The alignment score at the moment of applying, kept rather than
    #: recomputed. A recruiter ranking candidates needs the number the student
    #: actually applied with — recomputing later would silently reorder the
    #: list as people edit their profiles.
    alignment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The per-requirement breakdown behind that score, so a ranking can always
    #: be explained without re-deriving it.
    alignment_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    cover_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    applied_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )

    posting: Mapped[JobPosting] = relationship(back_populates="applications")
    profile: Mapped[Profile] = relationship()
