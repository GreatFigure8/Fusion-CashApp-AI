"""Command line for the worker host (typer)."""

import asyncio
from typing import Annotated

import typer

from cashapp.observability.logging import configure_logging
from cashapp.settings import get_settings
from cashapp.workers.container import WorkerContainer
from cashapp.workers.discovery import UnknownRoleError, discover_roles, select_roles
from cashapp.workers.host import WorkerHost

app = typer.Typer(help="Run pipeline stations, pollers and the outbox relay.", no_args_is_help=True)


@app.command()
def run(
    roles: Annotated[
        str, typer.Option("--roles", help="Comma-separated role names, or 'all'.")
    ] = "all",
    health_port: Annotated[
        int | None,
        typer.Option("--health-port", help="Health server port; 0 disables it."),
    ] = None,
) -> None:
    """Start the selected roles and run until stopped."""
    settings = get_settings()  # configuration errors surface before anything else
    configure_logging(settings, service_name="cashapp-worker")
    available = discover_roles()
    try:
        selected = select_roles(available, roles)
    except UnknownRoleError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    host = WorkerHost(WorkerContainer(settings), selected, health_port=health_port)
    code = asyncio.run(host.run())
    raise typer.Exit(code)


@app.command(name="roles")
def list_roles() -> None:
    """Print every discovered role as '<name><TAB><kind>'."""
    for name, spec in discover_roles().items():
        typer.echo(f"{name}\t{spec.kind}")
