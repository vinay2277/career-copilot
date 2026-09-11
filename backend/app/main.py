"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create any missing tables on startup.

    Convenient for local development. Alembic owns the schema in production —
    `create_all` cannot alter an existing table, so a column added after the
    first run needs a migration regardless.
    """
    Base.metadata.create_all(bind=engine)
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
def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.llm_model}
