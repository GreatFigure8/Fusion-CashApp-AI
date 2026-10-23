"""Async Alembic environment. Models self-register by living in cashapp.data.models."""

import asyncio
import importlib
import pkgutil

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

import cashapp.data.models as models_pkg
from cashapp.data.base import Base
from cashapp.data.engine import create_engine
from cashapp.settings import get_settings

config = context.config

for _info in pkgutil.iter_modules(models_pkg.__path__):
    importlib.import_module(f"{models_pkg.__name__}.{_info.name}")

target_metadata = Base.metadata


def _database_url() -> str:
    """The one place the migration URL comes from: the `atp` settings group."""
    return get_settings().atp.url().render_as_string(hide_password=False)


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
        connect_args=get_settings().atp.connect_args(),
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
