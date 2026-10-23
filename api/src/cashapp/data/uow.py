"""The unit of work: one session, one transaction boundary, repositories on that session."""

from collections.abc import Callable
from types import TracebackType
from typing import Any, Self, TypeVar

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cashapp.data.repositories.history import HistoryRepository
from cashapp.data.repositories.outbox import OutboxRepository
from cashapp.data.repositories.work_items import WorkItemRepository
from cashapp.data.repository import BaseRepository

R = TypeVar("R", bound=BaseRepository[Any])


class UnitOfWork:
    """Async context manager. Leaving the block without ``commit()`` rolls everything back."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._session: AsyncSession | None = None
        self._repos: dict[type[BaseRepository[Any]], BaseRepository[Any]] = {}

    async def __aenter__(self) -> Self:
        self._session = self._sessionmaker()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self._session
        self._session = None
        self._repos.clear()
        if session is None:
            return
        try:
            # A no-op after commit; discards everything else.
            await session.rollback()
        finally:
            await session.close()

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork used outside its 'async with' block")
        return self._session

    def repo(self, cls: type[R]) -> R:
        """One repository instance per class per unit of work, on this session."""
        existing = self._repos.get(cls)
        if existing is None:
            existing = cls(self.session)
            self._repos[cls] = existing
        return existing  # type: ignore[return-value]

    @property
    def work_items(self) -> WorkItemRepository:
        return self.repo(WorkItemRepository)

    @property
    def history(self) -> HistoryRepository:
        return self.repo(HistoryRepository)

    @property
    def outbox(self) -> OutboxRepository:
        return self.repo(OutboxRepository)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


UowFactory = Callable[[], UnitOfWork]


def make_uow_factory(engine: AsyncEngine) -> UowFactory:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    def factory() -> UnitOfWork:
        return UnitOfWork(maker)

    return factory
