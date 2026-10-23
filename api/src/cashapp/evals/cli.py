"""``uv run python -m cashapp.evals run --suite extraction|matching|autofix|all``.

Exit codes: 0 the report was written; 1 a selected suite was not evaluated (or the run failed);
2 bad arguments, an existing output directory, or the spend guard refused.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from cashapp.evals.models import EvalReport, SuiteStatus
from cashapp.evals.options import EvalOptions, Suite, default_paths, expand_suites
from cashapp.evals.runner import SpendNotConfirmed, run_evals
from cashapp.services.config import ConfigError

EXIT_NOT_EVALUATED = 1
EXIT_BAD_ARGS = 2

app = typer.Typer(add_completion=False, help="Measure extraction, matching and auto-fix changes.")


@app.callback()
def _root() -> None:
    """Evaluation harness. Runs are deliberate: a live extraction run spends money."""


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(EXIT_BAD_ARGS)


def _load_overrides(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _fail(f"--config {path}: cannot read a JSON object ({type(exc).__name__})") from exc
    if not isinstance(raw, dict):
        raise _fail(f"--config {path}: expected a JSON object of config_key: value")
    return {str(k): v for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def _not_evaluated(report: EvalReport) -> list[str]:
    suites = {
        "extraction": report.extraction,
        "matching": report.matching,
        "autofix": report.autofix,
    }
    return [
        f"{name}: {suite.reason}"
        for name, suite in suites.items()
        if suite is not None and suite.status is SuiteStatus.NOT_EVALUATED
    ]


@app.command("run")
def run(
    suite: Annotated[Suite, typer.Option("--suite", help="Which suite to run.")],
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Cases per suite.")] = None,
    replay: Annotated[
        bool, typer.Option("--replay", help="Use recorded model outputs: no cost.")
    ] = False,
    runs: Annotated[
        int, typer.Option("--runs", min=1, help="Repeat each extraction case this many times.")
    ] = 1,
    confirm_spend: Annotated[
        bool, typer.Option("--confirm-spend", help="Allow a live run that spends money.")
    ] = False,
    out: Annotated[Path | None, typer.Option("--out", help="Report directory (new).")] = None,
    gold: Annotated[Path | None, typer.Option("--gold", help="Gold extractions.")] = None,
    prior: Annotated[Path | None, typer.Option("--prior", help="Prior fixtures (s43).")] = None,
    recordings: Annotated[Path | None, typer.Option("--recordings", help="Replay set.")] = None,
    config: Annotated[
        Path | None, typer.Option("--config", help="JSON of config_key: value overrides.")
    ] = None,
) -> None:
    """Run one suite (or all) and write report.md and report.json."""
    paths = default_paths()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out if out is not None else paths["reports"] / stamp
    options = EvalOptions(
        suites=expand_suites(suite),
        out_dir=out_dir,
        gold_dir=gold if gold is not None else paths["gold"],
        prior_dir=prior if prior is not None else paths["prior"],
        recordings_dir=recordings if recordings is not None else paths["recordings"],
        artifacts_dir=paths["artifacts"],
        limit=limit,
        runs=runs,
        replay=replay,
        confirm_spend=confirm_spend,
        config_overrides=_load_overrides(config),
    )
    if out_dir.exists():
        raise _fail(f"refusing: {out_dir} already exists; a run never overwrites a report")
    try:
        report = asyncio.run(run_evals(options))
    except SpendNotConfirmed as exc:
        raise _fail(str(exc)) from exc
    except ConfigError as exc:
        raise _fail(f"--config: {exc}") from exc
    typer.echo(f"report written to {out_dir}")
    problems = _not_evaluated(report)
    for problem in problems:
        typer.echo(f"NOT EVALUATED: {problem}", err=True)
    raise typer.Exit(EXIT_NOT_EVALUATED if problems else 0)
