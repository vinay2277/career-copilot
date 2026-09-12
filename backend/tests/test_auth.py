"""Tests for the password gate.

The thing worth proving is that the gate actually blocks — a login screen that
sits in front of an API anyone can still call directly is theatre. So these go
straight at the API rather than through any UI flow.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def clear_limiters():
    """Each test starts with a fresh budget."""
    for limiter in (security.ai_limiter, security.api_limiter, security.login_limiter):
        limiter.reset()
    yield
    for limiter in (security.ai_limiter, security.api_limiter, security.login_limiter):
        limiter.reset()


@pytest.fixture
def db_override(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # A profile has to exist, or every route 404s at the profile dependency and
    # a "did the gate let me through?" assertion can't tell 404-because-blocked
    # from 404-because-empty.
    from app.api.deps import CURRENT_PROFILE_ID
    from app.models import Profile

    seed = Session()
    seed.add(Profile(id=CURRENT_PROFILE_ID, full_name="Test"))
    seed.commit()
    seed.close()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def locked(monkeypatch, db_override):
    """A client against an app with the gate switched on."""
    monkeypatch.setattr(settings, "app_password", PASSWORD)
    return TestClient(app)


@pytest.fixture
def open_app(monkeypatch, db_override):
    """A client against an app with no password configured."""
    monkeypatch.setattr(settings, "app_password", "")
    return TestClient(app)


# --------------------------------------------------------------------------- #
# The gate blocks
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/profile"),
        ("get", "/api/opportunities"),
        ("get", "/api/skill-roi"),
        ("get", "/api/analytics/funnel"),
        ("get", "/api/resume"),
        ("post", "/api/extract/text"),
        ("post", "/api/simulation/what-if"),
    ],
)
def test_api_is_closed_without_a_session(locked, method, path):
    # `json=` only on POST — TestClient.get() does not accept a body.
    response = (
        locked.get(path) if method == "get" else locked.post(path, json={})
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Not signed in."


def test_the_gate_blocks_before_the_handler_runs(locked):
    """401, not 404 — the request must not reach the profile lookup."""
    assert locked.get("/api/profile").status_code == 401


def test_health_stays_open(locked):
    """Platforms probe this before anything is signed in."""
    assert locked.get("/health").status_code == 200


def test_auth_status_stays_open(locked):
    """The frontend needs this to know whether to show a login screen."""
    response = locked.get("/api/auth/status")
    assert response.status_code == 200
    assert response.json() == {"auth_required": True, "authenticated": False}


# --------------------------------------------------------------------------- #
# Signing in
# --------------------------------------------------------------------------- #


def test_the_correct_password_opens_the_api(locked):
    assert locked.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
    # The cookie is held by the client, so the next call carries it.
    assert locked.get("/api/opportunities").status_code == 200


def test_the_wrong_password_is_rejected(locked):
    response = locked.post("/api/auth/login", json={"password": "guess"})
    assert response.status_code == 401
    assert locked.get("/api/opportunities").status_code == 401


def test_an_empty_password_is_rejected_by_validation(locked):
    assert locked.post("/api/auth/login", json={"password": ""}).status_code == 422


def test_logout_closes_the_api_again(locked):
    locked.post("/api/auth/login", json={"password": PASSWORD})
    assert locked.get("/api/opportunities").status_code == 200

    locked.post("/api/auth/logout")
    assert locked.get("/api/opportunities").status_code == 401


def test_status_reflects_being_signed_in(locked):
    locked.post("/api/auth/login", json={"password": PASSWORD})
    assert locked.get("/api/auth/status").json() == {
        "auth_required": True,
        "authenticated": True,
    }


def test_the_session_cookie_is_httponly(locked):
    """Script-readable would put the session one XSS away from theft."""
    response = locked.post("/api/auth/login", json={"password": PASSWORD})
    cookie = response.headers.get("set-cookie", "")
    assert "career_copilot_session" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()


def test_the_password_is_not_echoed_back(locked):
    """Not in the success body, not in the rejection."""
    ok = locked.post("/api/auth/login", json={"password": PASSWORD})
    assert PASSWORD not in ok.text

    bad = locked.post("/api/auth/login", json={"password": "guess"})
    assert PASSWORD not in bad.text


# --------------------------------------------------------------------------- #
# Gate disabled
# --------------------------------------------------------------------------- #


def test_no_password_means_no_gate(open_app):
    """Local development must not need a login."""
    assert open_app.get("/api/opportunities").status_code == 200


def test_status_reports_the_gate_is_off(open_app):
    assert open_app.get("/api/auth/status").json() == {
        "auth_required": False,
        "authenticated": True,
    }


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #


def test_sign_in_attempts_are_throttled(locked, monkeypatch):
    """Guessing one shared password is the attack this design invites."""
    monkeypatch.setattr(
        security, "login_limiter", security.SlidingWindowLimiter(3, 3600)
    )

    for _ in range(3):
        assert locked.post("/api/auth/login", json={"password": "no"}).status_code == 401

    throttled = locked.post("/api/auth/login", json={"password": "no"})
    assert throttled.status_code == 429
    assert "Retry-After" in throttled.headers


def test_throttling_applies_to_the_correct_password_too(locked, monkeypatch):
    """Otherwise a valid guess slips through after the limit is reached."""
    monkeypatch.setattr(
        security, "login_limiter", security.SlidingWindowLimiter(2, 3600)
    )
    locked.post("/api/auth/login", json={"password": "no"})
    locked.post("/api/auth/login", json={"password": "no"})

    assert locked.post("/api/auth/login", json={"password": PASSWORD}).status_code == 429


def test_ai_endpoints_have_their_own_budget(locked, monkeypatch):
    """These spend money per call, so they cap well below general traffic."""
    monkeypatch.setattr(security, "ai_limiter", security.SlidingWindowLimiter(1, 3600))
    locked.post("/api/auth/login", json={"password": PASSWORD})

    # One call is permitted; it fails at the model for lack of a key, not here.
    first = locked.post("/api/extract/text", json={"text": "x" * 200})
    assert first.status_code != 429

    second = locked.post("/api/extract/text", json={"text": "x" * 200})
    assert second.status_code == 429
    assert "AI" in second.json()["detail"]


def test_cheap_reads_are_not_charged_to_the_ai_budget(locked, monkeypatch):
    """Exhausting the AI budget must not lock you out of your own board."""
    monkeypatch.setattr(security, "ai_limiter", security.SlidingWindowLimiter(1, 3600))
    locked.post("/api/auth/login", json={"password": PASSWORD})

    locked.post("/api/extract/text", json={"text": "x" * 200})  # spends the budget

    assert locked.get("/api/opportunities").status_code == 200
    assert locked.get("/api/analytics/funnel").status_code == 200


def test_rate_limit_response_carries_retry_after(locked, monkeypatch):
    monkeypatch.setattr(security, "api_limiter", security.SlidingWindowLimiter(1, 60))
    locked.post("/api/auth/login", json={"password": PASSWORD})

    locked.get("/api/opportunities")
    throttled = locked.get("/api/opportunities")
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) > 0


# --------------------------------------------------------------------------- #
# Password comparison
# --------------------------------------------------------------------------- #


def test_verify_password_is_exact(monkeypatch):
    monkeypatch.setattr(settings, "app_password", PASSWORD)
    assert security.verify_password(PASSWORD)
    assert not security.verify_password(PASSWORD.upper())
    assert not security.verify_password(PASSWORD + " ")
    assert not security.verify_password(PASSWORD[:-1])
    assert not security.verify_password("")


def test_verify_password_passes_when_the_gate_is_off(monkeypatch):
    monkeypatch.setattr(settings, "app_password", "")
    assert security.verify_password("anything")
