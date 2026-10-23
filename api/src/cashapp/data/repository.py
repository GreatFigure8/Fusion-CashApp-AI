"""The generic repository. Flushes, never commits: transaction boundaries belong to services."""

from collections.abc import Sequence
from typing import Any, ClassVar, Generic, TypeVar, cast

from sqlalchemy import ColumnElement, Select, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from cashapp.data.models.base import Base
from cashapp.domain.paging import Page

__all__ = ["BaseRepository", "ModelT", "Page"]

ModelT = TypeVar("ModelT", bound=Base)

# `list` is shadowed inside the class by the repository method of that name.
type Rows[T] = list[T]


class BaseRepository(Generic[ModelT]):  # noqa: UP046 - pinned interface uses the TypeVar form
    """get / list / add / update / delete for one model; subclasses set ``model``."""

    model: ClassVar[type[Base]]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    def _pk(self) -> Any:
        return inspect(self.model).primary_key[0]

    async def get(self, id: int) -> ModelT | None:
        return cast("ModelT | None", await self._session.get(self.model, id))

    async def list(
        self,
        *,
        where: Sequence[ColumnElement[bool]] = (),
        order_by: Sequence[Any] = (),
        offset: int = 0,
        limit: int = 50,
    ) -> Page[ModelT]:
        ordering = tuple(order_by) or (self._pk(),)
        stmt = select(self.model).where(*where).order_by(*ordering).offset(offset).limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        count_stmt = select(func.count()).select_from(self.model).where(*where)
        total = (await self._session.execute(count_stmt)).scalar_one()
        return Page(items=cast("Rows[ModelT]", [*rows]), total=total, offset=offset, limit=limit)

    async def add(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update(self, entity: ModelT, **changes: Any) -> ModelT:
        for name in changes:
            if not hasattr(type(entity), name):
                raise AttributeError(f"{type(entity).__name__} has no attribute {name!r}")
        for name, value in changes.items():
            setattr(entity, name, value)
        await self._session.flush()
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self._session.delete(entity)
        await self._session.flush()

    async def select_for_update_skip_locked(
        self, stmt: Select[ModelT], limit: int | None = None
    ) -> Rows[ModelT]:
        """Lock the rows ``stmt`` selects, skipping rows another transaction holds.

        With ``limit`` the candidate keys are chosen first and the rows locked in a second query,
        because Oracle rejects FOR UPDATE combined with a row-limiting clause on some versions.
        Fewer than ``limit`` rows come back when some candidates are locked elsewhere.
        """
        if limit is None:
            locked = stmt.with_for_update(skip_locked=True)
            return [*(await self._session.execute(locked)).scalars().all()]
        pk = self._pk()
        key_rows = (await self._session.execute(stmt.with_only_columns(pk).limit(limit))).scalars()
        keys = [*key_rows.all()]
        if not keys:
            return []
        locked = stmt.where(pk.in_(keys)).with_for_update(skip_locked=True)
        return [*(await self._session.execute(locked)).scalars().all()]
