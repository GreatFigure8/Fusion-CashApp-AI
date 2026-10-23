"""An in-memory notification channel for tests and ``env == "local"``."""

from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from typing import cast

from cashapp.services.notifications.channel import ChannelName, ChannelSendError


@dataclass(frozen=True, slots=True)
class SentMessage:
    channel: str
    recipients: tuple[str, ...]
    subject: str
    body_text: str
    body_html: str | None
    attachments: tuple[tuple[str, bytes, str], ...] = ()


class FakeChannel:
    def __init__(self, name: ChannelName = "email", *, fail_with: Exception | None = None) -> None:
        self.name: ChannelName = name
        self.fail_with = fail_with
        self.sent: list[SentMessage] = []

    async def send(
        self,
        recipients: Sequence[str],
        subject: str,
        body_text: str,
        body_html: str | None,
    ) -> None:
        if self.fail_with is not None:
            raise ChannelSendError(
                self.name, f"{type(self.fail_with).__name__}: {self.fail_with}"
            ) from self.fail_with
        self.sent.append(SentMessage(self.name, tuple(recipients), subject, body_text, body_html))

    async def send_message(self, message: EmailMessage) -> None:
        """Record a prebuilt message, keeping its attachments (used by ``send_report_email``)."""
        if self.fail_with is not None:
            raise ChannelSendError(
                self.name, f"{type(self.fail_with).__name__}: {self.fail_with}"
            ) from self.fail_with
        body = message.get_body(preferencelist=("plain",))
        html = message.get_body(preferencelist=("html",))
        attachments = tuple(
            (
                part.get_filename() or "attachment",
                bytes(cast("bytes", part.get_payload(decode=True) or b"")),
                part.get_content_type(),
            )
            for part in message.iter_attachments()
        )
        self.sent.append(
            SentMessage(
                self.name,
                tuple(a.strip() for a in str(message["To"] or "").split(",") if a.strip()),
                str(message["Subject"] or ""),
                body.get_content() if body is not None else "",
                html.get_content() if html is not None else None,
                attachments,
            )
        )
