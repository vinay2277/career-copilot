"""`/api/admin/*` — approving organizations.

Verification is the control that stops anyone registering as a recruiter and
harvesting students' contact details behind a fake role. It is therefore a
human decision, and this is where a human makes it.

Deliberately small. Everything here is reversible, and nothing exposes a
student's data — an administrator approving companies has no reason to read
résumés.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import Account, HRMember, JobPosting, Organization, Role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class OrganizationRowOut(BaseModel):
    """An organization awaiting or holding approval.

    Carries the facts needed to make the decision — who registered, on what
    email domain, how long ago — and nothing else.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    domain: str | None
    website: str | None
    is_verified: bool
    created_at: datetime
    member_count: int
    posting_count: int
    #: Emails of the recruiters attached, so a reviewer can see whether the
    #: domain matches the company being claimed.
    member_emails: list[str]


class AdminStatsOut(BaseModel):
    organizations: int
    awaiting_verification: int
    students: int
    recruiters: int
    open_postings: int


def _rows(db: Session, organizations: list[Organization]) -> list[OrganizationRowOut]:
    """Attach counts in two grouped queries rather than per organization."""
    ids = [o.id for o in organizations]
    if not ids:
        return []

    posting_counts = dict(
        db.execute(
            select(JobPosting.organization_id, func.count(JobPosting.id))
            .where(JobPosting.organization_id.in_(ids))
            .group_by(JobPosting.organization_id)
        ).all()
    )

    emails: dict[int, list[str]] = {}
    for org_id, email in db.execute(
        select(HRMember.organization_id, Account.email)
        .join(Account, Account.id == HRMember.account_id)
        .where(HRMember.organization_id.in_(ids))
    ).all():
        emails.setdefault(org_id, []).append(email)

    return [
        OrganizationRowOut(
            id=o.id,
            name=o.name,
            domain=o.domain,
            website=o.website,
            is_verified=o.is_verified,
            created_at=o.created_at,
            member_count=len(emails.get(o.id, [])),
            posting_count=posting_counts.get(o.id, 0),
            member_emails=sorted(emails.get(o.id, [])),
        )
        for o in organizations
    ]


@router.get("/organizations", response_model=list[OrganizationRowOut])
def list_organizations(
    db: Session = Depends(get_db),
    _: Account = Depends(require_admin),
    pending_only: bool = Query(
        default=False, description="Only those awaiting a decision."
    ),
) -> list[OrganizationRowOut]:
    """Organizations, unverified first.

    Unverified first because those are the ones waiting on somebody, and a
    queue sorted by anything else is a queue people stop working through.
    """
    stmt = select(Organization)
    if pending_only:
        stmt = stmt.where(Organization.verified_at.is_(None))

    organizations = list(
        db.execute(
            stmt.order_by(
                Organization.verified_at.is_(None).desc(),
                Organization.created_at.desc(),
            )
        ).scalars()
    )
    return _rows(db, organizations)


@router.post("/organizations/{organization_id}/verify", response_model=OrganizationRowOut)
def verify_organization(
    organization_id: int,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
) -> OrganizationRowOut:
    """Approve an organization, letting it publish roles and see candidates."""
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such organization.")

    if organization.verified_at is None:
        organization.verified_at = datetime.now(UTC)
        db.commit()
        logger.warning(
            "admin %s verified organization %s (%s)",
            admin.id,
            organization.id,
            organization.name,
        )

    return _rows(db, [organization])[0]


@router.post(
    "/organizations/{organization_id}/unverify", response_model=OrganizationRowOut
)
def unverify_organization(
    organization_id: int,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
) -> OrganizationRowOut:
    """Withdraw approval.

    Published roles stay up and applications are untouched — revoking approval
    is not a reason to delete a student's application record. What stops is
    publishing anything new and seeing candidates.
    """
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such organization.")

    organization.verified_at = None
    db.commit()
    logger.warning(
        "admin %s withdrew verification from organization %s", admin.id, organization.id
    )
    return _rows(db, [organization])[0]


@router.get("/stats", response_model=AdminStatsOut)
def stats(
    db: Session = Depends(get_db), _: Account = Depends(require_admin)
) -> AdminStatsOut:
    """Counts for the admin landing page."""
    from app.models import PostingStatus

    def count(stmt) -> int:
        return db.execute(stmt).scalar_one()

    return AdminStatsOut(
        organizations=count(select(func.count()).select_from(Organization)),
        awaiting_verification=count(
            select(func.count())
            .select_from(Organization)
            .where(Organization.verified_at.is_(None))
        ),
        students=count(
            select(func.count()).select_from(Account).where(Account.role == Role.STUDENT)
        ),
        recruiters=count(
            select(func.count()).select_from(Account).where(Account.role == Role.HR)
        ),
        open_postings=count(
            select(func.count())
            .select_from(JobPosting)
            .where(JobPosting.status == PostingStatus.OPEN)
        ),
    )
