"""Test support for authentication: a fake identity domain (RSA key + JWKS) and principals."""

import json
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import httpx
import jwt
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from jwt.algorithms import RSAAlgorithm

from cashapp.auth.deps import current_principal
from cashapp.domain.principal import Principal, Role

TEST_ISSUER = "https://identity.test.example"
TEST_AUDIENCE = "cashapp-api"
TEST_JWKS_URL = f"{TEST_ISSUER}/admin/v1/SigningCert/jwk"
TEST_KID = "test-key-1"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks(*, kid: str = TEST_KID, key: rsa.RSAPrivateKey | None = None) -> dict[str, Any]:
    public = (key or _KEY).public_key()
    jwk: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(public))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


def mock_jwks(respx_mock: respx.MockRouter, *, url: str = TEST_JWKS_URL) -> respx.Route:
    return respx_mock.get(url).mock(return_value=httpx.Response(200, json=jwks()))


def mint_token(
    groups: Sequence[str] = (),
    *,
    kid: str = TEST_KID,
    key: rsa.RSAPrivateKey | None = None,
    expires_in: int = 300,
    **claims: Any,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "sub": "user@test",
        "user_displayname": "Test User",
        "email": "user@test.example",
        "iat": now,
        "exp": now + expires_in,
        "groups": list(groups),
    }
    payload.update(claims)
    return jwt.encode(payload, key or _KEY, algorithm="RS256", headers={"kid": kid})


def make_principal(
    roles: Iterable[Role] = (Role.VIEWER,),
    *,
    subject: str = "user@test",
    groups: Iterable[str] = (),
) -> Principal:
    return Principal.from_roles(
        subject=subject,
        display_name="Test User",
        email="user@test.example",
        groups=groups,
        roles=roles,
    )


@contextmanager
def override_principal(app: FastAPI, principal: Principal) -> Iterator[None]:
    async def _principal() -> Principal:
        return principal

    app.dependency_overrides[current_principal] = _principal
    try:
        yield
    finally:
        app.dependency_overrides.pop(current_principal, None)
