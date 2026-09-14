"""Rate limiting.

Authentication moved to real accounts — see `app/api/deps.py` for the
authorization dependencies and `app/services/accounts.py` for sign-in. What
stays here is throttling, which is independent of who the caller is and has to
work before they are identified.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.ratelimit import SlidingWindowLimiter

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Limiters — module-level so the counters survive between requests
# --------------------------------------------------------------------------- #

ai_limiter = SlidingWindowLimiter(settings.rate_limit_ai_per_hour, 3600)
api_limiter = SlidingWindowLimiter(settings.rate_limit_api_per_minute, 60)
login_limiter = SlidingWindowLimiter(settings.rate_limit_login_per_hour, 3600)


def ip_key(request: Request) -> str:
    """The caller's network address.

    Behind a reverse proxy the socket address is the proxy, so the leftmost
    X-Forwarded-For entry is used when present. It is client-controllable and
    therefore spoofable, which is acceptable here: the limiter protects a
    budget, it is not an access control, and authentication is what guards the
    data.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def client_key(request: Request) -> str:
    """Identify the caller for throughput limits on authenticated routes.

    Keyed by account when there is one, so a shared office NAT doesn't put
    every recruiter on a single budget.

    **Not for sign-in or registration.** Those must key by address — see
    `ip_key`. Registration signs the caller in, so an account-keyed budget
    would hand every newly created account a fresh allowance and leave
    registration itself effectively unlimited.
    """
    account_id = request.session.get("account_id")
    if account_id is not None:
        return f"account:{account_id}"
    return ip_key(request)


def _enforce(
    limiter: SlidingWindowLimiter,
    request: Request,
    what: str,
    key_fn=client_key,
) -> None:
    key = key_fn(request)
    decision = limiter.check(key)
    if decision.allowed:
        return

    logger.warning("rate limit hit: %s by %s (limit %d)", what, key, decision.limit)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"Too many {what} requests — the limit is {decision.limit}. "
            f"Try again in {decision.retry_after} seconds."
        ),
        headers={"Retry-After": str(decision.retry_after)},
    )


def rate_limit_api(request: Request) -> None:
    """General throughput cap, applied to every API route."""
    _enforce(api_limiter, request, "API")


def rate_limit_ai(request: Request) -> None:
    """Tight cap for routes that call a model.

    These cost real money per call, so they get a separate and much smaller
    budget than ordinary reads. Applied *in addition* to the general limit.
    """
    _enforce(ai_limiter, request, "AI")


def rate_limit_login(request: Request) -> None:
    """Throttle sign-in and registration, keyed by address.

    Credential stuffing is the attack this prevents, and registration is
    included because an unthrottled sign-up endpoint is how a platform acquires
    ten thousand fake students overnight.

    Keyed by `ip_key` rather than `client_key`, deliberately: registration
    signs the caller in, so an account-keyed budget would reset on every new
    account and cap nothing at all.
    """
    _enforce(login_limiter, request, "sign-in", key_fn=ip_key)


def startup_check() -> None:
    """Warn about configuration that is unsafe to expose.

    Not fatal: refusing to boot would break every local checkout, which is the
    common case. These lines are aimed at whoever is looking at a deployment
    that is already running.
    """
    if not settings.secret_key:
        logger.warning(
            "SECRET_KEY is not set, so a random one is generated per process. "
            "Everyone is signed out on every restart, and workers will not "
            "share sessions. Set it in .env."
        )
    if not settings.cookie_secure:
        logger.warning(
            "COOKIE_SECURE is false — the session cookie will travel over "
            "plain HTTP. Set it true when serving over HTTPS."
        )
    if not settings.require_org_verification:
        logger.warning(
            "REQUIRE_ORG_VERIFICATION is false — any recruiter who registers "
            "can post roles and view student contact details without review."
        )
