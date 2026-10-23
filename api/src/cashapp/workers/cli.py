"""Command line for the worker host (typer)."""

import asyncio
from typing import Annotated

import typer

from cashapp.observability import configure_observability_bootstrap, reconfigure_observability
from cashapp.pipeline.roles import RoleSpec
from cashapp.services.runtime_settings import SettingsIncompleteError
from cashapp.settings import Settings, get_settings
from cashapp.workers.container import WorkerContainer
from cashapp.workers.discovery import UnknownRoleError, discover_roles, select_roles
from cashapp.workers.host import WorkerHost

app = typer.Typer(help="Run pipeline stations, pollers and the outbox relay.", no_args_is_help=True)


async def _serve(settings: Settings, selected: list[RoleSpec], health_port: int | None) -> int:
    """Open the DB-stored settings, apply logging from them, then run the host (one event loop)."""
    container = WorkerContainer(settings)
    await container.runtime.start()
    reconfigure_observability(container.runtime, service_name="cashapp-worker")
    return await WorkerHost(container, selected, health_port=health_port).run()


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
    configure_observability_bootstrap(service_name="cashapp-worker")  # before settings load
    settings = get_settings()  # configuration errors surface before anything else
    available = discover_roles()
    try:
        selected = select_roles(available, roles)
    except UnknownRoleError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    try:
        code = asyncio.run(_serve(settings, list(selected), health_port))
    except SettingsIncompleteError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    raise typer.Exit(code)


@app.command(name="roles")
def list_roles() -> None:
    """Print every discovered role as '<name><TAB><kind>'."""
    for name, spec in discover_roles().items():
        typer.echo(f"{name}\t{spec.kind}")
