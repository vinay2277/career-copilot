"""Account creation and sign-in.

Kept out of the route layer because registration has to do several things
atomically — create the account, hash the password, provision the role's
side table — and that is a transaction, not a handler.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.passwords import (
    hash_password,
    needs_rehash,
    normalize_email,
    verify_password,
)
from app.models import Account, HRMember, Organization, Profile, Role

logger = logging.getLogger(__name__)


class RegistrationError(ValueError):
    """Registration cannot proceed. The message is shown to the user."""


def find_by_email(db: Session, email: str) -> Account | None:
    return db.execute(
        select(Account).where(Account.email == normalize_email(email))
    ).scalar_one_or_none()


def register_student(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
) -> Account:
    """Create a student account and its empty profile.

    The profile is created here rather than lazily, because every student route
    needs one and a student who exists without a profile is a state no part of
    the app wants to handle.
    """
    account = _create_account(
        db, email=email, password=password, full_name=full_name, role=Role.STUDENT
    )
    db.add(
        Profile(
            account_id=account.id,
            full_name=full_name,
            email=account.email,
        )
    )
    db.commit()
    db.refresh(account)
    return account


def register_hr(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    organization_name: str,
    title: str | None = None,
) -> Account:
    """Create an HR account and attach it to an organization.

    An organization matching the email's domain is reused; otherwise a new
    unverified one is created. Unverified organizations cannot publish
    postings — see `require_verified_organization` — so registration stays open
    while posting stays gated.
    """
    account = _create_account(
        db, email=email, password=password, full_name=full_name, role=Role.HR
    )

    domain = account.email.partition("@")[2] or None
    organization = _organization_for(db, domain, organization_name)

    db.add(
        HRMember(
            account_id=account.id,
            organization_id=organization.id,
            title=title,
        )
    )
    db.commit()
    db.refresh(account)
    return account


def _organization_for(
    db: Session, domain: str | None, name: str
) -> Organization:
    """Find the organization for this domain, or create it unverified.

    Matching on domain is what lets the second recruiter from a company join an
    already-approved organization without a second manual approval. Free
    webmail domains are excluded — otherwise every gmail.com recruiter would
    join one shared "organization".
    """
    FREE_MAIL = {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.in",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "proton.me",
        "protonmail.com",
        "icloud.com",
        "rediffmail.com",
    }

    if domain and domain not in FREE_MAIL:
        existing = db.execute(
            select(Organization).where(Organization.domain == domain)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    organization = Organization(
        name=name.strip() or (domain or "Unnamed organization"),
        domain=domain if domain not in FREE_MAIL else None,
    )
    db.add(organization)
    db.flush()
    return organization


def _create_account(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    role: Role,
) -> Account:
    """Insert the account row. Caller commits."""
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise RegistrationError("That doesn't look like an email address.")

    # Checked up front for a clear message, and enforced again by the unique
    # index below — the gap between the two is a real race when two people
    # register the same address at once.
    if find_by_email(db, normalized) is not None:
        raise RegistrationError("An account with that email already exists.")

    account = Account(
        email=normalized,
        password_hash=hash_password(password),
        role=role,
        full_name=full_name.strip(),
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise RegistrationError("An account with that email already exists.") from e

    return account


def authenticate(db: Session, *, email: str, password: str) -> Account | None:
    """Return the account when the credentials are right, else None.

    A missing account still runs a hash verification against a dummy value, so
    an attacker cannot tell a registered address from an unregistered one by
    timing the response — without it, "no such user" returns in microseconds
    and "wrong password" takes the full Argon2 work factor.
    """
    account = find_by_email(db, email)

    if account is None:
        _burn_time(password)
        return None

    if not verify_password(password, account.password_hash):
        return None

    if not account.is_active:
        logger.info("Sign-in refused for suspended account %s", account.id)
        return None

    # Transparent upgrade when the library's defaults tighten.
    if needs_rehash(account.password_hash):
        account.password_hash = hash_password(password)

    account.last_login_at = datetime.now(UTC)
    db.commit()
    return account


_DUMMY_HASH: str | None = None


def _burn_time(password: str) -> None:
    """Spend roughly the same time a real verification would."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("not-a-real-password-placeholder")
    verify_password(password, _DUMMY_HASH)


def bootstrap_from_env(db: Session) -> None:
    """Ensure the account named by BOOTSTRAP_ADMIN_* exists and can sign in.

    Exists because a hosted deployment often has no shell. The migration adopts
    a pre-existing profile onto an account with no usable password, and on a
    platform where you cannot run `scripts/set_password.py` that would lock the
    owner out of their own data permanently.

    Idempotent, and deliberately narrow:

    * If no account has that email, one is created with the given password and
      linked to any orphaned profile.
    * If one exists, only its password is reset — the role and everything it
      owns are left alone.

    Clear both variables once you are in. Leaving them set means the password
    is reapplied on every restart, so changing it in the app would silently
    revert at the next deploy.
    """
    from app.core.config import settings

    email = settings.bootstrap_admin_email.strip()
    password = settings.bootstrap_admin_password

    if not email or not password:
        return

    normalized = normalize_email(email)
    account = find_by_email(db, normalized)

    try:
        password_hash = hash_password(password)
    except ValueError as e:
        logger.error("BOOTSTRAP_ADMIN_PASSWORD rejected: %s", e)
        return

    if account is None:
        # No account with that address. Before creating one, check for a single
        # locked-out account — the migration's output when the original profile
        # had no email on it, in which case the account is named
        # `legacy-N@invalid` and owns all the real data. Creating a fresh
        # account here would strand that data behind an address nobody knows.
        #
        # Narrow on purpose: exactly one account, and it must already be unable
        # to sign in, so this can never take over a working account.
        locked = (
            db.execute(select(Account).where(Account.password_hash == "!"))
            .scalars()
            .all()
        )
        total = db.execute(select(func.count()).select_from(Account)).scalar_one()

        if len(locked) == 1 and total == 1:
            account = locked[0]
            logger.warning(
                "Claiming the locked account %s as %s — it was the only one and "
                "could not sign in.",
                account.email,
                normalized,
            )
            account.email = normalized
            account.password_hash = password_hash
            account.is_active = True
            db.commit()
            return

        try:
            role = Role(settings.bootstrap_admin_role.strip().lower())
        except ValueError:
            logger.error(
                "BOOTSTRAP_ADMIN_ROLE %r is not a role; using student.",
                settings.bootstrap_admin_role,
            )
            role = Role.STUDENT

        account = Account(
            email=normalized,
            password_hash=password_hash,
            role=role,
            full_name=email.partition("@")[0],
        )
        db.add(account)
        db.flush()

        # Only a student has a profile. An administrator approving companies
        # has no board, no résumé and no skills — giving them one would put an
        # empty profile in every count on the platform.
        if role is Role.STUDENT:
            db.add(
                Profile(
                    account_id=account.id,
                    full_name=account.full_name,
                    email=normalized,
                )
            )

        logger.warning(
            "Created bootstrap account %s (%s) from the environment.",
            normalized,
            role.value,
        )
    else:
        account.password_hash = password_hash
        account.is_active = True
        logger.warning(
            "Reset the password for %s from BOOTSTRAP_ADMIN_PASSWORD. "
            "Clear that variable once you have signed in.",
            normalized,
        )

    db.commit()


def account_count(db: Session, role: Role | None = None) -> int:
    stmt = select(func.count()).select_from(Account)
    if role is not None:
        stmt = stmt.where(Account.role == role)
    return db.execute(stmt).scalar_one()
