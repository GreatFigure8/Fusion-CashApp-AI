"""``python -m cashapp.tools.preflight --pod <name>``: thin typer shell over `run_preflight`."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.factory import FusionClientFactory
from cashapp.integrations.fusion.guard import read_only
from cashapp.settings import Settings, SettingsError, load_settings
from cashapp.tools.preflight.checks import PreflightContext, run_preflight
from cashapp.tools.preflight.report import PreflightReport, render_table

app = typer.Typer(help="Read-only Fusion tenant preflight.", add_completion=False)


def make_client(settings: Settings, pod: str) -> FusionClient:
    """Patch point for tests: the real client for `pod`."""
    return FusionClientFactory(settings).for_pod(pod)


async def _run(settings: Settings, pod: str, check_timeout_s: float) -> PreflightReport:
    client = read_only(make_client(settings, pod))
    try:
        ctx = PreflightContext.from_settings(settings, pod, check_timeout_s=check_timeout_s)
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
        settings = load_settings()
    except SettingsError as exc:
        typer.echo(f"settings error: {exc}", err=True)
        raise typer.Exit(2) from exc
    key = pod.lower()
    if key not in settings.fusion.pods:
        typer.echo(
            f"unknown pod '{key}'; known pods: {', '.join(sorted(settings.fusion.pods))}",
            err=True,
        )
        raise typer.Exit(2)
    report = asyncio.run(_run(settings, key, timeout))
    typer.echo(render_table(report))
    raise typer.Exit(0 if report.ok else 1)
