"""Builds the process's `McpClient` from `RuntimeSettings` and a call recorder."""

from __future__ import annotations

from cashapp.data.uow import UowFactory
from cashapp.integrations.mcp.client import StreamableHttpMcpClient
from cashapp.integrations.mcp.recorder import DbMcpCallRecorder, McpCallRecorder
from cashapp.secrets import SecretSource
from cashapp.services.runtime_settings import RuntimeSettings

__all__ = ["RuntimeSecretSource", "build_mcp_client"]


class RuntimeSecretSource:
    """Resolves Vault references through `RuntimeSettings` (one secret source per process)."""

    def __init__(self, runtime: RuntimeSettings) -> None:
        self._runtime = runtime

    async def resolve(self, ref: str) -> str:
        return (await self._runtime.secret(ref)).get_secret_value()


def build_mcp_client(
    runtime: RuntimeSettings,
    *,
    uow_factory: UowFactory | None = None,
    recorder: McpCallRecorder | None = None,
    secrets: SecretSource | None = None,
) -> StreamableHttpMcpClient:
    """The shared MCP client. Give it a `uow_factory` (or a `recorder`) so calls are logged.

    The `mcp.*` keys are read through `runtime` (hot: a changed value is seen on the next call).
    """
    if recorder is None:
        if uow_factory is None:
            raise ValueError("build_mcp_client needs a uow_factory or a recorder")
        recorder = DbMcpCallRecorder(uow_factory)
    return StreamableHttpMcpClient(
        runtime, secrets if secrets is not None else RuntimeSecretSource(runtime), recorder
    )
