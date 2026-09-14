"""`/api/auth/*` — registration and sign-in.

Outside the authenticated dependency for the obvious reason, but rate-limited:
these are the endpoints an attacker can usefully hammer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import SESSION_ACCOUNT, get_current_account, get_optional_account
from app.core.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordError,
    hash_password,
    verify_password,
)
from app.core.security import rate_limit_login
from app.db.session import get_db
from app.models import Account, Role
from app.services import accounts as account_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_LIMIT = [Depends(rate_limit_login)]


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class StudentRegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    full_name: str = Field(min_length=1, max_length=200)


class HRRegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    full_name: str = Field(min_length=1, max_length=200)
    organization_name: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    is_verified: bool


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    full_name: str
    role: Role
    organization: OrganizationOut | None = None


class SessionOut(BaseModel):
    authenticated: bool
    account: AccountOut | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _to_account_out(account: Account) -> AccountOut:
    organization = None
    if account.hr_membership is not None:
        organization = OrganizationOut.model_validate(
            account.hr_membership.organization
        )
    return AccountOut(
        id=account.id,
        email=account.email,
        full_name=account.full_name,
        role=account.role,
        organization=organization,
    )


def _sign_in(request: Request, account: Account) -> SessionOut:
    """Establish the session.

    Cleared before writing so no state from a previous session survives, which
    is also the session-fixation defence — Starlette re-signs the cookie
    whenever the session dict changes.
    """
    request.session.clear()
    request.session[SESSION_ACCOUNT] = account.id
    return SessionOut(authenticated=True, account=_to_account_out(account))


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/session", response_model=SessionOut)
def read_session(
    account: Account | None = Depends(get_optional_account),
) -> SessionOut:
    """Who is signed in, if anyone.

    Unauthenticated by design — the frontend calls it on load to choose between
    the sign-in screen and the app, and it reveals nothing to a stranger.
    """
    if account is None:
        return SessionOut(authenticated=False)
    return SessionOut(authenticated=True, account=_to_account_out(account))


@router.post(
    "/register/student",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=LOGIN_LIMIT,
)
def register_student(
    payload: StudentRegisterIn, request: Request, db: Session = Depends(get_db)
) -> SessionOut:
    """Create a student account and sign in."""
    try:
        account = account_service.register_student(
            db,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
        )
    except (account_service.RegistrationError, PasswordError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    return _sign_in(request, account)


@router.post(
    "/register/hr",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=LOGIN_LIMIT,
)
def register_hr(
    payload: HRRegisterIn, request: Request, db: Session = Depends(get_db)
) -> SessionOut:
    """Create a recruiter account and attach it to an organization.

    Registration succeeds immediately; posting roles does not. The organization
    starts unverified, and `require_verified_organization` is what gates the
    actions that could harm students.
    """
    try:
        account = account_service.register_hr(
            db,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            organization_name=payload.organization_name,
            title=payload.title,
        )
    except (account_service.RegistrationError, PasswordError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    return _sign_in(request, account)


@router.post("/login", response_model=SessionOut, dependencies=LOGIN_LIMIT)
def login(
    payload: LoginIn, request: Request, db: Session = Depends(get_db)
) -> SessionOut:
    """Sign in.

    One message for every failure — wrong password, no such account, suspended.
    Distinguishing them tells whoever is guessing which addresses are
    registered, which is the first half of a credential-stuffing attack.
    """
    account = account_service.authenticate(
        db, email=payload.email, password=payload.password
    )
    if account is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Incorrect email or password."
        )
    return _sign_in(request, account)


@router.post("/logout", response_model=SessionOut)
def logout(request: Request) -> SessionOut:
    request.session.clear()
    return SessionOut(authenticated=False)


@router.post("/password", response_model=SessionOut)
def change_password(
    payload: PasswordChangeIn,
    request: Request,
    account: Account = Depends(get_current_account),
    db: Session = Depends(get_db),
) -> SessionOut:
    """Change the signed-in account's password.

    The current password is required even though the caller is already
    authenticated — otherwise an unattended logged-in browser is enough for
    someone to lock the owner out of their own account.
    """
    if not verify_password(payload.current_password, account.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Current password is incorrect."
        )

    try:
        account.password_hash = hash_password(payload.new_password)
    except PasswordError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    db.commit()
    # Re-establish the session so the cookie is re-signed after the change.
    return _sign_in(request, account)
