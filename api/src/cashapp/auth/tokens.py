"""Access-token validation against the identity domain's JWKS."""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import httpx
import jwt
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWKClientError

from cashapp.api.errors import ApiError

if TYPE_CHECKING:
    from cashapp.settings import IdentitySettings

logger = logging.getLogger(__name__)

_ALGORITHMS = ["RS256"]
_GROUP_NAME_KEYS = ("name", "display")
_DISPLAY_NAME_KEYS = ("user_displayname", "name")
_EMAIL_KEYS = ("email", "user_email")


class TokenError(Exception):
    """Internal reason a token was refused; mapped to ApiError at the edge."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def extract_groups(raw: Mapping[str, Any], claim: str) -> frozenset[str]:
    """Groups from `claim`: a list of strings or of objects with name/display.

    Unverified against a live identity domain; both shapes have been seen.
    """
    value = raw.get(claim)
    if not isinstance(value, list):
        return frozenset()
    groups: set[str] = set()
    entries = cast("list[Any]", value)
    for entry in entries:
        if isinstance(entry, str):
            if entry:
                groups.add(entry)
        elif isinstance(entry, Mapping):
            as_map = cast("Mapping[str, Any]", entry)
            for key in _GROUP_NAME_KEYS:
                name = as_map.get(key)
                if isinstance(name, str) and name:
                    groups.add(name)
                    break
    return frozenset(groups)


def _first_str(raw: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return None


@dataclass(frozen=True, slots=True)
class Claims:
    subject: str
    issuer: str
    audience: tuple[str, ...]
    expires_at: datetime
    display_name: str
    email: str | None
    raw: Mapping[str, Any]

    def groups(self, claim: str) -> frozenset[str]:
        return extract_groups(self.raw, claim)


class HttpxJWKClient(PyJWKClient):
    """PyJWKClient whose fetch goes through httpx: bounded timeout, mockable with respx."""

    def __init__(
        self, uri: str, *, cache_seconds: int = 300, http_timeout_seconds: float = 5.0
    ) -> None:
        super().__init__(uri, lifespan=cache_seconds)
        self._http_timeout = http_timeout_seconds

    def fetch_data(self) -> Any:
        try:
            with httpx.Client(timeout=self._http_timeout) as client:
                response = client.get(self.uri)
                response.raise_for_status()
                jwk_set: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PyJWKClientConnectionError("JWKS fetch failed") from exc
        if self.jwk_set_cache is not None:
            self.jwk_set_cache.put(jwk_set)
        return jwk_set


class TokenValidator:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str | Sequence[str],
        jwks_url: str,
        leeway_seconds: int = 60,
        jwks_cache_seconds: int = 300,
        http_timeout_seconds: float = 5.0,
    ) -> None:
        self._issuer = issuer
        self._audience = audience if isinstance(audience, str) else list(audience)
        self._leeway = leeway_seconds
        self._jwks = HttpxJWKClient(
            jwks_url,
            cache_seconds=jwks_cache_seconds,
            http_timeout_seconds=http_timeout_seconds,
        )

    @classmethod
    def from_settings(cls, identity: "IdentitySettings") -> "TokenValidator":
        return cls(issuer=identity.issuer, audience=identity.audience, jwks_url=identity.jwks_url)

    async def validate(self, token: str) -> Claims:
        try:
            raw = await asyncio.to_thread(self._decode, token)
        except PyJWKClientConnectionError as exc:
            logger.warning("token refused", extra={"reason": "jwks_unreachable"})
            raise ApiError(503, "identity_unavailable", "Identity provider is unavailable") from exc
        except (jwt.PyJWTError, PyJWKClientError, TokenError) as exc:
            reason = exc.reason if isinstance(exc, TokenError) else type(exc).__name__
            logger.warning("token refused", extra={"reason": reason})
            raise ApiError(401, "invalid_token", "Invalid or expired access token") from exc
        return _to_claims(raw)

    def _decode(self, token: str) -> dict[str, Any]:
        key = self._jwks.get_signing_key_from_jwt(token)
        decoded: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=_ALGORITHMS,
            audience=self._audience,
            issuer=self._issuer,
            leeway=self._leeway,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
        return decoded


def _to_claims(raw: dict[str, Any]) -> Claims:
    aud = raw["aud"]
    audience = (aud,) if isinstance(aud, str) else tuple(str(a) for a in aud)
    subject = str(raw["sub"])
    return Claims(
        subject=subject,
        issuer=str(raw["iss"]),
        audience=audience,
        expires_at=datetime.fromtimestamp(float(raw["exp"]), tz=UTC),
        display_name=_first_str(raw, _DISPLAY_NAME_KEYS) or subject,
        email=_first_str(raw, _EMAIL_KEYS),
        raw=raw,
    )
