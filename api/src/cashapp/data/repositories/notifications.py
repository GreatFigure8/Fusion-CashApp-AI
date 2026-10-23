"""Queries over NOTIFICATION_LOG and the transient-error history used by the outage source."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import ColumnElement, func, select

from cashapp.data.models.notification_log import NotificationLog
from cashapp.data.models.work_item import WorkItemHistory
from cashapp.data.repository import BaseRepository, Page
from cashapp.domain.error_codes import ErrorCode


class NotificationLogRepository(BaseRepository[NotificationLog]):
    model = NotificationLog

    async def search(
        self,
        *,
        kind: str | None,
        from_: datetime | None,
        to: datetime | None,
        offset: int,
        limit: int,
    ) -> Page[NotificationLog]:
        """Log rows newest first, optionally filtered by kind and a ``sent_at`` range."""
        where: list[ColumnElement[bool]] = []
        if kind is not None:
            where.append(NotificationLog.kind == kind)
        if from_ is not None:
            where.append(NotificationLog.sent_at >= from_)
        if to is not None:
            where.append(NotificationLog.sent_at <= to)
        return await self.list(
            where=where,
            order_by=(NotificationLog.sent_at.desc(), NotificationLog.id.desc()),
            offset=offset,
            limit=limit,
        )


class TransientErrorRepository(BaseRepository[WorkItemHistory]):
    model = WorkItemHistory

    async def count_since(self, codes: Collection[ErrorCode], since: datetime) -> int:
        """History rows carrying one of ``codes`` at or after ``since``."""
        if not codes:
            return 0
        stmt = (
            select(func.count())
            .select_from(WorkItemHistory)
            .where(WorkItemHistory.error_code.in_(list(codes)), WorkItemHistory.at >= since)
        )
        return int((await self.session.execute(stmt)).scalar_one())
