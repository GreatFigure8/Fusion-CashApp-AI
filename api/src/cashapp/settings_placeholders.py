"""Fake values for tools that must run with no environment, Vault or database.

Used by `openapi_dump` (the contract is generated offline) and by the test support, so the
placeholder values exist exactly once. `placeholder_settings` is the bootstrap model;
`placeholder_config_values` holds a fake value for every key in `REQUIRED_KEYS`.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import JsonValue

from cashapp.domain import config_keys as ck
from cashapp.settings import Settings

FAKE_SECRET_OCID_PREFIX = "ocid1.vaultsecret.oc1.iad."  # noqa: S105 - a fake reference


def fake_secret_ocid(name: str) -> str:
    """An OCID-shaped fake that satisfies `SecretRef` (a local-values map resolves it)."""
    return f"{FAKE_SECRET_OCID_PREFIX}{name.lower().replace('_', '')}fakefakefakefake"


def _base() -> dict[str, Any]:
    return {
        "env": "local",
        "atp": {
            "dsn": "fake_high",
            "user": "CASHAPP_TEST",
            "password": "fake-atp-password",
        },
    }


def _merge(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = _merge(current, value)  # pyright: ignore[reportUnknownArgumentType]
        else:
            merged[key] = value  # scalars and model instances replace
    return merged


def placeholder_settings(**overrides: Any) -> Settings:
    """Overrides are deep-merged per group (dict) or replace the group (model instance).

    Built with `model_validate`, so it reads no environment variable, `.env` file or Vault secret.
    """
    return Settings.model_validate(_merge(_base(), overrides))


def placeholder_config_values() -> dict[str, JsonValue]:
    """A fake value for every required DB key, in the JSON form the database stores."""
    return {
        ck.STREAMING_BOOTSTRAP_SERVERS.name: "localhost:9092",
        ck.STREAMING_SASL_USERNAME.name: "fake-tenancy/fake-user/fake-pool",
        ck.STREAMING_SASL_PASSWORD_REF.name: fake_secret_ocid("streaming"),
        ck.STREAMING_CONSUMER_GROUP.name: "cashapp-test",
        ck.OBJECT_STORAGE_NAMESPACE.name: "fakens",
        ck.OBJECT_STORAGE_BUCKET.name: "cashapp-test",
        ck.ANTHROPIC_API_KEY_REF.name: fake_secret_ocid("anthropic"),
        ck.OCI_GENAI_COMPARTMENT_OCID.name: "ocid1.compartment.oc1..fake",
        ck.OCI_GENAI_DEDICATED_ENDPOINT_OCID.name: "ocid1.generativeaiendpoint.oc1.iad.fake",
        ck.IDENTITY_ISSUER.name: "https://identity.example.test",
        ck.IDENTITY_JWKS_URL.name: "https://identity.example.test/.well-known/jwks.json",
        ck.IDENTITY_AUDIENCE.name: "cashapp-api",
        ck.FUSION_PODS.name: {
            "dev": {
                "base_url": "https://dev.fa.example.test",
                "username": "fake-user",
                "password_ref": fake_secret_ocid("fusiondev"),
            }
        },
        ck.FUSION_DEFAULT_POD.name: "dev",
        ck.FUSION_RELATIONSHIPS_REPORT_PATH.name: "/Custom/CashApp/Relationships.xdo",
        ck.INTAKE_DROP_FOLDER.name: "./drop",
    }
