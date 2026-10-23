"""The channel interface: how a rendered message leaves the system."""

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol

from cashapp.services.runtime_settings import RuntimeSettings

ChannelName = Literal["email", "teams"]

REASON_MAX = 2000


class ChannelSendError(Exception):
    """A send failed. ``reason`` is an exception class plus a short message, never the body."""

    def __init__(self, channel: ChannelName, reason: str) -> None:
        self.channel: ChannelName = channel
        self.reason = reason[:REASON_MAX]
        super().__init__(f"{channel}: {self.reason}")


class NotificationChannel(Protocol):
    name: ChannelName

    async def send(
        self,
        recipients: Sequence[str],
        subject: str,
        body_text: str,
        body_html: str | None,
    ) -> None:
        """Deliver one message to every recipient. Raises ``ChannelSendError`` on failure."""
        ...


Channels = Mapping[ChannelName, NotificationChannel]


def build_channels(runtime: RuntimeSettings) -> Channels:
    """The channels this environment can use. A missing channel suppresses its sends."""
    from cashapp.integrations.email.fake import FakeChannel
    from cashapp.integrations.email.smtp import SmtpEmailChannel
    from cashapp.integrations.email.teams_webhook import TeamsWebhookChannel

    if runtime.env == "local":
        return {"email": FakeChannel("email"), "teams": FakeChannel("teams")}
    channels: dict[ChannelName, NotificationChannel] = {"teams": TeamsWebhookChannel()}
    smtp = runtime.smtp()
    if smtp is not None:
        channels["email"] = SmtpEmailChannel(smtp, lambda: runtime.secret(smtp.password_ref))
    return channels
