"""The app must bring an out-of-date database up to head on startup.

Regression from a failed deploy. Startup created the schema only when the
database was empty and otherwise returned early, leaving migrations to "a
release command" that was never wired up. The deploy therefore shipped new code
against an old schema: the app booted, served pages, and 500'd with
`no such table: accounts` as soon as anyone registered.

An app that boots into a broken state is worse than one that refuses to boot.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND / "alembic.ini"

pytestmark = pytest.mark.skipif(
    not ALEMBIC_INI.is_file(), reason="alembic.ini not present"
)


def run_app_startup(db_path: Path) -> subprocess.CompletedProcess:
    """Boot the app against `db_path`, exactly as the container would."""
    code = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "with TestClient(app) as c:\n"
        "    print('STATUS', c.get('/health').status_code)\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env={
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
            "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
            "PYTHONPATH": str(BACKEND),
            "SECRET_KEY": "test-secret",
        },
        capture_output=True,
        text=True,
    )


def tables_in(db_path: Path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {
            r[0]
            for r in con.execute("select name from sqlite_master where type='table'")
        }
    finally:
        con.close()


def revision_of(db_path: Path) -> str | None:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("select version_num from alembic_version").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()


def head_revision() -> str:
    """The newest revision on disk, by walking down_revision links."""
    versions = (BACKEND / "migrations" / "versions").glob("*.py")
    revisions: dict[str, str | None] = {}
    for path in versions:
        text = path.read_text(encoding="utf-8-sig")
        rev = down = None
        for line in text.splitlines():
            if line.startswith("revision: str"):
                rev = line.split("=")[1].strip().strip("'\"")
            elif line.startswith("down_revision"):
                value = line.split("=")[1].strip()
                down = None if value == "None" else value.strip("'\"")
        if rev:
            revisions[rev] = down
    parents = {d for d in revisions.values() if d}
    heads = [r for r in revisions if r not in parents]
    assert len(heads) == 1, f"expected one head, found {heads}"
    return heads[0]


def test_an_empty_database_is_provisioned_and_stamped(tmp_path):
    db = tmp_path / "empty.db"
    db.touch()

    result = run_app_startup(db)
    assert "STATUS 200" in result.stdout, result.stderr[-1500:]

    assert "accounts" in tables_in(db)
    assert revision_of(db) == head_revision()


def test_a_database_behind_head_is_migrated_on_startup(tmp_path):
    """The deploy failure, in one test.

    Builds a database at the first revision, then boots the app against it and
    requires that the newest tables exist afterwards.
    """
    db = tmp_path / "behind.db"
    db.touch()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "7967fbefa544"],
        cwd=BACKEND,
        env={
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
            "DATABASE_URL": f"sqlite:///{db.as_posix()}",
            "PYTHONPATH": str(BACKEND),
        },
        capture_output=True,
        text=True,
        check=True,
    )

    assert "accounts" not in tables_in(db), "precondition: an old schema"
    assert revision_of(db) != head_revision()

    result = run_app_startup(db)
    assert "STATUS 200" in result.stdout, result.stderr[-1500:]

    assert "accounts" in tables_in(db), "startup did not run the migration"
    assert revision_of(db) == head_revision()


def test_a_database_already_at_head_is_left_alone(tmp_path):
    """Startup runs on every boot, so it has to be idempotent."""
    db = tmp_path / "current.db"
    db.touch()

    run_app_startup(db)
    before = (tables_in(db), revision_of(db))

    result = run_app_startup(db)
    assert "STATUS 200" in result.stdout, result.stderr[-1500:]

    assert (tables_in(db), revision_of(db)) == before


def test_existing_data_survives_the_migration(tmp_path):
    """A migration that loses rows is worse than one that fails."""
    live = BACKEND / "career_copilot.db"
    if not live.is_file():
        pytest.skip("no local database to copy")

    db = tmp_path / "with-data.db"
    shutil.copy(live, db)

    con = sqlite3.connect(db)
    before = {
        table: con.execute(f"select count(*) from {table}").fetchone()[0]
        for table in ("job_posts", "applications", "profile_skills")
    }
    con.close()

    result = run_app_startup(db)
    assert "STATUS 200" in result.stdout, result.stderr[-1500:]

    con = sqlite3.connect(db)
    after = {
        table: con.execute(f"select count(*) from {table}").fetchone()[0]
        for table in before
    }
    con.close()

    assert after == before
