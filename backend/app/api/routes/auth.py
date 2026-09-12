"""`/api/auth/*` — the password gate.

Deliberately outside the `require_auth` dependency, for the obvious reason, but
still rate-limited: this is the one endpoint an attacker can usefully hammer.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import (
    SESSION_KEY,
    rate_limit_login,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str = Field(min_length=1)


class AuthStatusOut(BaseModel):
    #: False when no password is configured, i.e. the gate is off entirely.
    auth_required: bool
    authenticated: bool


@router.get("/status", response_model=AuthStatusOut)
def auth_status(request: Request) -> AuthStatusOut:
    """Whether a gate exists and whether this caller is through it.

    The frontend calls this on load to decide between the login screen and the
    app. Unauthenticated by design — it reveals only that a password exists.
    """
    return AuthStatusOut(
        auth_required=settings.auth_enabled,
        authenticated=not settings.auth_enabled
        or bool(request.session.get(SESSION_KEY)),
    )


@router.post(
    "/login",
    response_model=AuthStatusOut,
    dependencies=[Depends(rate_limit_login)],
)
def login(payload: LoginIn, request: Request) -> AuthStatusOut:
    """Exchange the password for a session cookie."""
    if not settings.auth_enabled:
        # Nothing to sign in to. Reported plainly rather than pretending to
        # succeed, so a misconfigured deployment is visible.
        return AuthStatusOut(auth_required=False, authenticated=True)

    if not verify_password(payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password.",
        )

    # Starlette regenerates the signed cookie whenever the session dict is
    # written, so this is also the session-fixation defence.
    request.session[SESSION_KEY] = True
    return AuthStatusOut(auth_required=True, authenticated=True)


@router.post("/logout", response_model=AuthStatusOut)
def logout(request: Request) -> AuthStatusOut:
    """Clear the session."""
    request.session.clear()
    return AuthStatusOut(
        auth_required=settings.auth_enabled,
        authenticated=not settings.auth_enabled,
    )
