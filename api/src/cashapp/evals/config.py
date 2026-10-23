"""Configuration for an evaluation run: registry defaults plus ``--config`` overrides.

The harness never reads the database. Overrides are validated through s28's ``validate_value`` so
a mistyped rule is refused before anything runs, and they are applied through the same
``ConfigSnapshot`` the stations use, so a rule or model change is measured exactly as it would run.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import JsonValue

from cashapp.services.config import (
    ConfigSnapshot,
    RuntimeConfig,
    StoredSetting,
    lookup_key,
    validate_value,
)

__all__ = ["EVAL_ACTOR", "StaticConfigStore", "eval_runtime_config", "eval_snapshot"]

EVAL_ACTOR = "evals"


class StaticConfigStore:
    """A ``ConfigStore`` over a fixed set of overrides."""

    def __init__(self, overrides: Mapping[str, Any] | None = None) -> None:
        self._stored: dict[str, StoredSetting] = {}
        now = datetime.now(UTC)
        for name, value in (overrides or {}).items():
            key = lookup_key(name)  # UnknownConfigKey
            validate_value(key, value)  # ConfigValidationError
            self._stored[name] = StoredSetting(
                key=name,
                value=cast(JsonValue, value),
                version=1,
                updated_at=now,
                updated_by=EVAL_ACTOR,
            )

    @property
    def stored(self) -> Mapping[str, StoredSetting]:
        return dict(self._stored)

    async def load(self) -> Mapping[str, StoredSetting]:
        return self.stored


def eval_snapshot(overrides: Mapping[str, Any] | None = None) -> ConfigSnapshot:
    """The configuration the run measures: registry defaults with ``overrides`` on top."""
    return ConfigSnapshot(StaticConfigStore(overrides).stored)


def eval_runtime_config(overrides: Mapping[str, Any] | None = None) -> RuntimeConfig:
    return RuntimeConfig(StaticConfigStore(overrides))
