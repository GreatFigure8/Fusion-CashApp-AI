"""Shared loader for GitHub Actions workflow files under ``.github/workflows``."""

from pathlib import Path
from typing import Any

import yaml  # pyright: ignore[reportMissingTypeStubs]

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
WORKFLOWS_DIR: Path = REPO_ROOT / ".github" / "workflows"


def load_workflow(name: str) -> dict[str, Any]:
    """Parse a workflow file; PyYAML reads ``on:`` as ``True``, renamed back to ``"on"``."""
    path = WORKFLOWS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as handle:
        data: dict[Any, Any] = yaml.safe_load(handle)
    if True in data:
        data["on"] = data.pop(True)
    return data


def workflow_triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return the ``on`` section normalised to a dict of trigger name to config."""
    triggers = workflow["on"]
    if isinstance(triggers, str):
        return {triggers: None}
    if isinstance(triggers, list):
        return {str(name): None for name in triggers}  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    return dict(triggers)


def iter_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Every step of every job, in file order."""
    steps: list[dict[str, Any]] = []
    for job in workflow.get("jobs", {}).values():
        steps.extend(job.get("steps", []))
    return steps


def step_text(step: dict[str, Any]) -> str:
    """Lower-cased name, uses, run and with/env text of a step for forbidden-word scans."""
    parts = [
        str(step.get("name", "")),
        str(step.get("uses", "")),
        str(step.get("run", "")),
        str(step.get("with", "")),
        str(step.get("env", "")),
    ]
    return " ".join(parts).lower()
