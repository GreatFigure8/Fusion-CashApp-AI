"""Database fixtures: aiosqlite for unit tests, DEV ATP (opt in) for integration tests.

Registered through ``pytest_plugins`` in ``tests/conftest.py``.
"""

import importlib
import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from cashapp.data.engine import create_engine
from cashapp.data.models import Base, load_all_models
from cashapp.data.uow import UnitOfWork, UowFactory, make_uow_factory


@pytest_asyncio.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    load_all_models()
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def uow_factory(sqlite_engine: AsyncEngine) -> UowFactory:
    return make_uow_factory(sqlite_engine)


@pytest_asyncio.fixture
async def uow(uow_factory: UowFactory) -> AsyncIterator[UnitOfWork]:
    async with uow_factory() as unit:
        yield unit
        await unit.rollback()


@pytest_asyncio.fixture
async def atp_engine() -> AsyncIterator[AsyncEngine]:
    if os.environ.get("CASHAPP_TEST_ATP") != "1":
        pytest.skip(
            "set CASHAPP_TEST_ATP=1 (and the CASHAPP_ATP__* settings) to run against DEV ATP"
        )
    load_all_models()
    settings: Any = importlib.import_module("cashapp.settings").get_settings()
    kwargs: dict[str, Any] = dict(settings.atp.engine_kwargs())
    kwargs.pop("pool_pre_ping", None)  # create_engine already sets it
    url = settings.atp.url().render_as_string(hide_password=False)
    engine = create_engine(url, **kwargs)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def atp_uow_factory(atp_engine: AsyncEngine) -> UowFactory:
    return make_uow_factory(atp_engine)
