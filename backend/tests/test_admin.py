"""Tests for organization verification.

Verification is the control that stops anyone registering as a recruiter and
harvesting students' contact details behind a fake role, so the tests that
matter most here are the negative ones: that a student or a recruiter cannot
reach these routes, and that an unverified organization really is blocked from
publishing until somebody approves it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Account, Organization, Role
from tests.conftest import HR_PASSWORD, register_hr, register_student
from tests.test_postings import DRAFT

ADMIN_EMAIL = "admin@example.com"


def sign_in_recruiter(client, email: str = "recruiter@acme.com"):
    """Swap back to the recruiter after acting as somebody else."""
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"email": email, "password": HR_PASSWORD}
    )
    assert response.status_code == 200, response.text


def make_admin(client, db_session, email: str = ADMIN_EMAIL):
    """Sign in as an administrator.

    There is deliberately no route that creates one — an account that can
    approve companies is not something you should be able to sign up for. So
    this promotes a registered account directly, which is what the
    BOOTSTRAP_ADMIN_* variables do on a real deployment.
    """
    client.post("/api/auth/logout")
    register_student(client, email=email, full_name="Test Admin")
    with db_session() as db:
        account = db.execute(
            select(Account).where(Account.email == email)
        ).scalar_one()
        account.role = Role.ADMIN
        db.commit()
    return client


@pytest.fixture
def admin(api, db_session):
    return make_admin(api, db_session)


ADMIN_ROUTES = [
    ("get", "/api/admin/organizations"),
    ("get", "/api/admin/stats"),
    ("post", "/api/admin/organizations/1/verify"),
    ("post", "/api/admin/organizations/1/unverify"),
]


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_signed_out_is_refused(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_student_is_refused(student, method, path):
    """A student must not be able to approve their own employer."""
    assert getattr(student, method)(path).status_code == 403


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_recruiter_is_refused(recruiter, method, path):
    """The obvious attack: verify yourself, then post whatever you like."""
    assert getattr(recruiter, method)(path).status_code == 403


def test_registering_as_a_recruiter_leaves_the_organization_pending(api, db_session):
    register_hr(api)
    make_admin(api, db_session)

    rows = api.get("/api/admin/organizations").json()
    assert [r["name"] for r in rows] == ["Acme"]
    assert rows[0]["is_verified"] is False
    assert rows[0]["member_emails"] == ["recruiter@acme.com"]
    assert rows[0]["member_count"] == 1
    assert rows[0]["posting_count"] == 0


def test_verification_unblocks_posting(api, db_session):
    """The whole point, end to end.

    Before approval the employer write surface is closed — including the AI
    parse route, so an unvetted account cannot register on a free email and
    spend the deployment's model credit. After approval it all opens.
    """
    register_hr(api)
    blocked = api.post("/api/employer/postings", json=DRAFT)
    assert blocked.status_code == 403, blocked.text
    assert "verification" in blocked.json()["detail"]
    assert (
        api.post("/api/employer/postings/parse", json={"text": "..."}).status_code == 403
    )
    # Reading your own (empty) list is not gated: there is nothing to leak.
    assert api.get("/api/employer/postings").status_code == 200

    make_admin(api, db_session)
    organization_id = api.get("/api/admin/organizations").json()[0]["id"]
    approved = api.post(f"/api/admin/organizations/{organization_id}/verify")
    assert approved.status_code == 200, approved.text
    assert approved.json()["is_verified"] is True

    sign_in_recruiter(api)
    created = api.post("/api/employer/postings", json=DRAFT)
    assert created.status_code == 201, created.text
    published = api.post(f"/api/employer/postings/{created.json()['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "open"


def test_withdrawing_approval_leaves_published_roles_alone(api, db_session):
    """Revoking approval stops new roles; it does not retract live ones.

    A student who applied to a role that was open at the time should not have
    their application disappear because the employer's approval later lapsed.
    """
    register_hr(api)
    with db_session() as db:
        org = db.execute(select(Organization)).scalar_one()
        org.verified_at = datetime.now(UTC)
        db.commit()

    posting_id = api.post("/api/employer/postings", json=DRAFT).json()["id"]
    assert api.post(f"/api/employer/postings/{posting_id}/publish").status_code == 200

    make_admin(api, db_session)
    organization_id = api.get("/api/admin/organizations").json()[0]["id"]
    withdrawn = api.post(f"/api/admin/organizations/{organization_id}/unverify")
    assert withdrawn.status_code == 200
    assert withdrawn.json()["is_verified"] is False

    # Still on the board, and still applicable to.
    api.post("/api/auth/logout")
    register_student(api)
    board = api.get("/api/board").json()
    assert [e["posting"]["id"] for e in board["from_employers"]] == [posting_id]
    assert api.post(f"/api/board/postings/{posting_id}/apply", json={}).status_code == 201

    # But the recruiter cannot post anything new.
    sign_in_recruiter(api)
    assert api.post("/api/employer/postings", json=DRAFT).status_code == 403


def test_pending_first_and_pending_only(api, db_session):
    register_hr(api, email="a@acme.com", organization_name="Acme")
    api.post("/api/auth/logout")
    register_hr(api, email="b@globex.com", organization_name="Globex")

    with db_session() as db:
        org = db.execute(
            select(Organization).where(Organization.name == "Globex")
        ).scalar_one()
        org.verified_at = datetime.now(UTC)
        db.commit()

    make_admin(api, db_session)

    names = [r["name"] for r in api.get("/api/admin/organizations").json()]
    assert names == ["Acme", "Globex"], "those awaiting a decision come first"

    pending = api.get("/api/admin/organizations?pending_only=true").json()
    assert [r["name"] for r in pending] == ["Acme"]


def test_verify_is_idempotent(api, db_session):
    register_hr(api)
    make_admin(api, db_session)
    organization_id = api.get("/api/admin/organizations").json()[0]["id"]

    first = api.post(f"/api/admin/organizations/{organization_id}/verify").json()
    second = api.post(f"/api/admin/organizations/{organization_id}/verify").json()
    assert first["is_verified"] and second["is_verified"]
    assert first["created_at"] == second["created_at"]


def test_unknown_organization_is_404(admin):
    assert admin.post("/api/admin/organizations/9999/verify").status_code == 404
    assert admin.post("/api/admin/organizations/9999/unverify").status_code == 404


def test_stats_counts(api, db_session):
    register_student(api, email="s1@example.com")
    api.post("/api/auth/logout")
    register_hr(api)
    with db_session() as db:
        org = db.execute(select(Organization)).scalar_one()
        org.verified_at = datetime.now(UTC)
        db.commit()
    posting_id = api.post("/api/employer/postings", json=DRAFT).json()["id"]
    api.post(f"/api/employer/postings/{posting_id}/publish")

    make_admin(api, db_session)
    stats = api.get("/api/admin/stats").json()

    assert stats["organizations"] == 1
    assert stats["awaiting_verification"] == 0
    assert stats["recruiters"] == 1
    assert stats["open_postings"] == 1
    # The admin registered as a student and was promoted, so it is not counted.
    assert stats["students"] == 1


def test_empty_listing(admin):
    assert admin.get("/api/admin/organizations").json() == []
    assert admin.get("/api/admin/stats").json()["organizations"] == 0
