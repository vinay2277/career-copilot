"""Tests for registration, sign-in, and the role boundary.

This is the authorization boundary, so the tests that matter most are the
negative ones: a student must not reach recruiter routes, one student must not
reach another's data, and an unverified organization must not reach candidates.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.passwords import hash_password, needs_rehash, verify_password
from app.models import Account, Organization, Profile
from tests.conftest import (
    HR_PASSWORD,
    STUDENT_PASSWORD,
    register_hr,
    register_student,
)

# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_student_registration_signs_you_in(client):
    body = register_student(client)
    assert body["authenticated"] is True
    assert body["account"]["role"] == "student"
    assert client.get("/api/profile").status_code == 200


def test_student_registration_creates_a_profile(client, db_session):
    register_student(client)
    with db_session() as db:
        profile = db.execute(select(Profile)).scalar_one()
        assert profile.full_name == "Test Student"
        assert profile.email == "student@example.com"


def test_hr_registration_creates_an_organization(client, db_session):
    body = register_hr(client)
    assert body["account"]["role"] == "hr"
    assert body["account"]["organization"]["name"] == "Acme"

    with db_session() as db:
        org = db.execute(select(Organization)).scalar_one()
        assert org.domain == "acme.com"
        assert org.verified_at is None  # unverified until reviewed


def test_a_second_recruiter_joins_the_same_organization(client, db_session):
    """Domain matching, so one approval covers the whole company."""
    register_hr(client, email="first@acme.com")
    client.post("/api/auth/logout")
    register_hr(client, email="second@acme.com", organization_name="Acme Corp")

    with db_session() as db:
        assert len(db.execute(select(Organization)).scalars().all()) == 1


def test_free_mail_recruiters_do_not_share_an_organization(client, db_session):
    """Otherwise every gmail.com recruiter lands in one shared company."""
    register_hr(client, email="one@gmail.com", organization_name="One Ltd")
    client.post("/api/auth/logout")
    register_hr(client, email="two@gmail.com", organization_name="Two Ltd")

    with db_session() as db:
        orgs = db.execute(select(Organization)).scalars().all()
        assert len(orgs) == 2
        assert all(o.domain is None for o in orgs)


def test_duplicate_email_is_refused(client):
    register_student(client)
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/register/student",
        json={
            "email": "student@example.com",
            "password": STUDENT_PASSWORD,
            "full_name": "Impostor",
        },
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_email_case_does_not_create_a_second_account(client):
    register_student(client, email="Vinay@Example.COM")
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/register/student",
        json={
            "email": "vinay@example.com",
            "password": STUDENT_PASSWORD,
            "full_name": "Same Person",
        },
    )
    assert response.status_code == 409


def test_short_passwords_are_refused(client):
    response = client.post(
        "/api/auth/register/student",
        json={"email": "a@b.com", "password": "short", "full_name": "A"},
    )
    assert response.status_code == 422


def test_malformed_email_is_refused(client):
    response = client.post(
        "/api/auth/register/student",
        json={"email": "not-an-email", "password": STUDENT_PASSWORD, "full_name": "A"},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Sign-in
# --------------------------------------------------------------------------- #


def test_sign_in_with_the_right_password(client):
    register_student(client)
    client.post("/api/auth/logout")

    response = client.post(
        "/api/auth/login",
        json={"email": "student@example.com", "password": STUDENT_PASSWORD},
    )
    assert response.status_code == 200
    assert client.get("/api/profile").status_code == 200


def test_wrong_password_is_refused(client):
    register_student(client)
    client.post("/api/auth/logout")

    response = client.post(
        "/api/auth/login",
        json={"email": "student@example.com", "password": "wrong-password-xx"},
    )
    assert response.status_code == 401
    assert client.get("/api/profile").status_code == 401


def test_unknown_and_wrong_password_give_the_same_message(client):
    """Distinguishing them tells an attacker which addresses are registered."""
    register_student(client)
    client.post("/api/auth/logout")

    wrong = client.post(
        "/api/auth/login",
        json={"email": "student@example.com", "password": "wrong-password-xx"},
    )
    unknown = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "wrong-password-xx"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_logout_ends_the_session(client):
    register_student(client)
    client.post("/api/auth/logout")
    assert client.get("/api/profile").status_code == 401


def test_session_reports_who_is_signed_in(client):
    register_student(client)
    body = client.get("/api/auth/session").json()
    assert body["authenticated"] is True
    assert body["account"]["email"] == "student@example.com"


def test_session_is_readable_while_signed_out(client):
    """The frontend needs this to choose between sign-in and the app."""
    body = client.get("/api/auth/session").json()
    assert body == {"authenticated": False, "account": None}


def test_a_suspended_account_cannot_use_its_existing_session(client, db_session):
    """Suspension must take effect immediately, not when the cookie expires."""
    register_student(client)
    assert client.get("/api/profile").status_code == 200

    with db_session() as db:
        account = db.execute(select(Account)).scalar_one()
        account.is_active = False
        db.commit()

    assert client.get("/api/profile").status_code == 401


# --------------------------------------------------------------------------- #
# Role boundary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    ["/api/profile", "/api/opportunities", "/api/skill-roi", "/api/analytics/funnel"],
)
def test_recruiters_cannot_reach_student_routes(recruiter, path):
    response = recruiter.get(path)
    assert response.status_code == 403
    assert "students" in response.json()["detail"]


def test_students_reach_their_own_routes(student):
    assert student.get("/api/profile").status_code == 200
    assert student.get("/api/opportunities").status_code == 200


def test_anonymous_callers_are_refused(client):
    assert client.get("/api/profile").status_code == 401
    assert client.get("/api/opportunities").status_code == 401


# --------------------------------------------------------------------------- #
# Tenant isolation — the property the whole refactor exists for
# --------------------------------------------------------------------------- #


def test_one_student_cannot_see_another_students_profile(client):
    register_student(client, email="first@example.com", full_name="First Student")
    client.put(
        "/api/profile",
        json={
            "full_name": "First Student",
            "years_experience": 5,
            "skills": [{"name": "python", "proficiency": "expert", "years": 5}],
            "preferences": None,
        },
    )
    client.post("/api/auth/logout")

    register_student(client, email="second@example.com", full_name="Second Student")
    profile = client.get("/api/profile").json()

    assert profile["full_name"] == "Second Student"
    assert profile["skills"] == []


def test_saving_a_profile_cannot_touch_another_account(client, db_session):
    register_student(client, email="first@example.com")
    client.post("/api/auth/logout")
    register_student(client, email="second@example.com")

    client.put(
        "/api/profile",
        json={"full_name": "Edited", "years_experience": 1, "preferences": None},
    )

    with db_session() as db:
        names = {p.account_id: p.full_name for p in db.execute(select(Profile)).scalars()}
        assert len(names) == 2
        assert "Edited" in names.values()
        assert "Test Student" in names.values()  # the first is untouched


# --------------------------------------------------------------------------- #
# Recruiter visibility consent
# --------------------------------------------------------------------------- #


def test_recruiter_visibility_is_off_by_default(student):
    """Uploading a résumé is not consent to appear in candidate searches."""
    assert student.get("/api/profile").json()["visible_to_recruiters"] is False


def test_saving_a_profile_does_not_silently_opt_you_in(student):
    student.put(
        "/api/profile",
        json={"full_name": "Test Student", "years_experience": 2, "preferences": None},
    )
    assert student.get("/api/profile").json()["visible_to_recruiters"] is False


def test_visibility_can_be_turned_on_explicitly(student):
    student.put(
        "/api/profile",
        json={
            "full_name": "Test Student",
            "years_experience": 2,
            "visible_to_recruiters": True,
            "preferences": None,
        },
    )
    assert student.get("/api/profile").json()["visible_to_recruiters"] is True


# --------------------------------------------------------------------------- #
# Password change
# --------------------------------------------------------------------------- #


def test_password_change_requires_the_current_one(student):
    """An unattended logged-in browser must not be enough to lock the owner out."""
    response = student.post(
        "/api/auth/password",
        json={"current_password": "wrong-password-xx", "new_password": "new-password-123"},
    )
    assert response.status_code == 401


def test_password_change_works_and_the_new_one_signs_in(client):
    register_student(client)
    assert (
        client.post(
            "/api/auth/password",
            json={
                "current_password": STUDENT_PASSWORD,
                "new_password": "a-brand-new-password",
            },
        ).status_code
        == 200
    )

    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "student@example.com", "password": "a-brand-new-password"},
        ).status_code
        == 200
    )


def test_the_old_password_stops_working(client):
    register_student(client)
    client.post(
        "/api/auth/password",
        json={"current_password": STUDENT_PASSWORD, "new_password": "a-brand-new-password"},
    )
    client.post("/api/auth/logout")

    assert (
        client.post(
            "/api/auth/login",
            json={"email": "student@example.com", "password": STUDENT_PASSWORD},
        ).status_code
        == 401
    )


# --------------------------------------------------------------------------- #
# Hashing
# --------------------------------------------------------------------------- #


def test_hashes_are_salted_so_two_identical_passwords_differ():
    assert hash_password("the same password") != hash_password("the same password")


def test_a_hash_verifies_its_own_password():
    stored = hash_password("correct horse battery")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("Correct horse battery", stored)
    assert not verify_password("", stored)


def test_a_corrupt_hash_fails_rather_than_raising():
    assert verify_password("anything", "not-a-real-hash") is False
    assert needs_rehash("not-a-real-hash") is True


def test_the_migration_marker_can_never_authenticate():
    """"!" is what the migration writes for an adopted account."""
    assert verify_password("", "!") is False
    assert verify_password("any guess at all", "!") is False


def test_the_password_is_never_returned(client):
    body = register_student(client)
    assert STUDENT_PASSWORD not in str(body)
    assert "password" not in str(body["account"]).lower()


def test_rate_limiting_applies_to_registration(client):
    """An unthrottled sign-up endpoint is how you get ten thousand fake users.

    Exercises the real configured limit rather than patching one in, so this
    also catches the limit being removed from the route by accident.
    """
    from app.core.config import settings

    limit = settings.rate_limit_login_per_hour
    codes = [
        client.post(
            "/api/auth/register/student",
            json={
                "email": f"spam{i}@example.com",
                "password": HR_PASSWORD,
                "full_name": "Spam",
            },
        ).status_code
        for i in range(limit + 2)
    ]

    assert codes.count(201) <= limit
    assert codes[-1] == 429


def test_rate_limiting_applies_to_sign_in(client):
    from app.core.config import settings

    register_student(client)
    client.post("/api/auth/logout")

    codes = [
        client.post(
            "/api/auth/login",
            json={"email": "student@example.com", "password": "wrong-guess-here"},
        ).status_code
        for _ in range(settings.rate_limit_login_per_hour + 2)
    ]
    assert codes[-1] == 429
