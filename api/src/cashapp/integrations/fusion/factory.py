"""Builds `HttpFusionClient`s from `RuntimeSettings`. The only module in the package that reads
them. A pod password is resolved from Vault on each request, never held."""

from __future__ import annotations

import httpx

from cashapp.integrations.fusion.client import FusionClient, HttpFusionClient
from cashapp.integrations.fusion.guard import WriteGuard
from cashapp.integrations.fusion.transport import FusionClientOptions
from cashapp.services.runtime_settings import RuntimeSettings


class FusionClientFactory:
    def __init__(
        self,
        runtime: RuntimeSettings,
        *,
        options: FusionClientOptions = FusionClientOptions(),  # noqa: B008 - frozen value object
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._runtime = runtime
        self._options = options
        self._transport = transport

    def for_pod(self, name: str | None = None) -> HttpFusionClient:
        fusion = self._runtime.fusion()
        key = (name or fusion.default_pod).lower()
        pod = fusion.pods.get(key)
        if pod is None:
            raise KeyError(
                f"unknown Fusion pod '{key}'; known pods: {', '.join(sorted(fusion.pods))}"
            )
        return HttpFusionClient(
            pod_name=key,
            pod=pod,
            password=lambda: self._runtime.secret(pod.password_ref),
            guard=WriteGuard.from_runtime(self._runtime, key),
            relationships_report_path=self._runtime.relationships_report_path,
            options=self._options,
            transport=self._transport,
        )


def build_fusion_client(runtime: RuntimeSettings) -> FusionClient:
    """The default-pod client for the worker/API container (the caller awaits `aclose()`)."""
    return FusionClientFactory(runtime).for_pod()
