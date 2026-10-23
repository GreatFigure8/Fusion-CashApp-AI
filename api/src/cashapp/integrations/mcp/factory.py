"""Builds the process's `McpClient` from settings, runtime config and a call recorder."""

from __future__ import annotations

from cashapp.data.uow import UowFactory
from cashapp.integrations.mcp.client import StreamableHttpMcpClient
from cashapp.integrations.mcp.recorder import DbMcpCallRecorder, McpCallRecorder
from cashapp.integrations.mcp.settings import ConfigReader
from cashapp.secrets import EnvSecretSource, SecretSource, VaultSecretSource
from cashapp.settings import Settings

__all__ = ["build_mcp_client", "default_secret_source"]


def default_secret_source(settings: Settings) -> SecretSource:
    """The environment locally, OCI Vault everywhere else (the same rule `load_settings` uses)."""
    return EnvSecretSource() if settings.env == "local" else VaultSecretSource.from_environment()


def build_mcp_client(
    settings: Settings,
    config: ConfigReader,
    *,
    uow_factory: UowFactory | None = None,
    recorder: McpCallRecorder | None = None,
    secrets: SecretSource | None = None,
) -> StreamableHttpMcpClient:
    """The shared MCP client. Give it a `uow_factory` (or a `recorder`) so calls are logged."""
    if recorder is None:
        if uow_factory is None:
            raise ValueError("build_mcp_client needs a uow_factory or a recorder")
        recorder = DbMcpCallRecorder(uow_factory)
    return StreamableHttpMcpClient(
        config, secrets if secrets is not None else default_secret_source(settings), recorder
    )
