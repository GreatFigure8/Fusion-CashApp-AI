"""Microsoft Teams through an incoming webhook. Recipients are the webhook URLs."""

from collections.abc import Sequence

import httpx

from cashapp.services.notifications.channel import ChannelName, ChannelSendError


class TeamsWebhookChannel:
    name: ChannelName = "teams"

    def __init__(
        self, client: httpx.AsyncClient | None = None, *, timeout_seconds: float = 10.0
    ) -> None:
        self._client = client
        self._timeout = timeout_seconds

    async def send(
        self,
        recipients: Sequence[str],
        subject: str,
        body_text: str,
        body_html: str | None,
    ) -> None:
        payload = {"text": f"**{subject}**\n\n{body_text}"}
        failures: list[str] = []
        for url in recipients:
            try:
                response = await self._post(url, payload)
            except httpx.HTTPError as exc:
                failures.append(type(exc).__name__)
                continue
            if not response.is_success:
                failures.append(f"HTTP {response.status_code}")
        if failures:
            # Never the URL: it is a secret.
            raise ChannelSendError(
                "teams", f"{len(failures)} of {len(recipients)} webhooks failed: {failures[0]}"
            )

    async def _post(self, url: str, payload: dict[str, str]) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(url, json=payload, timeout=self._timeout)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(url, json=payload)
