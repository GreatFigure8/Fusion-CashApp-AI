"""OAuth `client_credentials` tokens for the MCP server.

The client secret is resolved from OCI Vault at use through `cashapp.secrets`; the token is
cached until 60 seconds before it expires and refreshed by one caller at a time. Neither the
secret, the token nor the identity provider's response body is ever logged or put in an error.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.mcp.errors import McpError
from cashapp.integrations.mcp.settings import McpConnection
from cashapp.secrets import VAULT_PREFIX, SecretResolutionError, SecretSource

__all__ = ["ClientCredentialsTokenProvider"]

_EXPIRY_MARGIN_S = 60.0
_DEFAULT_LIFETIME_S = 300.0


@dataclass(slots=True)
class _Cached:
    key: tuple[str, str, str | None, str]
    token: str
    expires_at: float


class ClientCredentialsTokenProvider:
    def __init__(
        self,
        secrets: SecretSource,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._secrets = secrets
        self._transport = transport
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._cached: _Cached | None = None

    def invalidate(self) -> None:
        """Forget the cached token (after a 401); the next call fetches a fresh one."""
        self._cached = None

    def _valid(self, key: tuple[str, str, str | None, str]) -> str | None:
        cached = self._cached
        if cached is not None and cached.key == key and self._monotonic() < cached.expires_at:
            return cached.token
        return None

    async def get_token(self, conn: McpConnection) -> str:
        key = (conn.token_url, conn.client_id, conn.client_secret_ref, conn.scope)
        token = self._valid(key)
        if token is not None:
            return token
        async with self._lock:
            token = self._valid(key)
            if token is not None:
                return token
            return await self._fetch(conn, key)

    async def _fetch(self, conn: McpConnection, key: tuple[str, str, str | None, str]) -> str:
        if not conn.configured or conn.client_secret_ref is None:
            raise McpError(ErrorCode.FUSION_FAULT, "the MCP connection is not configured")
        try:
            secret = await self._secrets.resolve(conn.client_secret_ref.removeprefix(VAULT_PREFIX))
        except SecretResolutionError as exc:
            raise McpError(
                ErrorCode.FUSION_FAULT, "the MCP client secret could not be read from Vault"
            ) from exc
        try:
            async with httpx.AsyncClient(
                timeout=conn.timeout_s, transport=self._transport
            ) as client:
                response = await client.post(
                    conn.token_url,
                    auth=httpx.BasicAuth(conn.client_id, secret),
                    data={"grant_type": "client_credentials", "scope": conn.scope},
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise McpError(
                ErrorCode.FUSION_TRANSIENT, f"{type(exc).__name__} fetching the MCP token"
            ) from None
        if response.status_code >= 500:
            raise McpError(
                ErrorCode.FUSION_TRANSIENT, f"HTTP {response.status_code} from the token endpoint"
            )
        if response.status_code != 200:
            raise McpError(
                ErrorCode.FUSION_FAULT,
                f"HTTP {response.status_code} from the token endpoint (check the client id, "
                "secret and scope)",
                retryable=False,
            )
        try:
            body = response.json()
            token = str(body["access_token"])
            lifetime = float(body.get("expires_in", _DEFAULT_LIFETIME_S))
        except (ValueError, KeyError, TypeError, AttributeError):
            raise McpError(
                ErrorCode.FUSION_FAULT, "the token endpoint returned an unexpected response"
            ) from None
        self._cached = _Cached(
            key=key,
            token=token,
            expires_at=self._monotonic() + max(lifetime - _EXPIRY_MARGIN_S, 0.0),
        )
        return token
