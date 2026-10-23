"""Test settings: `make_settings` builds a valid local bootstrap `Settings` without reading env or
files; `runtime_settings_for` builds a `RuntimeSettings` over an in-memory config store."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from cashapp.domain.clock import SystemClock
from cashapp.secrets import SecretResolver
from cashapp.services.config import ConfigStore, RuntimeConfig, StoredSetting
from cashapp.services.runtime_settings import RuntimeSettings
from cashapp.settings import Settings
from cashapp.settings_placeholders import placeholder_config_values, placeholder_settings


def make_settings(**overrides: Any) -> Settings:
    """Overrides are deep-merged per group (dict) or replace the group (model instance)."""
    return placeholder_settings(**overrides)


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No CASHAPP_* variable and no stray .env: loaders see a blank environment."""
    for name in [n for n in os.environ if n.upper().startswith("CASHAPP_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


class MemoryConfigStore:
    """A `ConfigStore` over a dict of key to stored JSON value."""

    def __init__(self, values: Mapping[str, JsonValue]) -> None:
        self.values = dict(values)

    async def load(self) -> Mapping[str, StoredSetting]:
        now = SystemClock().now()
        return {
            name: StoredSetting(name, value, 1, now, "test") for name, value in self.values.items()
        }


class FakeSecretSource:
    """Resolves any reference to a fixed fake value."""

    def __init__(self, value: str = "fake-secret-value") -> None:
        self._value = value

    async def resolve(self, ref: str) -> str:
        return self._value


def runtime_settings_for(
    values: Mapping[str, JsonValue] | None = None,
    *,
    env: str = "local",
    store: ConfigStore | None = None,
) -> RuntimeSettings:
    """An unstarted `RuntimeSettings`; `await runtime.start()` pins the restart-required keys.

    `values` are layered over `placeholder_config_values()` (every required key present).
    """
    merged: dict[str, JsonValue] = {**placeholder_config_values(), **(values or {})}
    config = RuntimeConfig(store if store is not None else MemoryConfigStore(merged))
    return RuntimeSettings(
        config, SecretResolver(FakeSecretSource()), env=env, settings=make_settings()
    )
