"""The one writer of ``NotifyEvent`` rows to the outbox (s36, s38, s42 and s18 use it)."""

from cashapp.data.models.outbox import OutboxMessage
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock
from cashapp.domain.notifications import NOTIFY_TOPIC_NAME, NotifyEvent
from cashapp.domain.work_item import PRIORITY_LIVE
from cashapp.pipeline.events import TopicNamer, default_namer, enqueue


def notify_topic(namer: TopicNamer | None = None) -> str:
    return (namer or default_namer()).named(NOTIFY_TOPIC_NAME)


async def emit_notify(
    uow: UnitOfWork, event: NotifyEvent, *, clock: Clock | None = None
) -> OutboxMessage:
    """Write one outbox row for ``event`` in the caller's transaction (flush, no commit)."""
    key = str(event.work_item_id) if event.work_item_id is not None else event.kind.value
    return await enqueue(
        uow,
        topic=notify_topic(),
        key=key,
        payload=event,
        priority=PRIORITY_LIVE,
        clock=clock,
    )
