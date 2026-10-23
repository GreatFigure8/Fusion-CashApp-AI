"""Async engine factory for Oracle (thin mode) and, in tests, aiosqlite."""

from typing import Any

import oracledb
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(url: str, **opts: Any) -> AsyncEngine:
    """Build the async engine. Thin mode is oracledb's default; never init the thick client."""
    if url.startswith("oracle://"):
        url = "oracle+oracledb://" + url.removeprefix("oracle://")
    # NUMBER columns come back as Decimal, never float: money is Decimal end to end.
    oracledb.defaults.fetch_decimals = True
    return create_async_engine(url, pool_pre_ping=True, **opts)
