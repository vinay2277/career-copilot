"""A newly registered student has to be able to use everything immediately.

Regression, from before accounts existed: every route depended on a profile row
being there, and returned 404 when it wasn't. A fresh deployment was therefore
unusable — including the résumé upload, the one action that would have created
the profile. A new user was told to go and do the thing they were already
trying to do.

Registration now creates the profile, so this file guards the property rather
than the old mechanism: sign up, and nothing 404s.
"""

from __future__ import annotations

import io

import pytest
from sqlalchemy import select

from app.models import Account, Profile
from tests.conftest import register_student


@pytest.fixture
def fresh(api, db_session):
    """A just-registered student against an otherwise empty database."""
    register_student(api)
    return api, db_session


def test_registration_creates_exactly_one_profile(fresh):
    _, db_session = fresh
    with db_session() as db:
        accounts = db.execute(select(Account)).scalars().all()
        profiles = db.execute(select(Profile)).scalars().all()

    assert len(accounts) == 1
    assert len(profiles) == 1
    assert profiles[0].account_id == accounts[0].id


@pytest.mark.parametrize(
    "path",
    [
        "/api/profile",
        "/api/board",
        "/api/skill-roi",
        "/api/analytics/funnel",
        "/api/resume",
        "/api/interview",
        "/api/learning",
    ],
)
def test_every_read_works_immediately_after_signing_up(fresh, path):
    client, _ = fresh
    assert client.get(path).status_code == 200


def test_the_board_starts_empty_rather_than_erroring(fresh):
    client, _ = fresh
    assert client.get("/api/board").json() == {"from_employers": [], "sourced": []}
    assert client.get("/api/skill-roi").json() == []
    assert client.get("/api/analytics/funnel").json()["total"] == 0


def test_resume_upload_works_with_nothing_saved_yet(fresh):
    """The bug in one line: this is the first thing a new user does."""
    client, _ = fresh
    files = {
        "file": ("cv.txt", io.BytesIO(b"Experienced engineer. " * 40), "text/plain")
    }

    response = client.post("/api/resume?update_profile=false", files=files)

    # 201 on success, or 502 with no model credentials — either proves it got
    # past the profile dependency, which is what this is about.
    assert response.status_code != 404
    assert response.status_code in (201, 502)


def test_the_profile_is_seeded_from_the_signup_form(fresh):
    """Created to exist and carry what registration knew — not to invent."""
    client, _ = fresh
    profile = client.get("/api/profile").json()

    assert profile["full_name"] == "Test Student"
    assert profile["email"] == "student@example.com"
    assert profile["skills"] == []
    assert profile["headline"] is None
    assert profile["years_experience"] == 0
    assert profile["visible_to_recruiters"] is False


def test_saving_updates_rather_than_duplicates(fresh):
    """The profile registration made must be the one PUT writes to."""
    client, db_session = fresh

    response = client.put(
        "/api/profile",
        json={
            "full_name": "Vinay",
            "years_experience": 4,
            "skills": [{"name": "python", "proficiency": "expert", "years": 4}],
            "preferences": None,
        },
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Vinay"

    with db_session() as db:
        assert len(db.execute(select(Profile)).scalars().all()) == 1
