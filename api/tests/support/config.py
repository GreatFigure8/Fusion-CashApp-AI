"""Test support: an in-memory config store and ready-made RuntimeConfig / ConfigSnapshot."""

import datetime
from collections.abc import Mapping
from typing import Any

from cashapp.domain.clock import Clock, SystemClock
from cashapp.services.config import (
    ConfigSnapshot,
    RuntimeConfig,
    StoredSetting,
    lookup_key,
    to_json,
    validate_value,
)


class InMemoryConfigStore:
    """Implements ConfigStore. Values are validated exactly as the real writer validates them."""

    def __init__(self, values: Mapping[str, object] | None = None) -> None:
        self._settings: dict[str, StoredSetting] = {}
        for name, value in (values or {}).items():
            self.set(name, value)

    def set(self, key: str, value: object) -> None:
        """Store `value` (unknown keys raise UnknownConfigKey) and bump its version."""
        registry_key = lookup_key(key)
        stored = to_json(registry_key, validate_value(registry_key, value))
        previous = self._settings.get(key)
        self._settings[key] = StoredSetting(
            key=key,
            value=stored,
            version=(previous.version if previous is not None else 0) + 1,
            updated_at=datetime.datetime.now(datetime.UTC),
            updated_by="test",
        )

    def settings(self) -> Mapping[str, StoredSetting]:
        return dict(self._settings)

    async def load(self) -> Mapping[str, StoredSetting]:
        return self.settings()


def make_runtime_config(
    overrides: Mapping[str, Any] | None = None,
    *,
    ttl_seconds: float = 0.0,
    clock: Clock | None = None,
) -> RuntimeConfig:
    """A RuntimeConfig over an in-memory store; `overrides` maps key name -> value."""
    return RuntimeConfig(InMemoryConfigStore(overrides), ttl_seconds=ttl_seconds, clock=clock)


def make_config_snapshot(overrides: Mapping[str, Any] | None = None) -> ConfigSnapshot:
    """A ConfigSnapshot over the registry defaults plus `overrides`, for station tests."""
    return ConfigSnapshot(InMemoryConfigStore(overrides).settings(), SystemClock().now())
