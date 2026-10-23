"""Routes a batch to the configured channels and writes one NOTIFICATION_LOG row per attempt.

Writes and flushes the rows, never commits: the caller commits, then commits the bus offsets.
A failed send never raises; it becomes a ``failed`` row.
"""

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Literal

from cashapp.data.models.notification_log import NotificationLog
from cashapp.data.repositories.notifications import NotificationLogRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain import config_keys as ck
from cashapp.domain.clock import Clock
from cashapp.services.config import ConfigSnapshot
from cashapp.services.notifications.batcher import Batch
from cashapp.services.notifications.channel import (
    ChannelName,
    Channels,
    ChannelSendError,
    NotificationChannel,
)
from cashapp.services.notifications.render import RenderedMessage, render_batch

logger = logging.getLogger(__name__)

NotificationStatus = Literal["sent", "failed", "suppressed"]

SEND_ATTEMPTS: Final = 2
RETRY_DELAY_SECONDS: Final = 2.0
ERROR_MAX: Final = 2000
NO_CHANNEL: Final = "none"

_CHANNEL_ALIASES: Final[dict[str, ChannelName]] = {
    "email": "email",
    "teams": "teams",
    "webhook": "teams",
}


@dataclass(frozen=True, slots=True)
class DispatchResult:
    channel: str
    status: NotificationStatus
    log_id: int


def recipients_by_channel(config: ConfigSnapshot, kind: str) -> dict[ChannelName, tuple[str, ...]]:
    """The configured recipients for ``kind``, keyed by delivery channel, empty lists dropped."""
    configured = config.notifications().recipients.get(kind, {})
    merged: dict[ChannelName, list[str]] = {}
    for raw_name, addresses in configured.items():
        name = _CHANNEL_ALIASES.get(raw_name)
        if name is None:
            continue
        bucket = merged.setdefault(name, [])
        bucket.extend(a for a in addresses if a and a not in bucket)
    return {name: tuple(items) for name, items in merged.items() if items}


def loggable_recipients(channel: ChannelName, recipients: tuple[str, ...]) -> list[str]:
    """Addresses as stored in the log. A Teams webhook URL is a secret: only a hash prefix."""
    if channel == "teams":
        return [f"teams:{hashlib.sha256(url.encode()).hexdigest()[:12]}" for url in recipients]
    return list(recipients)


class NotificationDispatcher:
    def __init__(
        self,
        channels: Channels,
        *,
        clock: Clock,
        env_label: str,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._channels = channels
        self._clock = clock
        self._env_label = env_label
        self._sleep = sleep

    async def dispatch(
        self, uow: UnitOfWork, batch: Batch, config: ConfigSnapshot
    ) -> list[DispatchResult]:
        message = render_batch(
            batch.kind,
            batch.events,
            window_seconds=config.notifications().batch_window_seconds,
            env_label=self._env_label,
            app_base_url=config.get(ck.NOTIFICATIONS_APP_BASE_URL),
        )
        targets = recipients_by_channel(config, batch.kind)
        if not targets:
            row = await self._log(
                uow, batch, message, NO_CHANNEL, [], "suppressed", "no_recipients"
            )
            return [DispatchResult(NO_CHANNEL, "suppressed", row.id)]

        results: list[DispatchResult] = []
        for name, recipients in targets.items():
            channel = self._channels.get(name)
            stored = loggable_recipients(name, recipients)
            if channel is None:
                row = await self._log(
                    uow, batch, message, name, stored, "suppressed", "channel_not_configured"
                )
                results.append(DispatchResult(name, "suppressed", row.id))
                continue
            error = await self._send(channel, recipients, message)
            status: NotificationStatus = "sent" if error is None else "failed"
            row = await self._log(uow, batch, message, name, stored, status, error)
            results.append(DispatchResult(name, status, row.id))
            logger.info(
                "notification %s: kind=%s channel=%s events=%d",
                status,
                batch.kind,
                name,
                len(batch.events),
            )
        return results

    async def _send(
        self, channel: NotificationChannel, recipients: tuple[str, ...], message: RenderedMessage
    ) -> str | None:
        """``None`` on success, else the failure reason of the last attempt."""
        error: str | None = None
        for attempt in range(SEND_ATTEMPTS):
            try:
                await channel.send(
                    recipients, message.subject, message.body_text, message.body_html
                )
            except ChannelSendError as exc:
                error = exc.reason[:ERROR_MAX]
            except Exception as exc:  # a channel bug must not block the queue
                error = f"{type(exc).__name__}: send failed"
            else:
                return None
            if attempt + 1 < SEND_ATTEMPTS:
                await self._sleep(RETRY_DELAY_SECONDS)
        return error

    async def _log(
        self,
        uow: UnitOfWork,
        batch: Batch,
        message: RenderedMessage,
        channel: str,
        recipients: list[str],
        status: NotificationStatus,
        error: str | None,
    ) -> NotificationLog:
        item_ids = {e.work_item_id for e in batch.events if e.work_item_id is not None}
        row = NotificationLog(
            kind=batch.kind,
            severity=batch.severity,
            channel=channel,
            recipients=recipients,
            subject=message.subject,
            event_ids=[str(e.event_id) for e in batch.events],
            item_count=len(item_ids) if item_ids else len(batch.events),
            sent_at=self._clock.now(),
            status=status,
            error=error[:ERROR_MAX] if error is not None else None,
        )
        return await uow.repo(NotificationLogRepository).add(row)
