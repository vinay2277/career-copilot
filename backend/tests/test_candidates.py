"""Tests for the recruiter's view of who applied.

The rules that matter here are about who may see a student's contact details
and what the score is allowed to do. A recruiter sees applicants to their own
roles and nobody else's; the score ranks the list and never removes anyone from
it; and a status only changes because a person changed it.
"""

from __future__ import annotations

import csv
import io

import pytest
from sqlalchemy import select

from app.models import Organization
from tests.conftest import HR_PASSWORD, register_hr, register_student
from tests.test_postings import DRAFT, verify_organization

STUDENT_PASSWORD = "student-password-123"

STRONG = [
    {"name": "python", "proficiency": "expert", "years": 6},
    {"name": "postgresql", "proficiency": "proficient", "years": 4},
    {"name": "kubernetes", "proficiency": "working", "years": 2},
]
WEAK = [{"name": "python", "proficiency": "learning", "years": 0.5}]


def apply_as(client, posting_id, email, skills, cover_note=None):
    """Register a student with a profile worth scoring, then apply."""
    client.post("/api/auth/logout")
    name = email.split("@")[0].title()
    register_student(client, email=email, full_name=name)
    client.put(
        "/api/profile",
        json={
            "full_name": name,
            "email": email,
            "headline": "Engineer",
            "years_experience": 3,
            "career_goal": None,
            "skills": skills,
            "preferences": None,
        },
    )
    response = client.post(
        f"/api/board/postings/{posting_id}/apply", json={"cover_note": cover_note}
    )
    assert response.status_code == 201, response.text
    return response.json()


def sign_in_recruiter(client, email="recruiter@acme.com"):
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"email": email, "password": HR_PASSWORD}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def role(api, db_session):
    """A published role with a strong and a weak applicant, recruiter signed in."""
    register_hr(api)
    verify_organization(db_session)
    posting_id = api.post("/api/employer/postings", json=DRAFT).json()["id"]
    assert api.post(f"/api/employer/postings/{posting_id}/publish").status_code == 200

    apply_as(api, posting_id, "weak@example.com", WEAK, cover_note="Keen to learn.")
    apply_as(api, posting_id, "strong@example.com", STRONG)

    sign_in_recruiter(api)
    return posting_id


def candidates(api, posting_id):
    response = api.get(f"/api/employer/postings/{posting_id}/applications")
    assert response.status_code == 200, response.text
    return response.json()


def test_candidates_are_ranked_best_first(api, role):
    body = candidates(api, role)

    assert [c["full_name"] for c in body["candidates"]] == ["Strong", "Weak"]
    best, worst = body["candidates"]
    assert best["alignment_score"] > worst["alignment_score"]
    assert body["status_counts"] == {"applied": 2}


def test_a_weak_candidate_is_still_listed(api, role):
    """The score ranks; it must never quietly drop somebody from the list.

    Filtering low scores out would turn advice into an automated rejection the
    recruiter never made and the candidate could never appeal.
    """
    weak = candidates(api, role)["candidates"][-1]

    assert weak["full_name"] == "Weak"
    assert weak["alignment_score"] < 50
    assert weak["missing"], "the breakdown should say what they lack"
    assert weak["cover_note"] == "Keen to learn."


def test_the_breakdown_explains_the_ranking(api, role):
    best = candidates(api, role)["candidates"][0]

    assert "python" in best["have"]
    assert "postgresql" in best["have"]
    assert best["email"] == "strong@example.com"
    assert set(best["skills"]) >= {"python", "postgresql", "kubernetes"}


def test_another_organization_cannot_see_the_candidates(api, role):
    api.post("/api/auth/logout")
    register_hr(api, email="rival@globex.com", organization_name="Globex")

    assert api.get(f"/api/employer/postings/{role}/applications").status_code in (403, 404)


def test_a_student_cannot_read_the_candidate_list(api, role):
    api.post("/api/auth/logout")
    register_student(api, email="nosy@example.com")

    assert api.get(f"/api/employer/postings/{role}/applications").status_code == 403


def test_unverified_organization_cannot_see_candidates(api, db_session, role):
    """Approval lapsing closes the candidate list; the posting itself stays up."""
    with db_session() as db:
        org = db.execute(select(Organization)).scalar_one()
        org.verified_at = None
        db.commit()

    blocked = api.get(f"/api/employer/postings/{role}/applications")
    assert blocked.status_code == 403
    assert "verification" in blocked.json()["detail"]


def test_recruiter_moves_a_candidate_along(api, role):
    application_id = candidates(api, role)["candidates"][0]["application_id"]

    moved = api.patch(
        f"/api/employer/postings/{role}/applications/{application_id}",
        json={"status": "screening"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "screening"
    assert candidates(api, role)["status_counts"] == {"screening": 1, "applied": 1}


def test_the_student_sees_the_decision(api, role):
    """A status the candidate cannot see would be no better than none."""
    application_id = candidates(api, role)["candidates"][0]["application_id"]
    api.patch(
        f"/api/employer/postings/{role}/applications/{application_id}",
        json={"status": "interviewing"},
    )

    api.post("/api/auth/logout")
    api.post(
        "/api/auth/login",
        json={"email": "strong@example.com", "password": STUDENT_PASSWORD},
    )
    mine = api.get("/api/board/applications").json()
    assert [a["application"]["status"] for a in mine] == ["interviewing"]


def test_a_recruiter_cannot_mark_somebody_withdrawn(api, role):
    """Withdrawing is the candidate's own act, and their record should say so."""
    application_id = candidates(api, role)["candidates"][0]["application_id"]

    refused = api.patch(
        f"/api/employer/postings/{role}/applications/{application_id}",
        json={"status": "withdrawn"},
    )
    assert refused.status_code == 409
    assert "withdraw" in refused.json()["detail"].lower()


def test_an_application_from_another_posting_is_not_reachable(api, role):
    other = api.post(
        "/api/employer/postings", json={**DRAFT, "title": "Other role"}
    ).json()["id"]
    application_id = candidates(api, role)["candidates"][0]["application_id"]

    stray = api.patch(
        f"/api/employer/postings/{other}/applications/{application_id}",
        json={"status": "rejected"},
    )
    assert stray.status_code == 404


def test_csv_export(api, role):
    response = api.get(f"/api/employer/postings/{role}/applications.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert [r["name"] for r in rows] == ["Strong", "Weak"]
    assert rows[0]["stage"] == "Applied", "the export uses the words the UI uses"
    assert [r["rank"] for r in rows] == ["1", "2"]
    assert rows[0]["email"] == "strong@example.com"
    assert "python" in rows[0]["requirements_met"]
    assert rows[1]["cover_note"] == "Keen to learn."


def test_csv_opens_cleanly_in_excel(api, role):
    """The BOM is load-bearing: without it Excel on Windows mangles accents."""
    response = api.get(f"/api/employer/postings/{role}/applications.csv")
    assert response.content.startswith(b"\xef\xbb\xbf")


def test_export_is_scoped_to_the_organization(api, role):
    api.post("/api/auth/logout")
    register_hr(api, email="rival@globex.com", organization_name="Globex")

    assert api.get(
        f"/api/employer/postings/{role}/applications.csv"
    ).status_code in (403, 404)


def test_no_applicants_yet(api, db_session):
    register_hr(api)
    verify_organization(db_session)
    posting_id = api.post("/api/employer/postings", json=DRAFT).json()["id"]
    api.post(f"/api/employer/postings/{posting_id}/publish")

    body = candidates(api, posting_id)
    assert body["candidates"] == []
    assert body["status_counts"] == {}
    assert body["posting"]["title"] == DRAFT["title"]
