"""Async Alembic environment. Models self-register by living in cashapp.data.models."""

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection

from cashapp.data.engine import create_engine
from cashapp.data.models import Base, load_all_models

config = context.config

load_all_models()

target_metadata = Base.metadata


def _database_url() -> str:
    """The one place the migration URL comes from (s27 rewires this to the settings object)."""
    url = os.environ.get("CASHAPP_DATABASE_URL")
    if not url:
        raise RuntimeError("CASHAPP_DATABASE_URL is not set; it must hold the SQLAlchemy URL.")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
