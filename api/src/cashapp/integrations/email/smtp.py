"""Email through SMTP (OCI Email Delivery). stdlib ``smtplib`` run in a worker thread.

VERIFY against the live tenant: ``smtp.email.us-ashburn-1.oci.oraclecloud.com:587`` with STARTTLS,
an approved sender (``from_address``) and SMTP credentials from Vault.
"""

import asyncio
import smtplib
import ssl
from collections.abc import Awaitable, Callable, Sequence
from email.message import EmailMessage

from pydantic import SecretStr

from cashapp.services.notifications.channel import ChannelName, ChannelSendError
from cashapp.services.runtime_settings import SmtpConfig

SMTP_SSL_PORT = 465


class SmtpEmailChannel:
    name: ChannelName = "email"

    def __init__(
        self,
        smtp: SmtpConfig,
        password: Callable[[], Awaitable[SecretStr]],
        *,
        timeout_seconds: float = 30.0,
        smtp_factory: Callable[..., smtplib.SMTP] | None = None,
    ) -> None:
        self._smtp = smtp
        self._password = password
        self._timeout = timeout_seconds
        self._factory = smtp_factory

    async def send(
        self,
        recipients: Sequence[str],
        subject: str,
        body_text: str,
        body_html: str | None,
    ) -> None:
        message = EmailMessage()
        message["From"] = self._smtp.from_address
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(body_text)
        if body_html is not None:
            message.add_alternative(body_html, subtype="html")
        await self.send_message(message)

    async def send_message(self, message: EmailMessage) -> None:
        """Send a prebuilt message. ``From`` defaults to the configured sender."""
        if "From" not in message:
            message["From"] = self._smtp.from_address
        try:
            # Resolved at send time: the password is never held between sends.
            password = (await self._password()).get_secret_value()
            await asyncio.to_thread(self._deliver, message, password)
        except Exception as exc:
            # The reason names the exception class only: SMTP errors can echo addresses.
            raise ChannelSendError("email", f"{type(exc).__name__}: smtp delivery failed") from exc

    def _deliver(self, message: EmailMessage, password: str) -> None:
        settings = self._smtp
        context = ssl.create_default_context()
        if settings.port == SMTP_SSL_PORT:
            client: smtplib.SMTP = (
                self._factory(settings.host, settings.port, timeout=self._timeout, context=context)
                if self._factory is not None
                else smtplib.SMTP_SSL(
                    settings.host, settings.port, timeout=self._timeout, context=context
                )
            )
        else:
            client = (
                self._factory(settings.host, settings.port, timeout=self._timeout)
                if self._factory is not None
                else smtplib.SMTP(settings.host, settings.port, timeout=self._timeout)
            )
        with client:
            if settings.port != SMTP_SSL_PORT:
                client.starttls(context=context)
            client.login(settings.username, password)
            client.send_message(message)
