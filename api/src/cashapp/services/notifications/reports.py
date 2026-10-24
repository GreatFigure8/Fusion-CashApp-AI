"""Public email entry point for reports (s41's daily summary). Supports attachments."""

import logging
import mimetypes
from collections.abc import Sequence
from email.message import EmailMessage
from typing import TYPE_CHECKING

from cashapp.data.models.notification_log import NotificationLog
from cashapp.data.repositories.notifications import NotificationLogRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.services.notifications.channel import ChannelSendError

if TYPE_CHECKING:
    from cashapp.integrations.email.fake import FakeChannel
    from cashapp.integrations.email.smtp import SmtpEmailChannel
    from cashapp.services.runtime_settings import RuntimeSettings

logger = logging.getLogger(__name__)

Attachment = tuple[str, bytes, str]  # (filename, content, content_type)

ERROR_MAX = 2000


def _build_message(
    recipients: Sequence[str],
    subject: str,
    body: str,
    attachments: Sequence[Attachment],
    body_html: str | None,
    sender: str | None,
) -> EmailMessage:
    message = EmailMessage()
    if sender is not None:
        message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    if body_html is not None:
        message.add_alternative(body_html, subtype="html")
    for filename, content, content_type in attachments:
        maintype, _, subtype = (content_type or "application/octet-stream").partition("/")
        if not subtype:
            guessed, _ = mimetypes.guess_type(filename)
            maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    return message


async def _record(
    uow: UnitOfWork,
    *,
    kind: str,
    recipients: Sequence[str],
    subject: str,
    status: str,
    error: str | None,
    clock: Clock,
) -> None:
    await uow.repo(NotificationLogRepository).add(
        NotificationLog(
            kind=kind,
            severity="info",
            channel="email" if recipients else "none",
            recipients=list(recipients),
            subject=subject[:400],
            event_ids=[],
            item_count=0,
            sent_at=clock.now(),
            status=status,
            error=error[:ERROR_MAX] if error is not None else None,
        )
    )


async def send_report_email(
    recipients: Sequence[str],
    subject: str,
    body: str,
    attachments: Sequence[Attachment] = (),
    *,
    body_html: str | None = None,
    channel: "SmtpEmailChannel | FakeChannel | None" = None,
    uow: UnitOfWork | None = None,
    kind: str = "report",
    clock: Clock | None = None,
    runtime: "RuntimeSettings | None" = None,
) -> None:
    """Email a report. With ``uow`` one NOTIFICATION_LOG row is written (flush only).

    Empty recipients are suppressed. A failed send is logged and the ``ChannelSendError`` is
    re-raised so the caller can decide what to do.
    """
    now_clock = clock or SystemClock()
    if not recipients:
        if uow is not None:
            await _record(
                uow,
                kind=kind,
                recipients=[],
                subject=subject,
                status="suppressed",
                error="no_recipients",
                clock=now_clock,
            )
        return

    if channel is None:
        from cashapp.integrations.email.smtp import SmtpEmailChannel

        smtp = runtime.smtp() if runtime is not None else None
        if runtime is None or smtp is None:
            error = ChannelSendError("email", "smtp_not_configured")
            if uow is not None:
                await _record(
                    uow,
                    kind=kind,
                    recipients=recipients,
                    subject=subject,
                    status="failed",
                    error=error.reason,
                    clock=now_clock,
                )
            raise error
        channel = SmtpEmailChannel(smtp, lambda: runtime.secret(smtp.password_ref))

    message = _build_message(recipients, subject, body, attachments, body_html, None)
    try:
        await channel.send_message(message)
    except ChannelSendError as exc:
        if uow is not None:
            await _record(
                uow,
                kind=kind,
                recipients=recipients,
                subject=subject,
                status="failed",
                error=exc.reason,
                clock=now_clock,
            )
        logger.warning("report email failed: kind=%s", kind)
        raise
    if uow is not None:
        await _record(
            uow,
            kind=kind,
            recipients=recipients,
            subject=subject,
            status="sent",
            error=None,
            clock=now_clock,
        )
    logger.info("report email sent: kind=%s recipients=%d", kind, len(recipients))
