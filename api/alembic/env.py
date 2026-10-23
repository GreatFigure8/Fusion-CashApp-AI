"""Async Alembic environment. Models self-register by living in cashapp.data.models."""

import asyncio
import functools

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from cashapp.data.engine import create_engine
from cashapp.data.models import Base, load_all_models
from cashapp.settings import Settings, load_settings

config = context.config

load_all_models()

target_metadata = Base.metadata


@functools.cache
def _settings() -> Settings:
    """Migrations tolerate the removed deploy variables: the s48 data migration seeds the DB keys
    from them. Any other unknown `CASHAPP_*` variable is still refused."""
    return load_settings(allow_legacy_env=True)


def _database_url() -> str:
    """The one place the migration URL comes from: the `atp` settings group."""
    return _settings().atp.url().render_as_string(hide_password=False)


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
    engine = create_engine(
        _database_url(),
        poolclass=NullPool,
        connect_args=_settings().atp.connect_args(),
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
