"""`python -m cashapp.tools.receipt_signal_study`: read-only receipt-signal study."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from cashapp.integrations.fusion import FusionClient, FusionClientFactory, FusionError
from cashapp.integrations.fusion.fake import FakeFusionClient
from cashapp.settings import SettingsError, aload_settings
from cashapp.tools.receipt_signal_study.report import write_report
from cashapp.tools.receipt_signal_study.run import run_study

app = typer.Typer(add_completion=False, help="Which receipt signals identify the applied receipt.")

_DATE_FORMATS = ["%Y-%m-%d"]
EXIT_STUDY_ERROR = 1
EXIT_BAD_ARGS = 2


async def build_client(pod: str, prior_dir: Path | None) -> FusionClient:
    """`fake` seeds a `FakeFusionClient` from prior fixtures; else a settings pod."""
    if pod.lower() == "fake":
        if prior_dir is None:
            raise typer.BadParameter(
                "--pod fake needs --prior <dir> to seed it", param_hint="--pod"
            )
        return FakeFusionClient.from_json(prior_dir / "day" / "fusion.json")
    settings = await aload_settings()
    return FusionClientFactory(settings).for_pod(pod)


@app.command()
def main(
    pod: Annotated[str, typer.Option("--pod", help="Configured Fusion pod name, or 'fake'.")],
    date_from: Annotated[
        datetime, typer.Option("--from", formats=_DATE_FORMATS, help="First receipt date.")
    ],
    date_to: Annotated[
        datetime, typer.Option("--to", formats=_DATE_FORMATS, help="Last receipt date.")
    ],
    out: Annotated[Path, typer.Option("--out", help="Directory for the output files.")],
    prior: Annotated[
        Path | None, typer.Option("--prior", help="Prior fixtures directory (case source).")
    ] = None,
    signals_report: Annotated[
        str | None, typer.Option("--signals-report", help="BIP path of the receipt_signals report.")
    ] = None,
    date_window_days: Annotated[
        int | None, typer.Option("--date-window-days", min=0, help="Override the date window.")
    ] = None,
    limit_receipts: Annotated[
        int, typer.Option("--limit-receipts", min=1, help="Cap on receipts read.")
    ] = 20_000,
) -> None:
    """Read receipts and their applications, then write aggregate signal statistics."""
    if date_to < date_from:
        typer.echo("--to must not be before --from", err=True)
        raise typer.Exit(EXIT_BAD_ARGS)
    try:
        code = asyncio.run(
            _run(
                pod,
                date_from,
                date_to,
                out,
                prior,
                signals_report,
                date_window_days,
                limit_receipts,
            )
        )
    except typer.BadParameter as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_BAD_ARGS) from exc
    raise typer.Exit(code)


async def _run(
    pod: str,
    date_from: datetime,
    date_to: datetime,
    out: Path,
    prior: Path | None,
    signals_report: str | None,
    date_window_days: int | None,
    limit_receipts: int,
) -> int:
    client: FusionClient | None = None
    try:
        client = await build_client(pod, prior)
        result = await run_study(
            client,
            date_from=date_from.date(),
            date_to=date_to.date(),
            date_window_days=date_window_days,
            signals_report_path=signals_report,
            prior_dir=prior,
            limit_receipts=limit_receipts,
        )
        for path in write_report(result, out):
            typer.echo(str(path))
        return 0
    except (FusionError, SettingsError, KeyError, OSError, ValueError) as exc:
        typer.echo(f"study failed: {type(exc).__name__}: {exc}", err=True)
        return EXIT_STUDY_ERROR
    finally:
        if client is not None:
            await client.aclose()


if __name__ == "__main__":
    app()
