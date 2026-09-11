"""Alembic environment.

Pulls the database URL from the app's own settings rather than alembic.ini, so
there is exactly one place a connection string is configured.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings

# Importing the models package populates Base.metadata, which is what
# autogenerate diffs against. Without it every migration comes out empty.
from app import models  # noqa: F401
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
        autogen_context.imports.add("import sqlalchemy as sa")
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=settings.database_url.startswith("sqlite"),
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
