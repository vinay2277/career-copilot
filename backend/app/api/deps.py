"""Shared route dependencies.

These are the authorization boundary. Every route that touches owned data goes
through one of them, and each returns a subject the handler can trust — an
authenticated account, a profile that account owns, an organization it may act
for. Handlers never re-derive who the caller is.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import rate_limit_ai, rate_limit_api
from app.db.session import get_db
from app.models import Account, Organization, Profile, Role

logger = logging.getLogger(__name__)

#: Session key holding the signed-in account id. Must match what
#: `core.security.client_key` reads, or rate limits fall back to IP for
#: authenticated callers.
SESSION_ACCOUNT = "account_id"


def get_current_account(
    request: Request, db: Session = Depends(get_db)
) -> Account:
    """The signed-in account, or 401.

    Reads the id from the signed session cookie and loads the row fresh on every
    request — so a suspended or deleted account stops working immediately rather
    than lasting until its cookie expires.
    """
    account_id = request.session.get(SESSION_ACCOUNT)
    if account_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Not signed in."
        )

    account = db.get(Account, account_id)
    if account is None or not account.is_active:
        # The session names an account that is gone or suspended. Clear it, so
        # the browser stops presenting a credential that will never work again.
        request.session.clear()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "That session is no longer valid."
        )

    return account


def get_optional_account(
    request: Request, db: Session = Depends(get_db)
) -> Account | None:
    """The signed-in account if there is one, else None. Never raises.

    For routes that serve both — a posting page that shows an Apply button to a
    signed-in student and a Sign up prompt to everyone else.
    """
    account_id = request.session.get(SESSION_ACCOUNT)
    if account_id is None:
        return None
    account = db.get(Account, account_id)
    return account if account is not None and account.is_active else None


def require_student(account: Account = Depends(get_current_account)) -> Account:
    if account.role is not Role.STUDENT:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This is only available to students."
        )
    return account


def require_hr(account: Account = Depends(get_current_account)) -> Account:
    if account.role not in (Role.HR, Role.ADMIN):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This is only available to recruiters."
        )
    return account


def require_admin(account: Account = Depends(get_current_account)) -> Account:
    if account.role is not Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrators only.")
    return account


def get_profile(
    account: Account = Depends(require_student),
    db: Session = Depends(get_db),
) -> Profile:
    """The signed-in student's own profile.

    Created if missing. Registration makes one, so this only fires for accounts
    that predate that — but a student who exists without a profile is a state no
    route wants to handle, and 404ing here would break every page they own.
    """
    profile = db.execute(
        select(Profile).where(Profile.account_id == account.id)
    ).scalar_one_or_none()

    if profile is None:
        logger.info("Student %s had no profile; creating one.", account.id)
        profile = Profile(
            account_id=account.id,
            full_name=account.full_name,
            email=account.email,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return profile


def get_organization(
    account: Account = Depends(require_hr),
    db: Session = Depends(get_db),
) -> Organization:
    """The organization this recruiter acts for."""
    membership = account.hr_membership
    if membership is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This account isn't attached to an organization yet.",
        )
    return membership.organization


def require_verified_organization(
    organization: Organization = Depends(get_organization),
) -> Organization:
    """An organization allowed to publish postings and see candidates.

    Registration stays open; posting does not. An unverified organization
    publishing roles is how a hiring platform turns into a résumé-harvesting
    operation — anyone can claim to be recruiting, and students hand over phone
    numbers on that claim.

    `REQUIRE_ORG_VERIFICATION=false` relaxes this for a pilot where you know
    every recruiter personally. It should be true anywhere public.
    """
    if not settings.require_org_verification:
        return organization

    if not organization.is_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Your organization is awaiting verification before it can post "
            "roles or view candidates.",
        )
    return organization


# --------------------------------------------------------------------------- #
# Router bundles
#
# Applied at `include_router` rather than per route, so a router added later
# cannot arrive unauthenticated by accident.
# --------------------------------------------------------------------------- #

#: Any signed-in account.
AUTHENTICATED = [Depends(get_current_account), Depends(rate_limit_api)]

#: Signed-in students only.
STUDENT_ONLY = [Depends(require_student), Depends(rate_limit_api)]

#: Signed-in recruiters only.
HR_ONLY = [Depends(require_hr), Depends(rate_limit_api)]

#: Add to an individual route that calls a model, on top of the router bundle.
AI_ROUTE = [Depends(rate_limit_ai)]
