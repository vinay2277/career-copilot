"""Tests for published postings, the student board, and applying.

The negative cases carry most of the weight: a recruiter must not touch another
organization's postings, a student must not see drafts or closed roles, and
requirements must not change under people who have already been scored against
them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import JobPosting, PostingApplication, PostingStatus
from tests.conftest import register_hr, register_student


def verify_organization(db_session, name: str = "Acme") -> None:
    """Approve an organization, as an admin eventually will.

    Posting is gated on verification, so almost every test here needs it.
    """
    from app.models import Organization

    with db_session() as db:
        org = db.execute(
            select(Organization).where(Organization.name == name)
        ).scalar_one()
        org.verified_at = datetime.now(UTC)
        db.commit()


DRAFT = {
    "title": "Senior Backend Engineer",
    "description": "Build payment services.",
    "location": "Bengaluru",
    "remote": True,
    "seniority": "senior",
    "salary_min": 2_800_000,
    "salary_max": 4_200_000,
    "currency": "INR",
    "industry": "fintech",
    "requirements": [
        {"name": "python", "necessity": "required", "min_years": 3},
        {"name": "postgresql", "necessity": "required", "min_years": 2},
        {"name": "kubernetes", "necessity": "preferred", "min_years": 0},
    ],
    "raw_text": "Senior Backend Engineer. Python, PostgreSQL, Kubernetes.",
}


@pytest.fixture
def employer(api, db_session):
    """A verified recruiter, signed in."""
    register_hr(api)
    verify_organization(db_session)
    return api


@pytest.fixture
def published(employer):
    """A published posting, with the recruiter still signed in."""
    created = employer.post("/api/employer/postings", json=DRAFT)
    assert created.status_code == 201, created.text
    posting_id = created.json()["id"]

    published = employer.post(f"/api/employer/postings/{posting_id}/publish")
    assert published.status_code == 200, published.text
    return posting_id


def sign_in_student(client, email="student@example.com", skills=None):
    """Register a student and give them a profile worth scoring."""
    client.post("/api/auth/logout")
    register_student(client, email=email)
    client.put(
        "/api/profile",
        json={
            "full_name": "Test Student",
            "years_experience": 4,
            "skills": skills
            if skills is not None
            else [{"name": "python", "proficiency": "expert", "years": 5}],
            "preferences": None,
        },
    )
    return client


# --------------------------------------------------------------------------- #
# Verification gate
# --------------------------------------------------------------------------- #


def test_an_unverified_organization_cannot_post(api):
    """Registration is open; posting roles is not."""
    register_hr(api)
    response = api.post("/api/employer/postings", json=DRAFT)
    assert response.status_code == 403
    assert "verification" in response.json()["detail"]


def test_a_verified_organization_can_post(employer):
    assert employer.post("/api/employer/postings", json=DRAFT).status_code == 201


def test_students_cannot_reach_employer_routes(client):
    register_student(client)
    assert client.get("/api/employer/postings").status_code == 403


def test_recruiters_cannot_reach_the_student_board(employer):
    assert employer.get("/api/board").status_code == 403


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


def test_a_new_posting_starts_as_a_draft(employer):
    created = employer.post("/api/employer/postings", json=DRAFT).json()
    assert created["status"] == "draft"


def test_drafts_are_invisible_to_students(employer, client):
    employer.post("/api/employer/postings", json=DRAFT)
    sign_in_student(client)

    board = client.get("/api/board").json()
    assert board["from_employers"] == []


def test_publishing_puts_it_on_the_board(published, client):
    sign_in_student(client)
    board = client.get("/api/board").json()

    assert len(board["from_employers"]) == 1
    assert board["from_employers"][0]["posting"]["title"] == DRAFT["title"]


def test_publishing_without_requirements_is_refused(employer):
    """Every candidate would score zero, making the ranking meaningless."""
    created = employer.post(
        "/api/employer/postings", json={**DRAFT, "requirements": []}
    ).json()

    response = employer.post(f"/api/employer/postings/{created['id']}/publish")
    assert response.status_code == 409
    assert "requirement" in response.json()["detail"]


def test_closing_removes_it_from_the_board(published, employer, client):
    employer.post(f"/api/employer/postings/{published}/close")
    sign_in_student(client)
    assert client.get("/api/board").json()["from_employers"] == []


def test_a_posting_past_its_closing_date_is_not_open(published, employer, db_session):
    with db_session() as db:
        posting = db.get(JobPosting, published)
        posting.closes_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
        assert posting.is_open() is False


def test_a_draft_can_be_deleted(employer):
    created = employer.post("/api/employer/postings", json=DRAFT).json()
    assert employer.delete(f"/api/employer/postings/{created['id']}").status_code == 204


def test_a_published_posting_cannot_be_deleted(published, employer):
    """Deleting it would take applicants' records with it."""
    response = employer.delete(f"/api/employer/postings/{published}")
    assert response.status_code == 409
    assert "Only drafts" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Tenant isolation between organizations
# --------------------------------------------------------------------------- #


def test_one_organization_cannot_see_anothers_postings(api, db_session):
    register_hr(api, email="first@acme.com", organization_name="Acme")
    verify_organization(db_session, "Acme")
    api.post("/api/employer/postings", json=DRAFT)

    api.post("/api/auth/logout")
    register_hr(api, email="second@globex.com", organization_name="Globex")
    verify_organization(db_session, "Globex")

    assert api.get("/api/employer/postings").json() == []


def test_one_organization_cannot_fetch_anothers_posting_by_id(api, db_session):
    register_hr(api, email="first@acme.com", organization_name="Acme")
    verify_organization(db_session, "Acme")
    posting_id = api.post("/api/employer/postings", json=DRAFT).json()["id"]

    api.post("/api/auth/logout")
    register_hr(api, email="second@globex.com", organization_name="Globex")
    verify_organization(db_session, "Globex")

    # 404 rather than 403 — probing ids must not confirm what exists.
    assert api.get(f"/api/employer/postings/{posting_id}").status_code == 404
    assert api.post(f"/api/employer/postings/{posting_id}/close").status_code == 404


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #


def test_applying_records_the_score(published, client):
    sign_in_student(client)
    response = client.post(f"/api/board/postings/{published}/apply", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["alignment_score"] is not None
    assert body["status"] == "applied"
    assert "python" in body["alignment_detail"]["have"]


def test_applying_twice_is_refused(published, client):
    sign_in_student(client)
    client.post(f"/api/board/postings/{published}/apply", json={})

    second = client.post(f"/api/board/postings/{published}/apply", json={})
    assert second.status_code == 409
    assert "already applied" in second.json()["detail"]


def test_the_board_shows_that_you_applied(published, client):
    sign_in_student(client)
    client.post(f"/api/board/postings/{published}/apply", json={})

    entry = client.get("/api/board").json()["from_employers"][0]
    assert entry["applied"] is True
    assert entry["application_status"] == "applied"


def test_cannot_apply_to_a_closed_posting(published, employer, client):
    employer.post(f"/api/employer/postings/{published}/close")
    sign_in_student(client)

    response = client.post(f"/api/board/postings/{published}/apply", json={})
    assert response.status_code in (404, 409)


def test_the_stored_score_does_not_move_when_the_profile_changes(
    published, client, db_session
):
    """A recruiter's ranking must not reorder itself as people edit profiles."""
    sign_in_student(client)
    client.post(f"/api/board/postings/{published}/apply", json={})

    with db_session() as db:
        original = db.execute(select(PostingApplication)).scalar_one().alignment_score

    client.put(
        "/api/profile",
        json={
            "full_name": "Test Student",
            "years_experience": 9,
            "skills": [
                {"name": "python", "proficiency": "expert", "years": 9},
                {"name": "postgresql", "proficiency": "expert", "years": 9},
                {"name": "kubernetes", "proficiency": "expert", "years": 9},
            ],
            "preferences": None,
        },
    )

    with db_session() as db:
        after = db.execute(select(PostingApplication)).scalar_one().alignment_score
    assert after == original


def test_withdrawing_removes_the_application(published, client):
    sign_in_student(client)
    application_id = client.post(
        f"/api/board/postings/{published}/apply", json={}
    ).json()["id"]

    assert client.delete(f"/api/board/applications/{application_id}").status_code == 204
    assert client.get("/api/board/applications").json() == []
    # And you can apply again afterwards.
    assert client.post(f"/api/board/postings/{published}/apply", json={}).status_code == 201


def test_one_student_cannot_withdraw_anothers_application(published, api):
    sign_in_student(api, email="first@example.com")
    application_id = api.post(
        f"/api/board/postings/{published}/apply", json={}
    ).json()["id"]

    sign_in_student(api, email="second@example.com")
    assert api.delete(f"/api/board/applications/{application_id}").status_code == 404


def test_my_applications_lists_only_your_own(published, api):
    sign_in_student(api, email="first@example.com")
    api.post(f"/api/board/postings/{published}/apply", json={})

    sign_in_student(api, email="second@example.com")
    assert api.get("/api/board/applications").json() == []


# --------------------------------------------------------------------------- #
# Editing after applications exist
# --------------------------------------------------------------------------- #


def test_requirements_cannot_change_once_someone_has_applied(
    published, employer, api
):
    """Otherwise applicants were scored against terms that no longer exist."""
    sign_in_student(api)
    api.post(f"/api/board/postings/{published}/apply", json={})

    # Sign the recruiter back in — `sign_in_student` shares this client, so it
    # is currently holding the student's session.
    employer.post("/api/auth/logout")
    employer.post(
        "/api/auth/login",
        json={"email": "recruiter@acme.com", "password": "recruiter-password-123"},
    )

    response = employer.put(
        f"/api/employer/postings/{published}",
        json={**DRAFT, "title": "Changed"},
    )
    assert response.status_code == 409
    assert "already applied" in response.json()["detail"]


def test_a_posting_with_no_applications_can_be_edited(published, employer):
    response = employer.put(
        f"/api/employer/postings/{published}", json={**DRAFT, "title": "Revised title"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Revised title"


# --------------------------------------------------------------------------- #
# Board behaviour
# --------------------------------------------------------------------------- #


def test_the_board_scores_against_the_students_own_profile(published, api):
    """Two students, same posting, different scores."""
    sign_in_student(
        api,
        email="strong@example.com",
        skills=[
            {"name": "python", "proficiency": "expert", "years": 6},
            {"name": "postgresql", "proficiency": "expert", "years": 4},
            {"name": "kubernetes", "proficiency": "working", "years": 2},
        ],
    )
    strong = api.get("/api/board").json()["from_employers"][0]["alignment"]["total"]

    sign_in_student(
        api,
        email="weak@example.com",
        skills=[{"name": "cobol", "proficiency": "expert", "years": 6}],
    )
    weak = api.get("/api/board").json()["from_employers"][0]["alignment"]["total"]

    assert strong > weak


def test_the_board_omits_the_breakdown_unless_asked(published, client):
    sign_in_student(client)

    lean = client.get("/api/board").json()["from_employers"][0]
    assert lean["alignment"]["requirements"] == []

    full = client.get("/api/board?include_breakdown=true").json()["from_employers"][0]
    assert len(full["alignment"]["requirements"]) == 3


def test_the_detail_view_always_includes_the_derivation(published, client):
    sign_in_student(client)
    entry = client.get(f"/api/board/postings/{published}").json()

    assert len(entry["alignment"]["requirements"]) == 3
    assert "Total" in entry["alignment"]["explanation"]


def test_min_score_filters_the_board(published, client):
    sign_in_student(
        client, skills=[{"name": "cobol", "proficiency": "expert", "years": 6}]
    )
    assert client.get("/api/board?min_score=90").json()["from_employers"] == []


def test_an_empty_board_is_safe(client):
    sign_in_student(client)
    board = client.get("/api/board").json()
    assert board == {"from_employers": [], "sourced": []}


def test_sourced_and_employer_postings_are_separated(published, client, db_session):
    """The two sections a student sees are the product decision, not a filter."""
    from app.models import PostingSource

    with db_session() as db:
        db.add(
            JobPosting(
                source=PostingSource.SOURCED,
                status=PostingStatus.OPEN,
                title="Sourced Role",
                company_name="Elsewhere Inc",
                opens_at=datetime.now(UTC),
            )
        )
        db.commit()

    sign_in_student(client)
    board = client.get("/api/board").json()

    assert [p["posting"]["title"] for p in board["from_employers"]] == [DRAFT["title"]]
    assert [p["posting"]["title"] for p in board["sourced"]] == ["Sourced Role"]
