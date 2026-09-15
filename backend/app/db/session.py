"""Database engine and session management."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


# check_same_thread is a SQLite-only quirk: FastAPI serves requests from a
# threadpool, and SQLite refuses cross-thread connections by default.
connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

# pool_pre_ping costs one cheap round trip per checkout and saves the class of
# failure where a managed database has dropped an idle connection and the app
# only finds out by raising on the next real query — which on a free tier that
# sleeps is most mornings.
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    future=True,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
