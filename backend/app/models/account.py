"""Accounts, organizations, and the link between them.

The account is the tenant boundary. Every row that belongs to somebody hangs
off one, and every query filters on it — which is the whole difference between
this and the single-user version it replaces.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import EnumStr
from app.models.enums import Role

if TYPE_CHECKING:
    from app.models.profile import Profile


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Account(Base):
    """A person who can sign in."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Stored lowercased and stripped — see `normalize_email`. Unique, so the
    # database refuses a duplicate even if two registrations race.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))

    role: Mapped[Role] = mapped_column(EnumStr(Role), index=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")

    # Null until the address is confirmed. Kept separate from `is_active` so a
    # verified account can still be suspended, and an unverified one can still
    # be let in during a pilot where email delivery isn't wired up yet.
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    profile: Mapped[Profile | None] = relationship(
        back_populates="account", cascade="all, delete-orphan", uselist=False
    )
    hr_membership: Mapped[HRMember | None] = relationship(
        back_populates="account", cascade="all, delete-orphan", uselist=False
    )

    @property
    def is_student(self) -> bool:
        return self.role is Role.STUDENT

    @property
    def is_hr(self) -> bool:
        return self.role is Role.HR


class Organization(Base):
    """An employer.

    `verified_at` gates job posting. An unverified organization posting roles
    is how a hiring platform becomes a résumé-harvesting operation — anyone can
    claim to be recruiting, and students hand over phone numbers on that claim.
    """

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)

    # Email domain that proves membership, e.g. "cisco.com". Used to auto-admit
    # further HR sign-ups from the same company once one is approved.
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)

    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    members: Mapped[list[HRMember]] = relationship(
        back_populates="organization", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None


class HRMember(Base):
    """Links an HR account to the organization it recruits for."""

    __tablename__ = "hr_members"
    __table_args__ = (UniqueConstraint("account_id", name="uq_hr_member_account"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    account: Mapped[Account] = relationship(back_populates="hr_membership")
    organization: Mapped[Organization] = relationship(back_populates="members")
