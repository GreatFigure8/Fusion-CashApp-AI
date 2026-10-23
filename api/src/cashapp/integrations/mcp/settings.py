"""The MCP connection as one frozen value, read from the `mcp.*` config keys.

`ConfigReader` is the slice of the runtime configuration this package needs: an async `get(key)`.
`RuntimeConfig` and `RuntimeSettings` both satisfy it, so the client follows whichever the process
holds. Reading is hot: a changed value is seen on the next call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cashapp.domain import config_keys as ck
from cashapp.domain.config_keys import ConfigKey

__all__ = ["ConfigReader", "McpConnection", "load_connection"]


class ConfigReader(Protocol):
    async def get[T](self, key: ConfigKey[T]) -> T: ...


@dataclass(frozen=True, slots=True)
class McpConnection:
    server_url: str
    token_url: str
    client_id: str
    client_secret_ref: str | None
    scope: str
    fusion_source: str
    timeout_s: int
    max_rows: int

    @property
    def configured(self) -> bool:
        return bool(
            self.server_url and self.token_url and self.client_id and self.client_secret_ref
        )

    @property
    def identity(self) -> tuple[str, str, str, str | None, str]:
        """What forces a reconnect when it changes (the rest is read per call)."""
        return (
            self.server_url,
            self.token_url,
            self.client_id,
            self.client_secret_ref,
            self.scope,
        )


async def load_connection(config: ConfigReader) -> McpConnection:
    return McpConnection(
        server_url=await config.get(ck.MCP_SERVER_URL),
        token_url=await config.get(ck.MCP_TOKEN_URL),
        client_id=await config.get(ck.MCP_CLIENT_ID),
        client_secret_ref=await config.get(ck.MCP_CLIENT_SECRET_REF),
        scope=await config.get(ck.MCP_SCOPE),
        fusion_source=await config.get(ck.MCP_FUSION_SOURCE),
        timeout_s=await config.get(ck.MCP_TIMEOUT_SECONDS),
        max_rows=await config.get(ck.MCP_MAX_ROWS),
    )
