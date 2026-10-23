"""``python -m cashapp.tools.preflight --pod <name>``: thin typer shell over `run_preflight`."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.factory import standalone_factory
from cashapp.integrations.fusion.guard import read_only
from cashapp.services.runtime_settings import (
    RuntimeSettings,
    SettingsIncompleteError,
    load_runtime_settings,
)
from cashapp.settings import SettingsError, load_settings
from cashapp.tools.preflight.checks import PreflightContext, run_preflight
from cashapp.tools.preflight.report import PreflightReport, render_table

app = typer.Typer(help="Read-only Fusion tenant preflight.", add_completion=False)


def make_client(runtime: RuntimeSettings, pod: str) -> FusionClient:
    """Patch point for tests: the real client for `pod`."""
    return standalone_factory(runtime).for_pod(pod)


async def _run(runtime: RuntimeSettings, pod: str, check_timeout_s: float) -> PreflightReport:
    client = read_only(make_client(runtime, pod))
    try:
        ctx = await PreflightContext.from_runtime(
            runtime, pod, check_timeout_s=check_timeout_s, mcp=getattr(client, "mcp", None)
        )
        return await run_preflight(client, ctx)
    finally:
        await client.aclose()


@app.command()
def main(
    pod: Annotated[str, typer.Option("--pod", help="Configured Fusion pod name.")],
    timeout: Annotated[float, typer.Option("--timeout", help="Per-check timeout, seconds.")] = 30.0,
) -> None:
    """Run the preflight against POD and exit 0 (pass), 1 (any failure) or 2 (usage/config)."""
    try:
        runtime = load_runtime_settings(load_settings())
    except (SettingsError, SettingsIncompleteError) as exc:
        typer.echo(f"settings error: {exc}", err=True)
        raise typer.Exit(2) from exc
    key = pod.lower()
    pods = runtime.fusion().pods
    if key not in pods:
        typer.echo(f"unknown pod '{key}'; known pods: {', '.join(sorted(pods))}", err=True)
        raise typer.Exit(2)
    report = asyncio.run(_run(runtime, key, timeout))
    typer.echo(render_table(report))
    raise typer.Exit(0 if report.ok else 1)
