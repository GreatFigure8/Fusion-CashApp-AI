"""Secret resolution: a secret OCID becomes a value at the moment it is used.

Three `SecretSource` implementations exist: the encrypted database store (the default, see
`cashapp.services.app_secrets`), OCI Vault, and a value map (local and tests).
`SecretResolver` caches resolved values for a short TTL and never logs them. Errors name the
reference (a secret name or OCID, which is not secret), never a value.
"""

import asyncio
import base64
import os
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from pydantic import SecretStr

VAULT_PREFIX = "vault:"
VAULT_REGION = "us-ashburn-1"


class SecretResolutionError(Exception):
    """A secret reference could not be resolved."""

    def __init__(self, ref: str, reason: str = "not found") -> None:
        super().__init__(f"Could not resolve secret reference {ref}: {reason}")
        self.ref = ref


class SecretCipher:
    """AES-256-GCM over a master key that lives outside the database (a bootstrap setting).

    The secret's name is bound in as associated data, so a ciphertext copied onto another name
    does not decrypt.
    """

    NONCE_BYTES = 12

    def __init__(self, master_key: str) -> None:
        try:
            raw = base64.b64decode(master_key, validate=True)
        except ValueError:
            raise SecretResolutionError("secrets.master_key", "not base64") from None
        if len(raw) != 32:
            raise SecretResolutionError("secrets.master_key", "must decode to 32 bytes")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aead = AESGCM(raw)

    def encrypt(self, name: str, value: str) -> bytes:
        nonce = os.urandom(self.NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, value.encode("utf-8"), name.encode("utf-8"))

    def decrypt(self, name: str, blob: bytes) -> str:
        nonce, body = blob[: self.NONCE_BYTES], blob[self.NONCE_BYTES :]
        try:
            return self._aead.decrypt(nonce, body, name.encode("utf-8")).decode("utf-8")
        except Exception:
            # Only the name is reported: a wrong master key and a damaged row look the same.
            raise SecretResolutionError(name, "could not decrypt") from None


class SecretsClientLike(Protocol):
    """The slice of `oci.secrets.SecretsClient` that is used."""

    def get_secret_bundle(self, secret_id: str, *, stage: str = ...) -> Any: ...


class SecretSource(Protocol):
    async def resolve(self, ref: str) -> str:
        """Return the secret value for `ref` (the secret OCID, prefix already stripped)."""
        ...


class VaultSecretSource:
    """Reads the CURRENT version of a secret from OCI Vault."""

    def __init__(self, client: SecretsClientLike) -> None:
        self._client = client

    @classmethod
    def from_signer(cls, signer: Any) -> "VaultSecretSource":
        """The signer comes from `settings.oci_signer`, which owns the environment reads."""
        import oci  # pyright: ignore[reportMissingTypeStubs]

        sdk: Any = oci
        client: SecretsClientLike = sdk.secrets.SecretsClient(
            config={"region": VAULT_REGION}, signer=signer
        )
        return cls(client)

    async def resolve(self, ref: str) -> str:
        try:
            response = await asyncio.to_thread(
                self._client.get_secret_bundle, secret_id=ref, stage="CURRENT"
            )
            content: str = response.data.secret_bundle_content.content
            return base64.b64decode(content).decode("utf-8")
        except SecretResolutionError:
            raise
        except Exception as exc:
            # Only the exception type is kept: SDK messages can echo request details.
            raise SecretResolutionError(ref, type(exc).__name__) from None


class EnvSecretSource:
    """Resolves references from a mapping of OCID to value (local development and tests)."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values: Mapping[str, str] = values

    async def resolve(self, ref: str) -> str:
        try:
            return self._values[ref]
        except KeyError:
            raise SecretResolutionError(ref) from None


def is_secret_ref(value: object) -> bool:
    return (
        isinstance(value, str) and value.startswith(VAULT_PREFIX) and len(value) > len(VAULT_PREFIX)
    )


def collect_secret_refs(data: Any) -> set[str]:
    """Every distinct secret OCID referenced anywhere in a nested structure."""
    if isinstance(data, str):
        return {data.removeprefix(VAULT_PREFIX)} if is_secret_ref(data) else set()
    if isinstance(data, dict):
        found: set[str] = set()
        for item in data.values():  # pyright: ignore[reportUnknownVariableType]
            found |= collect_secret_refs(item)
        return found
    if isinstance(data, list | tuple):
        found = set()
        for item in data:  # pyright: ignore[reportUnknownVariableType]
            found |= collect_secret_refs(item)
        return found
    return set()


def _substitute(data: Any, values: Mapping[str, str]) -> Any:
    if isinstance(data, str):
        return values[data.removeprefix(VAULT_PREFIX)] if is_secret_ref(data) else data
    if isinstance(data, dict):
        return {key: _substitute(item, values) for key, item in data.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(data, list | tuple):
        return [_substitute(item, values) for item in data]  # pyright: ignore[reportUnknownVariableType]
    return data


async def resolve_secret_refs(data: dict[str, Any], source: SecretSource) -> dict[str, Any]:
    """Return a new dict with every `vault:` reference replaced by its value.

    Each distinct reference is resolved once, concurrently. The input is left untouched.
    """
    refs = sorted(collect_secret_refs(data))
    if not refs:
        return _substitute(data, {})  # still a deep copy
    values = await asyncio.gather(*(source.resolve(ref) for ref in refs))
    return _substitute(data, dict(zip(refs, values, strict=True)))


class SecretResolver:
    """Resolves a secret OCID at use, with a TTL cache and one in-flight read per reference."""

    def __init__(
        self,
        source: SecretSource,
        *,
        ttl_seconds: float = 300.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._source = source
        self._ttl = ttl_seconds
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._cache: dict[str, tuple[float, SecretStr]] = {}
        self._lock = asyncio.Lock()

    def _cached(self, ref: str) -> SecretStr | None:
        entry = self._cache.get(ref)
        if entry is None:
            return None
        stamped, value = entry
        return value if 0 <= self._clock() - stamped < self._ttl else None

    async def resolve(self, ref: str) -> SecretStr:
        cached = self._cached(ref)
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._cached(ref)
            if cached is not None:
                return cached
            value = SecretStr(await self._source.resolve(ref))
            self._cache[ref] = (self._clock(), value)
            return value

    def invalidate(self, ref: str | None = None) -> None:
        """Forget one reference, or all of them (after a rotation or a changed ref)."""
        if ref is None:
            self._cache.clear()
        else:
            self._cache.pop(ref, None)
