"""A brand-new instance has to be usable.

Regression: every route depended on a profile row existing, and returned 404
with "create one at PUT /api/profile" when it didn't. That made a fresh deploy
completely unusable — including the résumé upload, the one action that would
have created the profile. A new user was told to go and do the thing they were
already trying to do.

Caught only after deploying, because local development always had a profile
from the seed script.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import CURRENT_PROFILE_ID
from app.db.session import Base, get_db
from app.main import app
from app.models import Profile


@pytest.fixture
def fresh(tmp_path):
    """A client against a database with the schema but no rows at all."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fresh.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app), Session
    app.dependency_overrides.clear()


def test_no_profile_row_exists_to_begin_with(fresh):
    _, Session = fresh
    db = Session()
    assert db.execute(select(Profile)).scalars().all() == []
    db.close()


@pytest.mark.parametrize(
    "path",
    [
        "/api/profile",
        "/api/opportunities",
        "/api/skill-roi",
        "/api/analytics/funnel",
        "/api/resume",
        "/api/interview",
        "/api/learning",
    ],
)
def test_every_read_works_on_a_fresh_instance(fresh, path):
    client, _ = fresh
    assert client.get(path).status_code == 200


def test_the_profile_is_created_on_first_touch(fresh):
    client, Session = fresh
    client.get("/api/profile")

    db = Session()
    profile = db.execute(select(Profile)).scalar_one()
    assert profile.id == CURRENT_PROFILE_ID
    db.close()


def test_only_one_profile_is_ever_created(fresh):
    """Repeated requests must not pile up rows."""
    client, Session = fresh
    for _ in range(5):
        client.get("/api/profile")
        client.get("/api/opportunities")

    db = Session()
    assert len(db.execute(select(Profile)).scalars().all()) == 1
    db.close()


def test_resume_upload_works_before_any_profile_is_saved(fresh):
    """The bug in one line: this is the first thing a new user does."""
    client, _ = fresh
    files = {"file": ("cv.txt", io.BytesIO(b"Experienced engineer. " * 40), "text/plain")}

    response = client.post("/api/resume?update_profile=false", files=files)

    # 201 on success, or 502 if no model credentials — either proves it got
    # past the profile dependency, which is what this is about.
    assert response.status_code != 404
    assert response.status_code in (201, 502)


def test_the_empty_profile_is_blank_not_fabricated(fresh):
    """Created to exist, not to invent a name."""
    client, _ = fresh
    profile = client.get("/api/profile").json()

    assert profile["full_name"] == ""
    assert profile["skills"] == []
    assert profile["headline"] is None
    assert profile["years_experience"] == 0


def test_saving_a_profile_updates_rather_than_duplicates(fresh):
    """The auto-created row must be the one PUT writes to."""
    client, Session = fresh
    client.get("/api/profile")  # forces creation

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

    db = Session()
    assert len(db.execute(select(Profile)).scalars().all()) == 1
    db.close()
