"""Test settings: `make_settings` builds a valid local `Settings` without reading env or files."""

import os
from pathlib import Path
from typing import Any

import pytest

from cashapp.settings import Settings
from cashapp.settings_placeholders import placeholder_settings


def make_settings(**overrides: Any) -> Settings:
    """Overrides are deep-merged per group (dict) or replace the group (model instance)."""
    return placeholder_settings(**overrides)


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No CASHAPP_* variable and no stray .env: loaders see a blank environment."""
    for name in [n for n in os.environ if n.upper().startswith("CASHAPP_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
