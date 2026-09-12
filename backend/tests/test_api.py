"""End-to-end API tests against a real (temporary) database.

No API key needed: these drive `/api/extract/confirm`, which takes an already
validated preview, so the two agent calls are out of the path. Everything after
ingestion — persistence, scoring, the board, ROI, the funnel — is covered.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import CURRENT_PROFILE_ID
from app.db.session import Base, get_db
from app.main import app


@pytest.fixture
def client(tmp_path):
    """A client bound to a fresh SQLite file per test."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_profile(client, skills=None, **prefs):
    payload = {
        "full_name": "Test Candidate",
        "years_experience": 4.0,
        "career_goal": "Senior backend role",
        "skills": skills
        if skills is not None
        else [{"name": "python", "proficiency": "proficient", "years": 4.0}],
        "preferences": {
            "target_roles": prefs.get("target_roles", ["backend engineer"]),
            "locations": prefs.get("locations", []),
            "remote_ok": prefs.get("remote_ok", True),
            "min_salary": prefs.get("min_salary"),
            "seniority": prefs.get("seniority"),
            "industries": prefs.get("industries", []),
            "company_sizes": [],
            "currency": "USD",
        },
    }
    response = client.put("/api/profile", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def preview(title="Backend Engineer", requirements=None, **overrides):
    """A synthetic extraction preview, as the confirm endpoint expects."""
    body = {
        "title": title,
        "company": "Acme",
        "location": "Remote",
        "remote": True,
        "seniority": "senior",
        "salary_min": 120_000,
        "salary_max": 160_000,
        "currency": "USD",
        "industry": "software",
        "company_size": "medium",
        "description": "Build backend services.",
        "requirements": requirements
        if requirements is not None
        else [
            {
                "name": "python",
                "necessity": "required",
                "min_years": 3.0,
                "evidence": "3+ years of Python",
            },
            {
                "name": "kubernetes",
                "necessity": "required",
                "min_years": 0.0,
                "evidence": "experience with Kubernetes",
            },
        ],
        "source_kind": "text",
        "source_url": None,
        "raw_text": "We want a backend engineer with 3+ years of Python and Kubernetes.",
        "confidence": 0.95,
        "unverified_fields": [],
        "contradicted_fields": [],
        "validation_notes": "All fields grounded.",
        "needs_confirmation": False,
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- #
# Health and profile
# --------------------------------------------------------------------------- #


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_reading_the_profile_before_saving_one_works(client):
    """It used to 404 here, which made every route on a fresh instance fail —
    including the résumé upload that would have created the profile. The
    profile is a singleton, so it is created on first touch instead.
    See tests/test_fresh_instance.py."""
    response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json()["full_name"] == ""


def test_profile_round_trip(client):
    created = make_profile(client)
    assert created["id"] == CURRENT_PROFILE_ID
    assert created["full_name"] == "Test Candidate"

    fetched = client.get("/api/profile").json()
    assert [s["name"] for s in fetched["skills"]] == ["python"]
    assert fetched["preferences"]["target_roles"] == ["backend engineer"]


def test_profile_put_replaces_skills_rather_than_merging(client):
    make_profile(client, skills=[{"name": "python", "proficiency": "expert", "years": 5}])
    make_profile(client, skills=[{"name": "go", "proficiency": "working", "years": 1}])
    assert [s["name"] for s in client.get("/api/profile").json()["skills"]] == ["go"]


def test_skill_names_are_canonicalised_on_save(client):
    make_profile(client, skills=[{"name": "  Postgres ", "proficiency": "working", "years": 2}])
    assert client.get("/api/profile").json()["skills"][0]["name"] == "postgresql"


# --------------------------------------------------------------------------- #
# Ingestion and the board
# --------------------------------------------------------------------------- #


def test_confirm_creates_a_job_and_an_application(client):
    make_profile(client)
    response = client.post("/api/extract/confirm", json=preview())
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["title"] == "Backend Engineer"
    assert {r["name"] for r in job["requirements"]} == {"python", "kubernetes"}

    board = client.get("/api/opportunities").json()
    assert len(board) == 1
    assert board[0]["status"] == "saved"
    assert board[0]["application_id"] is not None


def test_board_reports_a_score_with_a_derivation(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())

    detail = client.get("/api/opportunities/1").json()
    alignment = detail["alignment"]

    # One of two required skills held -> 50% requirements fit.
    assert alignment["requirements_fit"] == 50.0
    assert alignment["total"] == pytest.approx(
        0.7 * alignment["requirements_fit"] + 0.3 * alignment["preference_fit"],
        abs=0.05,
    )
    assert {r["name"]: r["coverage"] for r in alignment["requirements"]} == {
        "python": "have",
        "kubernetes": "missing",
    }
    assert "Total" in alignment["explanation"]


def test_board_omits_the_breakdown_unless_asked(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())

    lean = client.get("/api/opportunities").json()[0]
    assert lean["alignment"]["requirements"] == []
    assert lean["alignment"]["total"] > 0

    full = client.get("/api/opportunities?include_breakdown=true").json()[0]
    assert len(full["alignment"]["requirements"]) == 2


def test_editing_the_profile_changes_the_score(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())
    before = client.get("/api/opportunities/1").json()["alignment"]["total"]

    make_profile(
        client,
        skills=[
            {"name": "python", "proficiency": "proficient", "years": 4},
            {"name": "kubernetes", "proficiency": "working", "years": 1},
        ],
    )
    after = client.get("/api/opportunities/1").json()["alignment"]["total"]
    assert after > before


def test_board_filters_by_status_and_score(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview(title="Match"))
    client.post(
        "/api/extract/confirm",
        json=preview(
            title="Mismatch",
            requirements=[
                {"name": "cobol", "necessity": "required", "min_years": 0.0, "evidence": "COBOL"}
            ],
        ),
    )

    assert len(client.get("/api/opportunities?status=saved").json()) == 2
    assert len(client.get("/api/opportunities?status=applied").json()) == 0

    high = client.get("/api/opportunities?min_score=50").json()
    assert [o["job"]["title"] for o in high] == ["Match"]


# --------------------------------------------------------------------------- #
# Pipeline transitions
# --------------------------------------------------------------------------- #


def test_status_change_stamps_applied_at_and_records_history(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())

    response = client.patch(
        "/api/opportunities/1/application", json={"status": "applied"}
    )
    assert response.status_code == 200
    assert response.json()["applied_at"] is not None

    funnel = client.get("/api/analytics/funnel").json()
    reached = {s["status"]: s["reached"] for s in funnel["stages"]}
    assert reached["saved"] == 1
    assert reached["applied"] == 1


def test_applied_at_is_not_moved_by_later_transitions(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())

    first = client.patch(
        "/api/opportunities/1/application", json={"status": "applied"}
    ).json()["applied_at"]
    later = client.patch(
        "/api/opportunities/1/application", json={"status": "screening"}
    ).json()["applied_at"]
    assert first == later


def test_funnel_rates_use_submitted_as_the_denominator(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview(title="A"))
    client.post("/api/extract/confirm", json=preview(title="B"))

    client.patch("/api/opportunities/1/application", json={"status": "applied"})
    client.patch("/api/opportunities/1/application", json={"status": "screening"})
    # Job 2 stays saved, so it must not count against the response rate.

    funnel = client.get("/api/analytics/funnel").json()
    assert funnel["response_rate"] == 1.0
    assert funnel["total"] == 2


def test_deleting_a_job_removes_it_from_the_board(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())
    assert client.delete("/api/opportunities/1").status_code == 204
    assert client.get("/api/opportunities").json() == []
    assert client.get("/api/opportunities/1").status_code == 404


# --------------------------------------------------------------------------- #
# Skill ROI and what-if
# --------------------------------------------------------------------------- #


def test_skill_roi_ranks_the_gap(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())

    rois = client.get("/api/skill-roi").json()
    assert [r["skill"] for r in rois] == ["kubernetes"]
    assert rois[0]["demand"] == 1
    assert rois[0]["mean_gain"] > 0


def test_skill_roi_reports_unlocks(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())

    roi = client.get("/api/skill-roi").json()[0]
    # Closing the only gap takes requirements to 100, crossing the threshold.
    assert roi["unlock_count"] == 1


def test_what_if_adding_a_skill_lifts_the_board(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())

    result = client.post(
        "/api/simulation/what-if", json={"add_skills": ["kubernetes"]}
    ).json()

    assert result["mean_change"] > 0
    assert result["in_reach_after"] > result["in_reach_before"]
    assert result["deltas"][0]["newly_in_reach"] is True


def test_what_if_persists_nothing(client):
    make_profile(client)
    client.post("/api/extract/confirm", json=preview())
    before = client.get("/api/opportunities/1").json()["alignment"]["total"]

    client.post("/api/simulation/what-if", json={"add_skills": ["kubernetes"]})

    assert client.get("/api/opportunities/1").json()["alignment"]["total"] == before
    assert [s["name"] for s in client.get("/api/profile").json()["skills"]] == ["python"]


def test_what_if_can_lower_a_salary_floor(client):
    make_profile(client, min_salary=200_000)
    client.post("/api/extract/confirm", json=preview())
    before = client.get("/api/opportunities/1").json()["alignment"]["total"]

    result = client.post(
        "/api/simulation/what-if", json={"min_salary": 100_000}
    ).json()
    assert result["mean_after"] > before


# --------------------------------------------------------------------------- #
# Empty-state behaviour
# --------------------------------------------------------------------------- #


def test_endpoints_are_safe_with_an_empty_board(client):
    make_profile(client)
    assert client.get("/api/opportunities").json() == []
    assert client.get("/api/skill-roi").json() == []
    assert client.get("/api/analytics/funnel").json()["total"] == 0
    assert client.post("/api/simulation/what-if", json={}).json()["deltas"] == []


def test_roadmap_refuses_with_nothing_to_plan_around(client):
    make_profile(client)
    response = client.post("/api/learning/roadmap", json={})
    assert response.status_code == 409
    assert "add some jobs" in response.json()["detail"]
