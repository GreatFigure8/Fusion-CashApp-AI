"""Test settings: `make_settings` builds a valid local `Settings` without reading env or files."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from cashapp.settings import Settings


def _base() -> dict[str, Any]:
    return {
        "env": "local",
        "atp": {
            "dsn": "fake_high",
            "user": "CASHAPP_TEST",
            "password": "fake-atp-password",
        },
        "streaming": {
            "bootstrap_servers": "localhost:9092",
            "sasl_username": "fake-tenancy/fake-user/fake-pool",
            "sasl_password": "fake-streaming-token",
            "consumer_group": "cashapp-test",
        },
        "object_storage": {"namespace": "fakens", "bucket": "cashapp-test"},
        "anthropic": {"api_key": "fake-anthropic-key"},
        "oci_genai": {
            "compartment_ocid": "ocid1.compartment.oc1..fake",
            "dedicated_endpoint_ocid": "ocid1.generativeaiendpoint.oc1.iad.fake",
        },
        "identity": {
            "issuer": "https://identity.example.test",
            "jwks_url": "https://identity.example.test/.well-known/jwks.json",
            "audience": "cashapp-api",
        },
        "fusion": {
            "pods": {
                "dev": {
                    "base_url": "https://dev.fa.example.test",
                    "username": "fake-user",
                    "password": "fake-fusion-password",
                }
            },
            "default_pod": "dev",
            "relationships_report_path": "/Custom/CashApp/Relationships.xdo",
        },
        "intake": {"drop_folder": "./drop"},
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


def make_settings(**overrides: Any) -> Settings:
    """Overrides are deep-merged per group (dict) or replace the group (model instance)."""
    return Settings.model_validate(_merge(_base(), overrides))


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No CASHAPP_* variable and no stray .env: loaders see a blank environment."""
    for name in [n for n in os.environ if n.upper().startswith("CASHAPP_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
