"""Shared fixtures.

Every test gets its own database file and its own rate-limit budget, so nothing
leaks between them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.db.session import Base, get_db
from app.main import app

STUDENT_PASSWORD = "student-password-123"
HR_PASSWORD = "recruiter-password-123"


@pytest.fixture(autouse=True)
def reset_limiters():
    """A fresh budget per test.

    Without this, a test that exhausts the sign-in limiter silently fails every
    later test that tries to authenticate — and the failure looks like a bug in
    whatever ran last.
    """
    limiters = (security.ai_limiter, security.api_limiter, security.login_limiter)
    for limiter in limiters:
        limiter.reset()
    yield
    for limiter in limiters:
        limiter.reset()


@pytest.fixture
def db_session(tmp_path):
    """A session factory over an empty database with the full schema."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def api(db_session):
    """A client bound to this test's database, signed in as nobody.

    Named `api` rather than `client` so a test module can override `client`
    with an authenticated one without the signed-in fixtures below recursing
    into their own override.
    """

    def override():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client(api):
    """An unauthenticated client."""
    return api


def register_student(
    client: TestClient,
    email: str = "student@example.com",
    password: str = STUDENT_PASSWORD,
    full_name: str = "Test Student",
):
    response = client.post(
        "/api/auth/register/student",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def register_hr(
    client: TestClient,
    email: str = "recruiter@acme.com",
    password: str = HR_PASSWORD,
    full_name: str = "Test Recruiter",
    organization_name: str = "Acme",
):
    response = client.post(
        "/api/auth/register/hr",
        json={
            "email": email,
            "password": password,
            "full_name": full_name,
            "organization_name": organization_name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def student(api):
    """A client signed in as a student. Registration signs you in."""
    register_student(api)
    return api


@pytest.fixture
def recruiter(api):
    """A client signed in as a recruiter."""
    register_hr(api)
    return api
