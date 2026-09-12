"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401  (imported for its side effect, see below)

# `models` above is imported purely to populate `Base.metadata`. Without it the
# lifespan's create_all would produce an empty schema. Imported as `from app
# import models` rather than `import app.models`, which would bind the name
# `app` and shadow the FastAPI instance defined below.
from app.api.routes import (
    analytics,
    extract,
    interview,
    learning,
    opportunities,
    profile,
    resume,
    simulation,
)
from app.core.config import settings
from app.db.session import Base, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def _bootstrap_schema() -> None:
    """Create the schema on a first run, and hand it to Alembic afterwards.

    Naively calling `create_all` on every startup puts the database in a state
    Alembic cannot manage: the tables exist but no revision is stamped, so the
    next `alembic upgrade head` dies on "table already exists". So this runs
    only against a genuinely empty database, and stamps the current head
    immediately afterwards — leaving Alembic correctly in sync either way.

    A database that already has tables is left strictly alone. Migrations are
    the only thing that may alter an existing schema.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    if inspect(engine).get_table_names():
        return  # already provisioned; `alembic upgrade head` owns it from here

    logger.info("Empty database — creating the schema and stamping it.")
    Base.metadata.create_all(bind=engine)

    alembic_cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.stamp(alembic_cfg, "head")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Provision the schema on a first run so a fresh clone just works."""
    _bootstrap_schema()
    yield


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

for module in (
    profile,
    extract,
    opportunities,
    simulation,
    analytics,
    resume,
    interview,
    learning,
):
    app.include_router(module.router)


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


# Last, so the SPA catch-all cannot shadow a real route.
_mount_frontend()
