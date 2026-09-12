"""Tests for settings normalization.

The database URL rewrite exists because every managed Postgres provider hands
out a scheme SQLAlchemy 2 refuses. Getting it wrong is a startup crash with an
opaque dialect error, so it is worth pinning down.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def url(value: str) -> str:
    return Settings(database_url=value).database_url


def test_heroku_style_url_is_rewritten():
    """Render, Railway, Heroku and Fly all hand out this shape."""
    assert url("postgres://u:p@host:5432/db") == "postgresql+psycopg://u:p@host:5432/db"


def test_bare_postgresql_scheme_is_pinned_to_psycopg3():
    """`postgresql://` alone resolves to psycopg2, which is not installed."""
    assert (
        url("postgresql://u:p@host:5432/db") == "postgresql+psycopg://u:p@host:5432/db"
    )


def test_an_explicit_driver_is_left_alone():
    given = "postgresql+psycopg://u:p@host:5432/db"
    assert url(given) == given


def test_sqlite_is_left_alone():
    assert url("sqlite:///./career_copilot.db") == "sqlite:///./career_copilot.db"


def test_only_the_scheme_is_replaced():
    """A password containing the scheme text must not be mangled."""
    given = "postgres://user:postgres://@host:5432/db"
    assert url(given) == "postgresql+psycopg://user:postgres://@host:5432/db"


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_llm_model_follows_the_provider(provider):
    settings = Settings(
        llm_provider=provider, openai_model="gpt-4o", anthropic_model="claude-opus-5"
    )
    assert settings.llm_model == (
        "gpt-4o" if provider == "openai" else "claude-opus-5"
    )


def test_auth_is_off_when_no_password_is_set():
    assert Settings(app_password="").auth_enabled is False
    assert Settings(app_password="x").auth_enabled is True


def test_cors_origins_parse_to_a_list():
    settings = Settings(cors_origins="http://a.com, http://b.com ,")
    assert settings.cors_origin_list == ["http://a.com", "http://b.com"]
