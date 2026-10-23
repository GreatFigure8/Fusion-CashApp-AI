"""Builds `McpFusionClient`s. The only module in the package that reads `Settings`.

A client composes the process's shared `McpClient` (reads and REST writes) with a per-pod
`SoapTransport` (receipt apply and unapply, credentials from Vault via `Settings`).
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
from cashapp.integrations.mcp.settings import ConfigReader, McpConnection, load_connection
from cashapp.services.config import build_runtime_config
from cashapp.settings import Settings


class FusionClientFactory:
    def __init__(
        self,
        settings: Settings,
        mcp: McpClient,
        config: ConfigReader,
        *,
        options: McpFusionOptions = McpFusionOptions(),  # noqa: B008 - frozen value object
        soap_options: SoapOptions = SoapOptions(),  # noqa: B008 - frozen value object
        soap_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._mcp = mcp
        self._config = config
        self._options = options
        self._soap_options = soap_options
        self._soap_transport = soap_transport

    def for_pod(self, name: str | None = None) -> McpFusionClient:
        fusion = self._settings.fusion
        key = (name or fusion.default_pod).lower()
        pod = fusion.pods.get(key)
        if pod is None:
            raise KeyError(
                f"unknown Fusion pod '{key}'; known pods: {', '.join(sorted(fusion.pods))}"
            )
        config = self._config

        async def connection() -> McpConnection:
            return await load_connection(config)

        return McpFusionClient(
            pod_name=key,
            mcp=self._mcp,
            connection=connection,
            guard=WriteGuard.from_settings(self._settings, key),
            soap_transport=SoapTransport(
                pod_name=key,
                pod=pod,
                options=self._soap_options,
                transport=self._soap_transport,
            ),
            source=pod.mcp_source,
            options=self._options,
        )


def standalone_factory(settings: Settings) -> FusionClientFactory:
    """For command-line tools: builds its own engine, runtime config and MCP client.

    The tools exit when they finish, so nothing here is closed. It needs the ATP settings because
    the MCP connection (`mcp.*`) and the call log live in the database.
    """
    atp = settings.atp
    options = {k: v for k, v in atp.engine_kwargs().items() if k != "pool_pre_ping"}
    engine = create_engine(atp.url().render_as_string(hide_password=False), **options)
    uow_factory = make_uow_factory(engine)
    config = build_runtime_config(uow_factory)
    mcp = build_mcp_client(settings, config, uow_factory=uow_factory)
    return FusionClientFactory(settings, mcp, config)


def build_fusion_client(
    settings: Settings,
    config: ConfigReader,
    *,
    uow_factory: UowFactory,
    mcp: McpClient | None = None,
) -> McpFusionClient:
    """The default-pod client for the worker/API container (the caller awaits `aclose()`).

    Pass the process's shared `mcp` client; without one a client of its own is built.
    """
    shared = mcp if mcp is not None else build_mcp_client(settings, config, uow_factory=uow_factory)
    return FusionClientFactory(settings, shared, config).for_pod()
