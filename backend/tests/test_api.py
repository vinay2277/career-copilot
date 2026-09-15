"""End-to-end API tests against a real (temporary) database.

No API key needed. Roles are seeded by a recruiter publishing them through
`/api/employer/postings`, which takes an already-structured payload, so the two
extraction agents stay out of the path. Everything after ingestion —
persistence, scoring, the board, ROI, the what-if simulator, the funnel — is
covered.

These used to seed roles through the student's own job tracker. That surface is
gone: pasting in a role found elsewhere is a recruiter's job now, and the
student's world is the shared board. The analytics engines never knew which
table a role came from, so what changed here is how roles get created, not what
is asserted about them.
"""

from __future__ import annotations

import pytest

from tests.conftest import HR_PASSWORD, register_hr, register_student
from tests.test_postings import verify_organization


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


def role(title="Backend Engineer", requirements=None, **overrides):
    """A posting payload, as the employer endpoint expects."""
    body = {
        "title": title,
        "description": "Build and run backend services.",
        "location": "Berlin",
        "remote": True,
        "seniority": "senior",
        "salary_min": 90_000,
        "salary_max": 130_000,
        "currency": "USD",
        "industry": "fintech",
        "company_size": "medium",
        "requirements": requirements
        if requirements is not None
        else [
            {"name": "python", "necessity": "required", "min_years": 3},
            {"name": "kubernetes", "necessity": "required", "min_years": 2},
        ],
        "raw_text": f"{title}. We need Python and Kubernetes experience.",
        # Off, so seeding a board never depends on anything model-shaped.
        "interview_required": False,
    }
    body.update(overrides)
    return body


@pytest.fixture
def recruiter_client(api, db_session):
    """A verified recruiter, for publishing the roles a test needs."""
    register_hr(api)
    verify_organization(db_session)
    return api


def publish(client, **kwargs) -> int:
    """Create and publish one role, returning its id."""
    created = client.post("/api/employer/postings", json=role(**kwargs))
    assert created.status_code == 201, created.text
    posting_id = created.json()["id"]
    published = client.post(f"/api/employer/postings/{posting_id}/publish")
    assert published.status_code == 200, published.text
    return posting_id


def as_student(client, email="student@example.com"):
    """Swap the signed-in account for a fresh student."""
    client.post("/api/auth/logout")
    register_student(client, email=email)
    return client


def as_recruiter(client, email="recruiter@acme.com"):
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"email": email, "password": HR_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def client(recruiter_client):
    """A student, with one role already published to the board."""
    publish(recruiter_client)
    return as_student(recruiter_client)


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_reading_the_profile_before_saving_one_works(client):
    body = client.get("/api/profile").json()
    assert body["skills"] == []
    assert body["visible_to_recruiters"] is False


def test_profile_round_trip(client):
    saved = make_profile(client)
    assert saved["full_name"] == "Test Candidate"
    assert [s["name"] for s in saved["skills"]] == ["python"]

    fetched = client.get("/api/profile").json()
    assert fetched["years_experience"] == 4.0


def test_profile_put_replaces_skills_rather_than_merging(client):
    make_profile(client)
    make_profile(client, skills=[{"name": "go", "proficiency": "working", "years": 1}])

    assert [s["name"] for s in client.get("/api/profile").json()["skills"]] == ["go"]


def test_skill_names_are_canonicalised_on_save(client):
    make_profile(
        client, skills=[{"name": "  PostGres  ", "proficiency": "expert", "years": 5}]
    )
    assert client.get("/api/profile").json()["skills"][0]["name"] == "postgresql"


# --------------------------------------------------------------------------- #
# The board a student actually sees
# --------------------------------------------------------------------------- #


def test_a_published_role_reaches_the_board_scored(client):
    make_profile(client)
    board = client.get("/api/board").json()

    assert len(board["from_employers"]) == 1
    entry = board["from_employers"][0]
    assert entry["posting"]["title"] == "Backend Engineer"
    assert entry["applied"] is False
    assert 0 < entry["alignment"]["total"] < 100, "python but no kubernetes"


def test_the_board_explains_its_score(client):
    make_profile(client)
    posting_id = client.get("/api/board").json()["from_employers"][0]["posting"]["id"]

    alignment = client.get(f"/api/board/postings/{posting_id}").json()["alignment"]
    covered = {r["name"]: r["coverage"] for r in alignment["requirements"]}
    assert covered["python"] == "have"
    assert covered["kubernetes"] == "missing"
    assert alignment["explanation"]


def test_editing_the_profile_changes_the_score(client):
    make_profile(client)
    before = client.get("/api/board").json()["from_employers"][0]["alignment"]["total"]

    make_profile(
        client,
        skills=[
            {"name": "python", "proficiency": "expert", "years": 6},
            {"name": "kubernetes", "proficiency": "proficient", "years": 3},
        ],
    )
    after = client.get("/api/board").json()["from_employers"][0]["alignment"]["total"]
    assert after > before


def test_a_draft_never_reaches_the_board(recruiter_client):
    created = recruiter_client.post("/api/employer/postings", json=role(title="Secret"))
    assert created.status_code == 201

    as_student(recruiter_client)
    make_profile(recruiter_client)
    assert recruiter_client.get("/api/board").json()["from_employers"] == []


# --------------------------------------------------------------------------- #
# Applying, and the funnel built from it
# --------------------------------------------------------------------------- #


def test_applying_records_the_opening_event(client):
    """The funnel needs a history, and it starts here."""
    make_profile(client)
    posting_id = client.get("/api/board").json()["from_employers"][0]["posting"]["id"]
    assert client.post(f"/api/board/postings/{posting_id}/apply", json={}).status_code == 201

    funnel = client.get("/api/analytics/funnel").json()
    assert funnel["total"] == 1
    reached = {s["status"]: s["reached"] for s in funnel["stages"]}
    assert reached["applied"] == 1


def test_the_funnel_follows_the_recruiters_decisions(recruiter_client):
    """Stages move because a recruiter moved them, and the funnel sees it."""
    posting_id = publish(recruiter_client)

    as_student(recruiter_client)
    make_profile(recruiter_client)
    recruiter_client.post(f"/api/board/postings/{posting_id}/apply", json={})

    as_recruiter(recruiter_client)
    application_id = recruiter_client.get(
        f"/api/employer/postings/{posting_id}/applications"
    ).json()["candidates"][0]["application_id"]
    recruiter_client.patch(
        f"/api/employer/postings/{posting_id}/applications/{application_id}",
        json={"status": "screening"},
    )

    recruiter_client.post("/api/auth/logout")
    recruiter_client.post(
        "/api/auth/login",
        json={"email": "student@example.com", "password": "student-password-123"},
    )
    funnel = recruiter_client.get("/api/analytics/funnel").json()

    reached = {s["status"]: s["reached"] for s in funnel["stages"]}
    assert reached["applied"] == 1
    assert reached["screening"] == 1, "the history carries both stages, not just the latest"


def test_withdrawing_removes_the_application(client):
    make_profile(client)
    posting_id = client.get("/api/board").json()["from_employers"][0]["posting"]["id"]
    application_id = client.post(
        f"/api/board/postings/{posting_id}/apply", json={}
    ).json()["id"]

    assert client.delete(f"/api/board/applications/{application_id}").status_code == 204
    assert client.get("/api/board/applications").json() == []
    assert client.get("/api/analytics/funnel").json()["total"] == 0


# --------------------------------------------------------------------------- #
# Skill ROI and what-if, over the open board
# --------------------------------------------------------------------------- #


def test_skill_roi_ranks_the_gap(client):
    make_profile(client)
    roi = client.get("/api/skill-roi").json()

    assert roi, "an open posting the student does not fully match should yield ROI"
    assert roi[0]["skill"] == "kubernetes"
    assert roi[0]["mean_gain"] > 0


def test_skill_roi_reports_unlocks(recruiter_client):
    """A skill that takes a role over the threshold should say which role."""
    publish(recruiter_client, title="Nearly", requirements=[
        {"name": "python", "necessity": "required", "min_years": 3},
        {"name": "kubernetes", "necessity": "preferred", "min_years": 1},
    ])
    as_student(recruiter_client)
    make_profile(recruiter_client)

    roi = recruiter_client.get("/api/skill-roi").json()
    kubernetes = next(r for r in roi if r["skill"] == "kubernetes")
    assert kubernetes["demand"] >= 1
    assert kubernetes["best_gain"] > 0


def test_what_if_adding_a_skill_lifts_the_board(client):
    make_profile(client)
    result = client.post(
        "/api/simulation/what-if", json={"add_skills": ["kubernetes"], "add_at": "proficient"}
    ).json()

    assert result["mean_after"] > result["mean_before"]
    assert result["deltas"], "the simulation should name the roles it moved"


def test_what_if_persists_nothing(client):
    make_profile(client)
    before = client.get("/api/board").json()["from_employers"][0]["alignment"]["total"]

    client.post("/api/simulation/what-if", json={"add_skills": ["kubernetes"]})

    after = client.get("/api/board").json()["from_employers"][0]["alignment"]["total"]
    assert after == before
    assert [s["name"] for s in client.get("/api/profile").json()["skills"]] == ["python"]


def test_what_if_can_lower_a_salary_floor(client):
    make_profile(client, min_salary=200_000)
    before = client.get("/api/skill-roi").json()

    relaxed = client.post(
        "/api/simulation/what-if", json={"min_salary": 80_000}
    ).json()

    assert relaxed["mean_after"] >= relaxed["mean_before"]
    assert before is not None


# --------------------------------------------------------------------------- #
# Empty states
# --------------------------------------------------------------------------- #


def test_endpoints_are_safe_with_an_empty_board(student):
    """A student who signs up before any role is published sees zeroes."""
    make_profile(student)

    assert student.get("/api/board").json() == {"from_employers": [], "sourced": []}
    assert student.get("/api/skill-roi").json() == []
    assert student.get("/api/analytics/funnel").json()["total"] == 0
    assert student.post("/api/simulation/what-if", json={}).json()["deltas"] == []


def test_roadmap_refuses_with_nothing_to_plan_around(student):
    response = student.post("/api/learning/roadmap", json={})
    assert response.status_code in (409, 422)
