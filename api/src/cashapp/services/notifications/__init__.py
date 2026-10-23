"""Notifications: batching, rendering, channels, dispatch and the report email entry point.

Emitting a notification is ``cashapp.services.notify.emit_notify`` (the one outbox writer).
"""

from cashapp.services.notifications.batcher import Batch, NotificationBatcher
from cashapp.services.notifications.channel import (
    ChannelName,
    Channels,
    ChannelSendError,
    NotificationChannel,
    build_channels,
)
from cashapp.services.notifications.dispatcher import (
    DispatchResult,
    NotificationDispatcher,
    NotificationStatus,
)
from cashapp.services.notifications.log_query import NotificationLogService
from cashapp.services.notifications.render import RenderedMessage, render_batch
from cashapp.services.notifications.reports import Attachment, send_report_email

__all__ = [
    "Attachment",
    "Batch",
    "ChannelName",
    "ChannelSendError",
    "Channels",
    "DispatchResult",
    "NotificationBatcher",
    "NotificationChannel",
    "NotificationDispatcher",
    "NotificationLogService",
    "NotificationStatus",
    "RenderedMessage",
    "build_channels",
    "render_batch",
    "send_report_email",
]
