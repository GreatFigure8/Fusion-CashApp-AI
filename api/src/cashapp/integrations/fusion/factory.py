"""Builds `HttpFusionClient`s from `Settings`. The only module in the package that reads them."""

from __future__ import annotations

import httpx

from cashapp.integrations.fusion.client import FusionClient, HttpFusionClient
from cashapp.integrations.fusion.guard import WriteGuard
from cashapp.integrations.fusion.transport import FusionClientOptions
from cashapp.settings import Settings


class FusionClientFactory:
    def __init__(
        self,
        settings: Settings,
        *,
        options: FusionClientOptions = FusionClientOptions(),  # noqa: B008 - frozen value object
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._options = options
        self._transport = transport

    def for_pod(self, name: str | None = None) -> HttpFusionClient:
        fusion = self._settings.fusion
        key = (name or fusion.default_pod).lower()
        pod = fusion.pods.get(key)
        if pod is None:
            raise KeyError(
                f"unknown Fusion pod '{key}'; known pods: {', '.join(sorted(fusion.pods))}"
            )
        return HttpFusionClient(
            pod_name=key,
            pod=pod,
            guard=WriteGuard.from_settings(self._settings, key),
            relationships_report_path=fusion.relationships_report_path,
            options=self._options,
            transport=self._transport,
        )


def build_fusion_client(settings: Settings) -> FusionClient:
    """The default-pod client for the worker/API container (the caller awaits `aclose()`)."""
    return FusionClientFactory(settings).for_pod()
