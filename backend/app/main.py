"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import models  # noqa: F401  (imported for its side effect, see below)
from app.api.deps import HR_ONLY, STUDENT_ONLY

# `models` above is imported purely to populate `Base.metadata`. Without it the
# lifespan's create_all would produce an empty schema. Imported as `from app
# import models` rather than `import app.models`, which would bind the name
# `app` and shadow the FastAPI instance defined below.
from app.api.routes import (
    admin,
    analytics,
    auth,
    board,
    employer,
    interview,
    learning,
    modules,
    profile,
    resume,
    simulation,
)
from app.core.config import settings
from app.core.security import rate_limit_api, startup_check
from app.db.session import Base, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def _bootstrap_schema() -> None:
    """Bring the database up to the code's schema, however far behind it is.

    Two paths:

    * **Empty database** — `create_all`, then stamp the head. Faster than
      replaying every migration, and stamping is what keeps Alembic able to
      manage it afterwards; without that, the next upgrade dies on "table
      already exists".
    * **Existing database** — `alembic upgrade head`. Idempotent, so a database
      already at head is a no-op.

    The second branch used to return early, leaving migrations to "a release
    command" that was never wired up. The result was a deploy that shipped new
    code against an old schema: the app started, served pages, and 500'd on
    `no such table: accounts` the moment anyone tried to register. An app that
    boots into a broken state is worse than one that refuses to boot, so this
    now runs the migration itself.

    **Single-instance assumption.** Two processes migrating at once can
    deadlock or double-apply. Fine for one Render instance; scaling out means
    moving this to a pre-deploy command that runs once.
    """
    from alembic import command
    from sqlalchemy import inspect

    if not inspect(engine).get_table_names():
        logger.info("Empty database — creating the schema and stamping it.")
        Base.metadata.create_all(bind=engine)
        command.stamp(_alembic_config(), "head")
        return

    logger.info("Existing database — running migrations up to head.")
    command.upgrade(_alembic_config(), "head")
    logger.info("Schema is up to date.")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Bring the schema up to date, then start serving.

    Every phase announces itself and reports how long it took. That is not
    decoration: a deploy once died here with the log ending mid-phase and no
    error, and there was no way to tell from the outside which step had stalled
    — migrations, the configuration check, or the account bootstrap. A silent
    gap between two log lines is a diagnosis nobody can make.

    Only the schema blocks startup. Everything optional runs after the app is
    answering, because a slow recovery path must not be able to stop the
    application booting.
    """
    started = time.monotonic()

    _phase("schema", _bootstrap_schema)
    _phase("configuration check", startup_check)

    logger.info("Startup finished in %.1fs — serving.", time.monotonic() - started)

    # Deliberately not awaited and deliberately not blocking. The bootstrap
    # account is a way back in when you are locked out, not something the app
    # needs in order to serve a page — and it hashes a password with Argon2,
    # which is slow by design and slower again on a small instance.
    bootstrap = asyncio.create_task(asyncio.to_thread(_phase, "account bootstrap", _bootstrap_account))

    yield

    bootstrap.cancel()


def _phase(name: str, step) -> None:
    """Run one startup phase, saying when it began and how long it took."""
    logger.info("Startup: %s…", name)
    began = time.monotonic()
    try:
        step()
    except Exception:
        logger.exception("Startup: %s FAILED after %.1fs", name, time.monotonic() - began)
        raise
    logger.info("Startup: %s done in %.1fs", name, time.monotonic() - began)


def _bootstrap_account() -> None:
    """Apply BOOTSTRAP_ADMIN_* if set. Never fatal.

    A failure here must not stop the app booting: the variables are a recovery
    mechanism, and an app that refuses to start because a recovery path failed
    is worse than one you cannot yet sign in to.
    """
    from app.db.session import SessionLocal
    from app.services.accounts import bootstrap_from_env

    try:
        with SessionLocal() as db:
            bootstrap_from_env(db)
    except Exception:
        logger.exception("Bootstrap account setup failed; continuing.")


app = FastAPI(
    title="Career Copilot",
    version="0.1.0",
    lifespan=lifespan,
    description=(
        "Turns a job post into an alignment score, a skill-gap map, and a "
        "concrete next move. All scoring is deterministic and auditable; the "
        "LLM handles extraction, validation, and narrative advice only."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Signs the session cookie the password gate issues. A random per-process key
# is a deliberate fallback rather than a hard failure: it keeps a local
# checkout working with no configuration, at the cost of logging everyone out
# on restart. startup_check() warns when that is happening.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key or secrets.token_urlsafe(32),
    session_cookie="career_copilot_session",
    max_age=settings.session_days * 86400,
    same_site="lax",
    https_only=settings.cookie_secure,
)

# Unauthenticated by necessity — this is where you register and sign in.
app.include_router(auth.router)

# The student-facing surface. Every one of these routes reads or writes data
# owned by the signed-in student, so the role check is applied at the router
# rather than repeated in each handler — a route added later cannot arrive
# unprotected by accident. Individually expensive routes carry an extra AI
# limit of their own.
# `extract` and `opportunities` are deliberately absent. Reading a job out of
# a URL, a PDF or a screenshot is how a role gets onto the board, and putting
# roles on the board is a recruiter's job — the student side is the board
# itself, not a private scrapbook beside it. The routes still exist under
# /api/employer, and the tables keep the rows anybody already had.
for module in (
    profile,
    simulation,
    analytics,
    resume,
    interview,
    learning,
    board,
    modules,
):
    app.include_router(module.router, dependencies=STUDENT_ONLY)

# The recruiter-facing surface. Same reasoning, different role: the check sits
# at the router so no handler can be reached by the wrong kind of account.
app.include_router(employer.router, dependencies=HR_ONLY)

# Administration. `require_admin` is on each route rather than the router,
# because these are few enough that an explicit check per handler reads better
# than an inherited one — and this is the surface that grants access.
app.include_router(admin.router, dependencies=[Depends(rate_limit_api)])


def _mount_frontend() -> None:
    """Serve the built frontend from this app, when a build is present.

    This is what makes the project deployable as one process on one port: no
    separate static host, no CORS, no second service to keep in sync. In
    development the build doesn't exist and Vite serves the frontend instead,
    so this is a no-op and nothing changes.

    Mounted last, after every API router, so `/api/...` and `/health` always
    win over the catch-all below.
    """
    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        logger.info("No frontend build at %s — serving API only.", dist)
        return

    # Hashed asset filenames are safe to cache hard; index.html must not be, or
    # a redeploy leaves browsers holding a page that references deleted bundles.
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    index = (dist / "index.html").read_bytes()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        """Hand every unmatched path to the SPA so client-side routing works.

        A hard refresh on /opportunities/9 is a real GET the server must answer;
        without this it would 404. An unmatched /api path is excluded so a
        mistyped endpoint returns a JSON 404 rather than the HTML shell, which
        is far more confusing to debug.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such endpoint.")
        return Response(
            content=index,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    logger.info("Serving the frontend build from %s", dist)


@app.get("/health", tags=["meta"])
def health() -> dict[str, object]:
    """Liveness, plus whether the AI features can authenticate.

    `ai_available` lets the UI warn up front instead of after the user has
    pasted a job description and clicked Extract.
    """
    from app.agents.client import credentials_available, no_credentials

    available = credentials_available()
    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "ai_available": available,
        "ai_note": None if available else no_credentials(),
    }


@app.get("/api/meta/config", tags=["meta"])
def public_config() -> dict[str, object]:
    """Settings the sign-in screen needs before anyone is authenticated."""
    return {
        "ai_available": True,
        "org_verification_required": settings.require_org_verification,
    }


# Last, so the SPA catch-all cannot shadow a real route.
_mount_frontend()
