"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
