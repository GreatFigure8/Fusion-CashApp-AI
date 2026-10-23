"""Builds `McpFusionClient`s from `RuntimeSettings`. The only module in the package that reads them.

A client composes the process's shared `McpClient` (reads and REST writes) with a per-pod
`SoapTransport` (receipt apply and unapply). A pod password is resolved from Vault on each
request, never held.
"""

from __future__ import annotations

import httpx

from cashapp.data.engine import create_engine
from cashapp.data.uow import UowFactory, make_uow_factory
from cashapp.integrations.fusion.guard import WriteGuard
from cashapp.integrations.fusion.mcp_client import McpFusionClient, McpFusionOptions
from cashapp.integrations.fusion.soap import SoapOptions, SoapTransport
from cashapp.integrations.mcp.client import McpClient
from cashapp.integrations.mcp.factory import build_mcp_client
from cashapp.integrations.mcp.settings import McpConnection, load_connection
from cashapp.services.runtime_settings import RuntimeSettings


class FusionClientFactory:
    def __init__(
        self,
        runtime: RuntimeSettings,
        mcp: McpClient,
        *,
        options: McpFusionOptions = McpFusionOptions(),  # noqa: B008 - frozen value object
        soap_options: SoapOptions = SoapOptions(),  # noqa: B008 - frozen value object
        soap_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._runtime = runtime
        self._mcp = mcp
        self._options = options
        self._soap_options = soap_options
        self._soap_transport = soap_transport

    def for_pod(self, name: str | None = None) -> McpFusionClient:
        fusion = self._runtime.fusion()
        key = (name or fusion.default_pod).lower()
        pod = fusion.pods.get(key)
        if pod is None:
            raise KeyError(
                f"unknown Fusion pod '{key}'; known pods: {', '.join(sorted(fusion.pods))}"
            )
        runtime = self._runtime

        async def connection() -> McpConnection:
            return await load_connection(runtime)

        return McpFusionClient(
            pod_name=key,
            mcp=self._mcp,
            connection=connection,
            guard=WriteGuard.from_runtime(runtime, key),
            soap_transport=SoapTransport(
                pod_name=key,
                pod=pod,
                password=lambda: runtime.secret(pod.password_ref),
                options=self._soap_options,
                transport=self._soap_transport,
            ),
            source=pod.mcp_source,
            options=self._options,
        )


def standalone_factory(runtime: RuntimeSettings) -> FusionClientFactory:
    """For command-line tools: builds its own engine and MCP client over `runtime`.

    The tools exit when they finish, so nothing here is closed. It needs the ATP settings because
    the MCP call log lives in the database.
    """
    atp = runtime.settings.atp
    options = {k: v for k, v in atp.engine_kwargs().items() if k != "pool_pre_ping"}
    engine = create_engine(atp.url().render_as_string(hide_password=False), **options)
    uow_factory = make_uow_factory(engine)
    mcp = build_mcp_client(runtime, uow_factory=uow_factory)
    return FusionClientFactory(runtime, mcp)


def build_fusion_client(
    runtime: RuntimeSettings,
    *,
    uow_factory: UowFactory,
    mcp: McpClient | None = None,
) -> McpFusionClient:
    """The default-pod client for the worker/API container (the caller awaits `aclose()`).

    Pass the process's shared `mcp` client; without one a client of its own is built.
    """
    shared = mcp if mcp is not None else build_mcp_client(runtime, uow_factory=uow_factory)
    return FusionClientFactory(runtime, shared).for_pod()
