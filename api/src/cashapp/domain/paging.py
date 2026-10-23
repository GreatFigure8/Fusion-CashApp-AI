"""A page of results. Pure, so routers and services need no SQLAlchemy import."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    offset: int
    limit: int
