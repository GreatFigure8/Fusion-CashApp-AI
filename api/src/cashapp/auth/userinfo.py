"""Groups from the identity provider's userinfo endpoint.

OCI IAM identity domains keep the group list out of the access token. The API asks the provider
itself, with the caller's own access token, so the answer is the provider's and not the web
app's. The result is cached briefly per token; any failure yields no groups, which means no role.
"""

import hashlib
import logging
import time
from collections.abc import Mapping
from typing import Any, Final

import httpx

from cashapp.auth.tokens import extract_groups

logger = logging.getLogger(__name__)

CACHE_SECONDS: Final = 300.0
HTTP_TIMEOUT_SECONDS: Final = 5.0
MAX_CACHE_ENTRIES: Final = 512


class UserInfoGroups:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._cache: dict[str, tuple[float, frozenset[str]]] = {}

    async def groups(self, url: str, token: str, claim: str) -> frozenset[str]:
        key = hashlib.sha256(token.encode()).hexdigest()
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        found = await self._fetch(url, token, claim)
        if found is not None:
            if len(self._cache) >= MAX_CACHE_ENTRIES:
                self._cache.clear()
            self._cache[key] = (now + CACHE_SECONDS, found)
        return found or frozenset()

    async def _fetch(self, url: str, token: str, claim: str) -> frozenset[str] | None:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            if self._client is not None:
                response = await self._client.get(url, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                    response = await client.get(url, headers=headers)
            response.raise_for_status()
            body: Mapping[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("userinfo unavailable", extra={"reason": type(exc).__name__})
            return None
        return extract_groups(body, claim)
