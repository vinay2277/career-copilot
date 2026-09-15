"""Tests for candidate search.

Most of these exist to defend one rule: a student appears in a recruiter's
search only because they switched `visible_to_recruiters` on. Not because they
uploaded a résumé, not because they filled in a profile, and not because they
applied to a role. Those are different acts and consenting to one is not
consenting to the others.
"""

from __future__ import annotations

import pytest

from tests.conftest import HR_PASSWORD, register_hr, register_student
from tests.test_postings import DRAFT, verify_organization

SEARCH = "/api/employer/candidates/search"


def make_student(client, email, name, skills, *, visible, **profile):
    """Register a student and save a profile, opting in or not."""
    client.post("/api/auth/logout")
    register_student(client, email=email, full_name=name)
    body = {
        "full_name": name,
        "email": email,
        "headline": profile.get("headline"),
        "years_experience": profile.get("years", 3),
        "career_goal": None,
        "location": profile.get("location"),
        "open_to_work": profile.get("open_to_work", True),
        "visible_to_recruiters": visible,
        "skills": [
            {"name": n, "proficiency": p, "years": y} for n, p, y in skills
        ],
        "preferences": profile.get("preferences"),
    }
    response = client.put("/api/profile", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def sign_in_recruiter(client, email="recruiter@acme.com"):
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"email": email, "password": HR_PASSWORD}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def recruiter_with_candidates(api, db_session):
    """Three opted-in candidates and one who did not opt in."""
    register_hr(api)
    verify_organization(db_session)

    make_student(
        api,
        "deep@example.com",
        "Deep Python",
        [("python", "expert", 6), ("django", "proficient", 4)],
        visible=True,
        years=6,
        location="Bengaluru",
        headline="Backend engineer",
    )
    make_student(
        api,
        "broad@example.com",
        "Broad Stack",
        [("python", "working", 2), ("react", "expert", 5), ("sql", "proficient", 3)],
        visible=True,
        years=5,
        location="Pune",
    )
    make_student(
        api,
        "junior@example.com",
        "Junior Dev",
        [("python", "learning", 0.5)],
        visible=True,
        years=1,
        location="Remote",
    )
    make_student(
        api,
        "private@example.com",
        "Private Person",
        [("python", "expert", 9), ("django", "expert", 8)],
        visible=False,
        years=9,
        location="Bengaluru",
    )

    sign_in_recruiter(api)
    return api


def search(api, **body):
    response = api.post(SEARCH, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_only_opted_in_candidates_are_findable(recruiter_with_candidates):
    """The rule this whole feature hangs on.

    Private Person is the strongest Python candidate in the database by a wide
    margin. They must not appear, because they never agreed to be found.
    """
    body = search(recruiter_with_candidates, skills=["python"])

    names = [r["full_name"] for r in body["results"]]
    assert "Private Person" not in names
    assert names == ["Deep Python", "Broad Stack", "Junior Dev"]
    assert body["searchable_total"] == 3


def test_applying_does_not_make_you_searchable(api, db_session):
    """Applying is consent for that one role, not to be in a candidate database."""
    register_hr(api)
    verify_organization(db_session)
    posting_id = api.post("/api/employer/postings", json=DRAFT).json()["id"]
    api.post(f"/api/employer/postings/{posting_id}/publish")

    make_student(
        api,
        "applicant@example.com",
        "Applied Only",
        [("python", "expert", 5)],
        visible=False,
    )
    assert (
        api.post(f"/api/board/postings/{posting_id}/apply", json={}).status_code == 201
    )

    sign_in_recruiter(api)

    # Visible to the recruiter as an applicant to their own role...
    applicants = api.get(f"/api/employer/postings/{posting_id}/applications").json()
    assert [c["full_name"] for c in applicants["candidates"]] == ["Applied Only"]

    # ...and absent from search.
    body = search(api, skills=["python"])
    assert body["results"] == []
    assert body["searchable_total"] == 0


def test_ranked_by_fit(recruiter_with_candidates):
    body = search(recruiter_with_candidates, skills=["python", "django"])

    results = body["results"]
    assert results[0]["full_name"] == "Deep Python"
    assert results[0]["score"] > results[1]["score"]
    assert set(results[0]["have"]) == {"python", "django"}
    assert "django" in results[1]["missing"]


def test_a_weak_match_is_still_returned(recruiter_with_candidates):
    """The score orders the list; it does not decide who is on it."""
    body = search(recruiter_with_candidates, skills=["python", "django"])

    names = [r["full_name"] for r in body["results"]]
    assert "Junior Dev" in names, "a weak candidate is ranked last, not removed"


def test_an_empty_search_lists_everyone_opted_in(recruiter_with_candidates):
    """'Who is here?' is a real question and deserves an answer."""
    body = search(recruiter_with_candidates)

    assert len(body["results"]) == 3
    assert all(r["score"] is None for r in body["results"]), (
        "no skills means nothing to score against; a number would be invented"
    )
    # Falls back to experience.
    assert body["results"][0]["full_name"] == "Deep Python"


def test_minimum_years_filter(recruiter_with_candidates):
    body = search(recruiter_with_candidates, skills=["python"], min_years=5)
    assert [r["full_name"] for r in body["results"]] == ["Deep Python", "Broad Stack"]


def test_location_matches_where_they_want_to_work_too(api, db_session):
    """Somebody willing to move is exactly who a location search should find."""
    register_hr(api)
    verify_organization(db_session)

    make_student(
        api,
        "mover@example.com",
        "Willing Mover",
        [("python", "expert", 5)],
        visible=True,
        location="Pune",
        preferences={
            "target_roles": [],
            "locations": ["Bengaluru"],
            "remote_ok": True,
            "seniority": None,
            "min_salary": None,
            "currency": "INR",
            "company_sizes": [],
            "industries": [],
        },
    )
    sign_in_recruiter(api)

    body = search(api, skills=["python"], location="Bengaluru")
    assert [r["full_name"] for r in body["results"]] == ["Willing Mover"]


def test_not_open_to_work_is_excluded_by_default(api, db_session):
    register_hr(api)
    verify_organization(db_session)
    make_student(
        api,
        "settled@example.com",
        "Happily Settled",
        [("python", "expert", 8)],
        visible=True,
        open_to_work=False,
    )
    sign_in_recruiter(api)

    assert search(api, skills=["python"])["results"] == []
    found = search(api, skills=["python"], open_to_work_only=False)["results"]
    assert [r["full_name"] for r in found] == ["Happily Settled"]


def test_turning_visibility_off_removes_you(recruiter_with_candidates, api):
    """Withdrawing consent has to actually withdraw it."""
    assert len(search(api, skills=["python"])["results"]) == 3

    api.post("/api/auth/logout")
    api.post(
        "/api/auth/login",
        json={"email": "deep@example.com", "password": "student-password-123"},
    )
    current = api.get("/api/profile").json()
    api.put("/api/profile", json={**current, "visible_to_recruiters": False})

    sign_in_recruiter(api)
    names = [r["full_name"] for r in search(api, skills=["python"])["results"]]
    assert "Deep Python" not in names
    assert search(api, skills=["python"])["searchable_total"] == 2


def test_a_student_cannot_search_candidates(api, db_session):
    register_student(api, email="nosy@example.com")
    assert api.post(SEARCH, json={"skills": ["python"]}).status_code == 403


def test_an_unverified_organization_cannot_search(api):
    register_hr(api)
    blocked = api.post(SEARCH, json={"skills": ["python"]})
    assert blocked.status_code == 403
    assert "verification" in blocked.json()["detail"]


def test_signed_out_cannot_search(client):
    assert client.post(SEARCH, json={"skills": ["python"]}).status_code == 401
