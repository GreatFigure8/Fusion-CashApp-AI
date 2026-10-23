"""API contracts for the notification log. Separate from the ORM model."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from cashapp.data.models.notification_log import NotificationLog
from cashapp.domain.paging import Page


class NotificationLogOut(BaseModel):
    id: int
    kind: str
    severity: str
    channel: str
    recipients: list[str]
    subject: str
    event_ids: list[str]
    item_count: int
    sent_at: datetime
    status: Literal["sent", "failed", "suppressed"]
    error: str | None

    @classmethod
    def of(cls, row: NotificationLog) -> "NotificationLogOut":
        return cls(
            id=row.id,
            kind=row.kind,
            severity=row.severity,
            channel=row.channel,
            recipients=list(row.recipients),
            subject=row.subject,
            event_ids=list(row.event_ids),
            item_count=row.item_count,
            sent_at=row.sent_at,
            status=row.status,  # pyright: ignore[reportArgumentType]
            error=row.error,
        )


class NotificationLogPage(BaseModel):
    items: list[NotificationLogOut]
    total: int
    offset: int
    limit: int

    @classmethod
    def of(cls, page: Page[NotificationLog]) -> "NotificationLogPage":
        return cls(
            items=[NotificationLogOut.of(row) for row in page.items],
            total=page.total,
            offset=page.offset,
            limit=page.limit,
        )
