"""Tests for serving the built frontend from the API process.

This is what lets the project deploy as one process on one port. The risk it
carries is a catch-all route that quietly shadows the API, so that is what
these cover.

Skipped when no frontend build is present — a backend-only checkout is a
legitimate state, and the mount is a deliberate no-op there.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

pytestmark = pytest.mark.skipif(
    not (DIST / "index.html").is_file(),
    reason="no frontend build; run `npm run build` in frontend/ first",
)


@pytest.fixture
def client():
    # No lifespan: these tests only exercise routing, and starting it would
    # provision a schema against the configured database.
    return TestClient(app)


def test_root_serves_the_app_shell(client):
    response = client.get("/")
    assert response.status_code == 200
    assert '<div id="root">' in response.text


@pytest.mark.parametrize(
    "path",
    ["/opportunities", "/opportunities/9", "/skill-roi", "/analytics", "/profile"],
)
def test_deep_links_serve_the_shell(client, path):
    """A hard refresh on a client-side route is a real GET the server answers."""
    response = client.get(path)
    assert response.status_code == 200
    assert '<div id="root">' in response.text


def test_the_shell_is_not_cached(client):
    """index.html references hashed bundles; a cached copy survives a redeploy
    and points at files that no longer exist."""
    assert client.get("/").headers["cache-control"] == "no-cache"


def test_health_is_not_shadowed(client):
    """The catch-all must never win over a real route."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unknown_api_paths_return_json_not_html(client):
    """A mistyped endpoint returning the HTML shell is miserable to debug."""
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "<div" not in response.text


def test_api_routes_still_reach_their_handlers(client):
    """404 here is the profile dependency talking, not the catch-all."""
    response = client.get("/api/profile")
    assert response.headers["content-type"].startswith("application/json")
    assert response.status_code in (200, 404)


def test_assets_are_served(client):
    """The bundle referenced by index.html must actually resolve."""
    import re

    shell = client.get("/").text
    match = re.search(r'/assets/([^"]+\.js)', shell)
    assert match, "index.html references no JS bundle"

    response = client.get(f"/assets/{match.group(1)}")
    assert response.status_code == 200
    assert len(response.content) > 1000
