"""Read side of the notification log."""

from datetime import datetime

from cashapp.data.models.notification_log import NotificationLog
from cashapp.data.repositories.notifications import NotificationLogRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.paging import Page


class NotificationLogService:
    async def list_log(
        self,
        uow: UnitOfWork,
        *,
        kind: str | None,
        from_: datetime | None,
        to: datetime | None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[NotificationLog]:
        return await uow.repo(NotificationLogRepository).search(
            kind=kind, from_=from_, to=to, offset=offset, limit=limit
        )
