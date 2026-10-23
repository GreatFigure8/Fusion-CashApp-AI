"""What one evaluation run was asked to do, and where its files live."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import cashapp

__all__ = ["EvalOptions", "Suite", "default_paths", "expand_suites"]


class Suite(StrEnum):
    EXTRACTION = "extraction"
    MATCHING = "matching"
    AUTOFIX = "autofix"
    ALL = "all"


_CONCRETE: tuple[Suite, ...] = (Suite.EXTRACTION, Suite.MATCHING, Suite.AUTOFIX)


def expand_suites(suite: Suite) -> frozenset[Suite]:
    """``all`` becomes the three concrete suites."""
    return frozenset(_CONCRETE) if suite is Suite.ALL else frozenset({suite})


def ordered(suites: frozenset[Suite]) -> list[Suite]:
    """The concrete suites in the order they run."""
    return [s for s in _CONCRETE if s in suites]


def default_paths() -> dict[str, Path]:
    """Defaults resolved against the api project root, so the command works from any directory."""
    root = Path(cashapp.__file__).resolve().parents[2]
    return {
        "gold": root / "evals" / "gold",
        "artifacts": root / "evals" / "artifacts",
        "recordings": root / "evals" / "recordings",
        "reports": root / "evals" / "reports",
        "prior": root / "tests" / "fixtures" / "prior",
    }


def _no_overrides() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class EvalOptions:
    suites: frozenset[Suite]  # ``all`` already expanded
    out_dir: Path
    gold_dir: Path
    prior_dir: Path
    recordings_dir: Path
    artifacts_dir: Path
    limit: int | None = None
    runs: int = 1
    replay: bool = False
    confirm_spend: bool = False
    config_overrides: Mapping[str, Any] = field(default_factory=_no_overrides)

    @property
    def needs_models(self) -> bool:
        """A live extraction run is the only thing that calls a paid model."""
        return Suite.EXTRACTION in self.suites and not self.replay
