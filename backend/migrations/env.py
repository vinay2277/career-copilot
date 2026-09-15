"""Alembic environment.

Pulls the database URL from the app's own settings rather than alembic.ini, so
there is exactly one place a connection string is configured.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the models package populates Base.metadata, which is what
# autogenerate diffs against. Without it every migration comes out empty.
from app import models  # noqa: F401
from app.core.config import settings
from app.db.session import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context) -> str | bool:
    """Render `EnumStr` columns as plain `sa.String` in generated migrations.

    `EnumStr` is a `TypeDecorator` whose constructor needs an enum class, which
    autogenerate cannot serialize — left alone it emits `EnumStr(length=32)` and
    the migration dies on a missing argument. At the database level the type is
    just a VARCHAR, and DDL is all a migration cares about, so that is what gets
    written. Returning False falls back to default rendering for everything else.
    """
    from app.db.types import EnumStr

    if type_ == "type" and isinstance(obj, EnumStr):
        # No need to register an `sa` import: script.py.mako already declares
        # it, and adding it here emits a duplicate import in every migration.
        return f"sa.String(length={obj.impl.length})"
    return False


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most columns in place; batch mode rewrites the
        # table instead. Harmless on PostgreSQL.
        render_as_batch=settings.database_url.startswith("sqlite"),
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations against the live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _bound_the_wait(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=settings.database_url.startswith("sqlite"),
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


def _bound_the_wait(connection) -> None:
    """Make a blocked migration fail loudly instead of hanging forever.

    Adding a column or a foreign key needs a lock on the table. During a deploy
    the previous instance is still serving, still holding connections, and any
    one of them in an open transaction will make the new instance's migration
    wait — by default, indefinitely.

    That is what an unbounded wait looks like from the outside: migrations
    start, the log goes quiet, the health check times out, and there is no
    error anywhere saying why. A bounded wait turns the same situation into a
    stack trace naming the lock, which is a problem somebody can act on.

    Postgres only; SQLite has no such settings and no such contention.
    """
    if not settings.database_url.startswith("postgresql"):
        return

    from sqlalchemy import text

    # Long enough to ride out a request finishing, short enough that the
    # platform's health check has not given up by the time it fails.
    connection.execute(text("SET lock_timeout = '20s'"))
    connection.execute(text("SET statement_timeout = '120s'"))
    connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
