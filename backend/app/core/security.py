"""Password gate and rate-limit dependencies.

One shared password, held in the environment, exchanged for a signed session
cookie. Deliberately not a user system: this is one person's tool, and the gate
exists to stop strangers reading the résumé and spending the API key, not to
model identity.

Leaving `APP_PASSWORD` empty disables the whole thing, which keeps local
development frictionless. Anything reachable from outside the machine must set
it.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.ratelimit import SlidingWindowLimiter

logger = logging.getLogger(__name__)

#: Marks a session as having passed the gate.
SESSION_KEY = "authenticated"


# --------------------------------------------------------------------------- #
# Limiters — module-level so the counters survive between requests
# --------------------------------------------------------------------------- #

ai_limiter = SlidingWindowLimiter(settings.rate_limit_ai_per_hour, 3600)
api_limiter = SlidingWindowLimiter(settings.rate_limit_api_per_minute, 60)
login_limiter = SlidingWindowLimiter(settings.rate_limit_login_per_hour, 3600)


def client_key(request: Request) -> str:
    """Identify the caller for rate-limiting purposes.

    Behind a reverse proxy the socket address is the proxy, so the leftmost
    X-Forwarded-For entry is used when present — that is the hop the proxy
    itself recorded. It is client-controllable and therefore spoofable, which
    is acceptable here: the limiter protects a budget, it is not an access
    control, and the password gate is what actually guards the data.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce(limiter: SlidingWindowLimiter, request: Request, what: str) -> None:
    decision = limiter.check(client_key(request))
    if decision.allowed:
        return

    logger.warning(
        "rate limit hit: %s by %s (limit %d)", what, client_key(request), decision.limit
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"Too many {what} requests — the limit is {decision.limit}. "
            f"Try again in {decision.retry_after} seconds."
        ),
        headers={"Retry-After": str(decision.retry_after)},
    )


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #


def require_auth(request: Request) -> None:
    """Reject anything without a valid session, when the gate is on.

    Applied to every API router. With no password configured this is a no-op,
    so a local checkout behaves exactly as before.
    """
    if not settings.auth_enabled:
        return

    if not request.session.get(SESSION_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in.",
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
    """Throttle sign-in attempts.

    Guessing one shared password is the obvious attack on this design, and it
    is the only one a rate limit meaningfully prevents.
    """
    _enforce(login_limiter, request, "sign-in")


#: Convenience bundles for `APIRouter(dependencies=...)`.
PROTECTED = [Depends(require_auth), Depends(rate_limit_api)]
PROTECTED_AI = [Depends(require_auth), Depends(rate_limit_api), Depends(rate_limit_ai)]


# --------------------------------------------------------------------------- #
# Password check
# --------------------------------------------------------------------------- #


def verify_password(candidate: str) -> bool:
    """Constant-time comparison against the configured password.

    `compare_digest` rather than `==` so the time taken doesn't leak how much
    of the password was correct.
    """
    if not settings.auth_enabled:
        return True
    return secrets.compare_digest(candidate.encode(), settings.app_password.encode())


def startup_check() -> None:
    """Warn loudly about a configuration that is unsafe to expose.

    Not fatal: refusing to boot would break every local checkout, which is the
    overwhelmingly common case. The log line is aimed at whoever is looking at
    a deployment that is already running.
    """
    if not settings.auth_enabled:
        logger.warning(
            "APP_PASSWORD is not set — the API is open to anyone who can reach "
            "it. Fine on localhost; set it before exposing this."
        )
        return

    if not settings.secret_key:
        logger.warning(
            "SECRET_KEY is not set, so a random one is generated per process. "
            "Sessions will not survive a restart, and will not be shared "
            "between workers. Set it in .env."
        )
    if not settings.cookie_secure:
        logger.warning(
            "COOKIE_SECURE is false — the session cookie will travel over "
            "plain HTTP. Set it true when serving over HTTPS."
        )
