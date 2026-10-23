"""``python -m cashapp.tools.backlog``: a thin typer shell over `BacklogService`.

It runs on the worker box with database credentials and has no sign-in token, so it acts as a
``cli:<os user>`` principal with the ADMIN role. Folder paths are trusted operator input (the API,
by contrast, takes only a name under the backlog root). Exit codes: 0 success, 2 on a backlog or
settings error (the message goes to stderr).
"""

import asyncio
import getpass
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from cashapp.api.deps import get_uow_factory
from cashapp.data.uow import UowFactory
from cashapp.domain.backlog import BacklogSourceKind, BacklogStatus, BatchProgress
from cashapp.domain.clock import SystemClock
from cashapp.domain.principal import Principal, Role
from cashapp.integrations.folder import FolderSource
from cashapp.integrations.storage.factory import build_object_store
from cashapp.pollers.intake.sources import ArtifactSource
from cashapp.services.backlog.service import BacklogError, BacklogService, BacklogSourceError
from cashapp.services.backlog.sources import build_backlog_mailbox_source
from cashapp.services.config import build_runtime_config
from cashapp.services.runtime_settings import (
    RuntimeSettings,
    SettingsIncompleteError,
    load_runtime_settings,
)
from cashapp.settings import SettingsError, load_settings

app = typer.Typer(help="Backlog reprocessing.", add_completion=False, no_args_is_help=True)

_EXIT_ERROR = 2


@dataclass(frozen=True, slots=True)
class CliContext:
    runtime: RuntimeSettings
    uow_factory: UowFactory
    service: BacklogService
    principal: Principal


def make_context() -> CliContext:
    """Patch point for tests: the real settings, database, object store and operator principal."""
    runtime = load_runtime_settings(load_settings())
    uow_factory = get_uow_factory()
    service = BacklogService(
        object_store=build_object_store(runtime),
        config=build_runtime_config(uow_factory),
    )
    user = getpass.getuser()
    principal = Principal.from_roles(
        subject=f"cli:{user}",
        display_name=f"CLI ({user})",
        email=None,
        groups=(),
        roles=(Role.ADMIN,),
    )
    return CliContext(runtime, uow_factory, service, principal)


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(_EXIT_ERROR)


def _context() -> CliContext:
    try:
        return make_context()
    except (SettingsError, SettingsIncompleteError) as exc:
        raise _fail(f"settings error: {exc}") from exc


def _run[T](work: Awaitable[T]) -> T:
    async def runner() -> T:
        return await work

    try:
        return asyncio.run(runner())
    except BacklogError as exc:
        raise _fail(str(exc)) from exc


def _row(progress: BatchProgress) -> str:
    eta = "-" if progress.eta_minutes is None else str(progress.eta_minutes)
    mode = "dry-run" if progress.dry_run else "real"
    return (
        f"{progress.id:>5}  {progress.name:<24} {progress.status.value:<10} {mode:<8} "
        f"{progress.processed:>7}/{progress.total:<7} applied={progress.applied} "
        f"escalated={progress.escalated} failed={progress.failed} awaiting={progress.awaiting} "
        f"in_flight={progress.in_flight} rate={progress.rate_limit_per_minute}/min eta_min={eta}"
    )


async def _show(ctx: CliContext, batch_id: int | None) -> list[BatchProgress]:
    async with ctx.uow_factory() as uow:
        return await ctx.service.progress(uow, batch_id=batch_id)


async def _echo_batch(ctx: CliContext, batch_id: int) -> None:
    for row in await _show(ctx, batch_id):
        typer.echo(_row(row))


@app.command("import")
def import_batch(
    name: Annotated[str, typer.Option("--name", help="Unique batch name, for example B-0007.")],
    folder: Annotated[
        Path | None, typer.Option("--folder", help="Folder of artifacts to import.")
    ] = None,
    mailbox_folder: Annotated[
        str | None, typer.Option("--mailbox-folder", help="Mailbox folder to import.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Record what apply would do; write nothing.")
    ] = False,
    rate: Annotated[
        int | None, typer.Option("--rate", min=1, help="Outbox rows per minute for this batch.")
    ] = None,
) -> None:
    """Import a folder or a mailbox folder as a new backlog batch."""
    if (folder is None) == (mailbox_folder is None):
        raise _fail("give exactly one of --folder and --mailbox-folder")
    ctx = _context()
    kind: BacklogSourceKind
    if folder is not None:
        root = folder.resolve()
        if not root.is_dir():
            raise _fail(f"folder does not exist: {folder}")
        source = FolderSource(root, clock=SystemClock())
        kind, source_ref = BacklogSourceKind.FOLDER, str(root)
    else:
        assert mailbox_folder is not None  # noqa: S101 - narrowed by the check above
        try:
            source = build_backlog_mailbox_source(ctx.runtime, mailbox_folder)
        except BacklogSourceError as exc:
            raise _fail(str(exc)) from exc
        kind, source_ref = BacklogSourceKind.MAILBOX_FOLDER, mailbox_folder

    async def work() -> None:
        batch = await ctx.service.import_batch(
            ctx.uow_factory,
            source,
            name=name,
            dry_run=dry_run,
            rate_limit=rate,
            principal=ctx.principal,
            source_kind=kind,
            source_ref=source_ref,
        )
        await _echo_batch(ctx, batch.id)

    _run(work())


@app.command("promote")
def promote_batch(
    batch: Annotated[str, typer.Option("--batch", help="The finished dry-run batch, id or name.")],
    name: Annotated[str, typer.Option("--name", help="Name of the new, real batch.")],
    rate: Annotated[int | None, typer.Option("--rate", min=1)] = None,
) -> None:
    """Run a finished dry-run batch for real, reusing its extractions."""
    ctx = _context()

    async def work() -> None:
        batch_id = await ctx.service.find_batch_id(ctx.uow_factory, batch)
        promoted = await ctx.service.promote(
            ctx.uow_factory, batch_id, name=name, rate_limit=rate, principal=ctx.principal
        )
        await _echo_batch(ctx, promoted.id)

    _run(work())


@app.command("status")
def status(
    batch: Annotated[str | None, typer.Option("--batch", help="Batch id or name.")] = None,
) -> None:
    """Print the progress of one batch, or of every batch."""
    ctx = _context()

    async def work() -> None:
        batch_id = (
            None if batch is None else await ctx.service.find_batch_id(ctx.uow_factory, batch)
        )
        async with ctx.uow_factory() as uow:
            rows = await ctx.service.progress(uow, batch_id=batch_id)
        for row in rows:
            typer.echo(_row(row))

    _run(work())


@app.command("pause")
def pause(batch: Annotated[str, typer.Option("--batch", help="Batch id or name.")]) -> None:
    """Stop releasing the batch's items into the pipeline."""
    ctx = _context()

    async def work() -> None:
        batch_id = await ctx.service.find_batch_id(ctx.uow_factory, batch)
        await ctx.service.pause(ctx.uow_factory, batch_id, principal=ctx.principal)
        await _echo_batch(ctx, batch_id)

    _run(work())


@app.command("resume")
def resume(batch: Annotated[str, typer.Option("--batch", help="Batch id or name.")]) -> None:
    """Resume a paused batch; an unfinished import is continued from where it stopped."""
    ctx = _context()

    async def work() -> None:
        batch_id = await ctx.service.find_batch_id(ctx.uow_factory, batch)
        resumed = await ctx.service.resume(ctx.uow_factory, batch_id, principal=ctx.principal)
        if resumed.status == BacklogStatus.IMPORTING:
            source = _source_for(ctx, resumed.source_kind, resumed.source_ref)
            await ctx.service.run_import(ctx.uow_factory, batch_id, source)
        await _echo_batch(ctx, batch_id)

    _run(work())


@app.command("cancel")
def cancel(batch: Annotated[str, typer.Option("--batch", help="Batch id or name.")]) -> None:
    """Cancel the batch and archive its items that have not started."""
    ctx = _context()

    async def work() -> None:
        batch_id = await ctx.service.find_batch_id(ctx.uow_factory, batch)
        await ctx.service.cancel(ctx.uow_factory, batch_id, principal=ctx.principal)
        await _echo_batch(ctx, batch_id)

    _run(work())


def _source_for(ctx: CliContext, kind: BacklogSourceKind, source_ref: str) -> ArtifactSource:
    """The source an unfinished import reads from, rebuilt from what the batch stored."""
    if kind == BacklogSourceKind.FOLDER:
        return FolderSource(Path(source_ref), clock=SystemClock())
    return build_backlog_mailbox_source(ctx.runtime, source_ref)
