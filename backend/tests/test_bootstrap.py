"""Tests for the environment-variable account bootstrap.

This is the recovery path for a host with no shell, where the multi-tenancy
migration would otherwise leave the owner permanently locked out of their own
data. It grants access, so its behaviour needs pinning down.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.passwords import verify_password
from app.models import Account, Profile, Role
from app.services.accounts import bootstrap_from_env, register_student

EMAIL = "owner@example.com"
PASSWORD = "a-recovered-password-1"


@pytest.fixture
def db(db_session):
    with db_session() as session:
        yield session


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", EMAIL)
    monkeypatch.setattr(settings, "bootstrap_admin_password", PASSWORD)


def test_does_nothing_when_unset(db, monkeypatch):
    """The common case: no variables, no accounts conjured."""
    monkeypatch.setattr(settings, "bootstrap_admin_email", "")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "")

    bootstrap_from_env(db)
    assert db.execute(select(Account)).scalars().all() == []


def test_does_nothing_with_only_an_email(db, monkeypatch):
    monkeypatch.setattr(settings, "bootstrap_admin_email", EMAIL)
    monkeypatch.setattr(settings, "bootstrap_admin_password", "")

    bootstrap_from_env(db)
    assert db.execute(select(Account)).scalars().all() == []


def test_creates_an_account_that_can_sign_in(db, configured):
    bootstrap_from_env(db)

    account = db.execute(select(Account)).scalar_one()
    assert account.email == EMAIL
    assert verify_password(PASSWORD, account.password_hash)


def test_creates_a_profile_for_the_new_account(db, configured):
    bootstrap_from_env(db)

    profile = db.execute(select(Profile)).scalar_one()
    account = db.execute(select(Account)).scalar_one()
    assert profile.account_id == account.id


def locked_account(db, email: str = "legacy-1@invalid") -> Account:
    """What the migration leaves when the original profile had no email.

    The account owns all the real data but cannot sign in — `!` is the unusable
    marker — and is named after nothing anybody knows to type.
    """
    account = Account(
        email=email, password_hash="!", role=Role.STUDENT, full_name="Vinay"
    )
    db.add(account)
    db.flush()
    db.add(Profile(account_id=account.id, full_name="Vinay"))
    db.commit()
    return account


def test_claims_the_single_locked_account_rather_than_stranding_its_data(
    db, configured
):
    """Otherwise the real data sits behind `legacy-1@invalid` forever."""
    original = locked_account(db)

    bootstrap_from_env(db)

    accounts = db.execute(select(Account)).scalars().all()
    profiles = db.execute(select(Profile)).scalars().all()

    assert len(accounts) == 1, "must claim, not create a second account"
    assert len(profiles) == 1
    assert accounts[0].id == original.id
    assert accounts[0].email == EMAIL
    assert verify_password(PASSWORD, accounts[0].password_hash)
    assert profiles[0].full_name == "Vinay"


def test_does_not_claim_a_locked_account_when_others_exist(db, configured):
    """Ambiguous — claiming the wrong one would hand over someone else's data."""
    locked_account(db)
    register_student(
        db, email="someone@example.com", password="x" * 12, full_name="Someone"
    )

    bootstrap_from_env(db)

    accounts = {a.email for a in db.execute(select(Account)).scalars()}
    assert "legacy-1@invalid" in accounts, "the locked account is left alone"
    assert EMAIL in accounts, "a fresh account is created instead"


def test_never_claims_an_account_that_can_sign_in(db, configured):
    """The guard is that the target is already unable to authenticate."""
    register_student(
        db, email="working@example.com", password="x" * 12, full_name="Working"
    )

    bootstrap_from_env(db)

    working = db.execute(
        select(Account).where(Account.email == "working@example.com")
    ).scalar_one()
    assert verify_password("x" * 12, working.password_hash)


def test_resets_the_password_of_an_existing_account(db, configured):
    register_student(
        db, email=EMAIL, password="the-original-password", full_name="Owner"
    )

    bootstrap_from_env(db)

    account = db.execute(select(Account)).scalar_one()
    assert verify_password(PASSWORD, account.password_hash)
    assert not verify_password("the-original-password", account.password_hash)


def test_reactivates_a_suspended_account(db, configured):
    """Recovery is useless if it leaves you locked out a different way."""
    register_student(db, email=EMAIL, password="x" * 12, full_name="Owner")
    account = db.execute(select(Account)).scalar_one()
    account.is_active = False
    db.commit()

    bootstrap_from_env(db)

    db.refresh(account)
    assert account.is_active is True


def test_does_not_change_an_existing_role(db, configured):
    """Resetting a password must not quietly promote or demote anyone."""
    register_student(db, email=EMAIL, password="x" * 12, full_name="Owner")
    account = db.execute(select(Account)).scalar_one()
    account.role = Role.ADMIN
    db.commit()

    bootstrap_from_env(db)

    db.refresh(account)
    assert account.role is Role.ADMIN


def test_running_twice_is_a_no_op(db, configured):
    bootstrap_from_env(db)
    bootstrap_from_env(db)

    assert len(db.execute(select(Account)).scalars().all()) == 1
    assert len(db.execute(select(Profile)).scalars().all()) == 1


def test_leaves_other_accounts_alone(db, configured):
    register_student(
        db, email="someone@example.com", password="x" * 12, full_name="Someone"
    )

    bootstrap_from_env(db)

    other = db.execute(
        select(Account).where(Account.email == "someone@example.com")
    ).scalar_one()
    assert verify_password("x" * 12, other.password_hash)


def test_a_password_that_fails_validation_creates_nothing(db, monkeypatch):
    """A rejected password must not leave a half-made account behind."""
    monkeypatch.setattr(settings, "bootstrap_admin_email", EMAIL)
    monkeypatch.setattr(settings, "bootstrap_admin_password", "short")

    bootstrap_from_env(db)
    assert db.execute(select(Account)).scalars().all() == []
