"""The backlog service: create, import, pause, resume, cancel and promote batches.

A backlog item is an ordinary work item with a batch id and the low backlog priority, driven by the
same stage runners as live traffic. Nothing here touches Fusion or the model clients. Artifact
content is never logged: only counts, hashes' owners (item ids) and exception type names.
"""

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from cashapp.api.errors import ApiError
from cashapp.data.models.backlog import BacklogBatch
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.artifacts import is_unique_violation
from cashapp.data.repositories.backlog import PAUSED_NOT_BEFORE, BacklogBatchRepository
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.backlog import (
    ALLOWED_TRANSITIONS,
    BacklogSourceKind,
    BacklogStatus,
    BatchProgress,
    estimate_eta_minutes,
    validate_batch_name,
)
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.principal import SYSTEM_PRINCIPAL, Principal
from cashapp.domain.stages import PIPELINE_ORDER, ItemState, Stage
from cashapp.domain.work_item import PRIORITY_BACKLOG, HistoryAction, SourceKind
from cashapp.integrations.storage.base import ObjectStore
from cashapp.pipeline.events import StageEvent, emit
from cashapp.pollers.intake.ingest import Normaliser, ingest
from cashapp.pollers.intake.sources import ArtifactSource
from cashapp.services.actor import actor_fields
from cashapp.services.config import RuntimeConfig
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.locking import is_locked_for_automation
from cashapp.services.normalise import normalise

logger = logging.getLogger(__name__)

_STATUS_CHECK_EVERY: Final = 50
_CHUNK: Final = 200
_ERROR_MAX: Final = 900
_PROMOTABLE_STATES: Final = (ItemState.DONE, ItemState.ESCALATED, ItemState.AWAITING_RECEIPT)
_CANCEL_STATES: Final = (ItemState.PENDING, ItemState.AWAITING_RECEIPT, ItemState.ESCALATED)


# --------------------------------------------------------------------------- errors


class BacklogError(Exception):
    """Base class for backlog service errors."""


class BacklogNotFound(BacklogError):  # noqa: N818
    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        super().__init__(f"Backlog batch {batch_id} not found")


class BacklogNameTaken(BacklogError):  # noqa: N818
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Backlog batch name {name!r} is already used")


class BacklogTransitionError(BacklogError):
    def __init__(self, status: BacklogStatus, action: str) -> None:
        self.status = status
        self.action = action
        super().__init__(f"Cannot {action} a backlog batch that is {status.value}")


class BacklogSourceError(BacklogError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class BacklogResumeViaCli(BacklogError):  # noqa: N818
    def __init__(self, batch_id: int) -> None:
        self.batch_id = batch_id
        super().__init__(f"Batch {batch_id} reads a mailbox folder; resume it with the CLI")


def backlog_error_to_api(exc: BacklogError) -> ApiError:
    """Translate a backlog error into the API's single error shape."""
    if isinstance(exc, BacklogNotFound):
        return ApiError(404, "backlog_not_found", str(exc))
    if isinstance(exc, BacklogNameTaken):
        return ApiError(409, "backlog_name_taken", str(exc))
    if isinstance(exc, BacklogTransitionError):
        return ApiError(
            409,
            "backlog_invalid_transition",
            str(exc),
            details=[{"status": exc.status.value, "action": exc.action}],
        )
    if isinstance(exc, BacklogResumeViaCli):
        return ApiError(409, "backlog_resume_via_cli", str(exc))
    if isinstance(exc, BacklogSourceError):
        return ApiError(422, "backlog_source_invalid", exc.reason)
    return ApiError(400, "backlog_error", str(exc))


# --------------------------------------------------------------------------- helpers


def append_audit(
    batch: BacklogBatch,
    *,
    at: datetime,
    principal: Principal,
    action: str,
    detail: Mapping[str, Any] | None = None,
) -> None:
    """Append an audit entry (the list is replaced so the JSON change is seen)."""
    entry = {
        "at": at.isoformat(),
        "actor_id": principal.subject,
        "actor_name": principal.display_name,
        "action": action,
        "detail": dict(detail) if detail else None,
    }
    batch.audit = [*batch.audit, entry]


async def _load(uow: UnitOfWork, batch_id: int, *, lock: bool = False) -> BacklogBatch:
    repo = uow.repo(BacklogBatchRepository)
    batch = await repo.get(batch_id)
    if batch is None:
        raise BacklogNotFound(batch_id)
    if lock:
        await uow.session.refresh(batch, with_for_update=True)
    return batch


def _truncate(text: str) -> str:
    return text[:_ERROR_MAX]


async def archive_batch_items(
    uow_factory: UowFactory,
    batch_id: int,
    *,
    principal: Principal,
    clock: Clock,
    reason: str,
    max_items: int | None = None,
) -> int:
    """Archive the batch's PENDING, AWAITING_RECEIPT and ESCALATED items that no person holds.

    Used by cancel and by the hook's cancel sweep. Items in flight are left to finish their stage.
    """
    archived = 0
    after_id = 0
    while max_items is None or archived < max_items:
        async with uow_factory() as uow:
            repo = uow.repo(BacklogBatchRepository)
            limit = _CHUNK if max_items is None else min(_CHUNK, max_items - archived)
            items = await repo.items_in_states(
                batch_id, _CANCEL_STATES, limit=limit, after_id=after_id
            )
            if not items:
                return archived
            now = clock.now()
            for item in items:
                after_id = max(after_id, item.id)
                if is_locked_for_automation(item, now):
                    continue
                previous = item.state
                item.state = ItemState.ARCHIVED
                item.awaiting_since = None
                await record_history(
                    uow,
                    item.id,
                    HistoryEntry(
                        action=HistoryAction.HUMAN_ACTION,
                        **actor_fields(principal),
                        from_stage=item.stage,
                        to_stage=item.stage,
                        from_state=previous,
                        to_state=ItemState.ARCHIVED,
                        reasoning=reason,
                        payload={"batch_id": batch_id},
                    ),
                    clock=clock,
                )
                archived += 1
            await uow.session.flush()
            await uow.commit()
    return archived


# --------------------------------------------------------------------------- service


@dataclass(slots=True)
class _ImportTally:
    ingested: int = 0
    duplicates: int = 0
    failed: int = 0


class BacklogService:
    def __init__(
        self,
        *,
        object_store: ObjectStore,
        config: RuntimeConfig,
        clock: Clock | None = None,
        normaliser: Normaliser = normalise,
    ) -> None:
        self._object_store = object_store
        self._config = config
        self._clock: Clock = clock or SystemClock()
        self._normaliser = normaliser

    # ------------------------------------------------------------------ create and import

    async def create_batch(
        self,
        uow_factory: UowFactory,
        *,
        name: str,
        dry_run: bool,
        rate_limit: int | None,
        source_kind: BacklogSourceKind,
        source_ref: str,
        principal: Principal,
    ) -> BacklogBatch:
        try:
            validate_batch_name(name)
        except ValueError as exc:
            raise BacklogSourceError(str(exc)) from exc
        if rate_limit is not None and rate_limit < 1:
            raise BacklogSourceError("rate limit must be at least 1 per minute")
        now = self._clock.now()
        try:
            async with uow_factory() as uow:
                repo = uow.repo(BacklogBatchRepository)
                if await repo.by_name(name) is not None:
                    raise BacklogNameTaken(name)
                batch = BacklogBatch(
                    name=name,
                    source_kind=source_kind,
                    source_ref=source_ref[:1000],
                    dry_run=dry_run,
                    rate_limit_per_min=rate_limit,
                    status=BacklogStatus.IMPORTING,
                    total=0,
                    created_by=principal.subject,
                    created_by_name=principal.display_name,
                    created_at=now,
                    updated_at=now,
                    audit=[],
                )
                append_audit(
                    batch,
                    at=now,
                    principal=principal,
                    action="created",
                    detail={"dry_run": dry_run, "rate_limit": rate_limit},
                )
                await repo.add(batch)
                await uow.commit()
        except BacklogError:
            raise
        except Exception as exc:
            if is_unique_violation(exc):
                raise BacklogNameTaken(name) from exc
            raise
        logger.info("backlog batch created: batch_id=%s dry_run=%s", batch.id, dry_run)
        return batch

    async def import_batch(
        self,
        uow_factory: UowFactory,
        source: ArtifactSource,
        *,
        name: str,
        dry_run: bool,
        rate_limit: int | None,
        principal: Principal,
        source_kind: BacklogSourceKind = BacklogSourceKind.FOLDER,
        source_ref: str,
    ) -> BacklogBatch:
        """Create the batch and import everything the source holds (the CLI path)."""
        batch = await self.create_batch(
            uow_factory,
            name=name,
            dry_run=dry_run,
            rate_limit=rate_limit,
            source_kind=source_kind,
            source_ref=source_ref,
            principal=principal,
        )
        return await self.run_import(uow_factory, batch.id, source)

    async def run_import(
        self, uow_factory: UowFactory, batch_id: int, source: ArtifactSource
    ) -> BacklogBatch:
        """Read the source through the live intake path, then open the batch to the pipeline.

        An error that escapes the loop is recorded as ``IMPORT_ERROR`` and the batch stays
        IMPORTING, so a resume re-runs this idempotently (dedupe plus the source's move to
        processed/ mean only what is left gets read).
        """
        async with uow_factory() as uow:
            batch = await _load(uow, batch_id)
            if batch.status in {BacklogStatus.CANCELLED, BacklogStatus.DONE}:
                return batch
            if batch.started_at is None:
                batch.started_at = self._clock.now()
            batch.import_error = None
            await uow.commit()

        tally = _ImportTally()
        try:
            await self._import_loop(uow_factory, batch_id, source, tally)
        except Exception as exc:
            logger.error(
                "backlog import failed: batch_id=%s error=%s", batch_id, type(exc).__name__
            )
            async with uow_factory() as uow:
                batch = await _load(uow, batch_id)
                batch.import_error = _truncate(f"{type(exc).__name__}: {exc}")
                append_audit(
                    batch,
                    at=self._clock.now(),
                    principal=SYSTEM_PRINCIPAL,
                    action="import_error",
                    detail={"error_type": type(exc).__name__},
                )
                await uow.commit()
                return batch
        return await self._finish_import(uow_factory, batch_id, tally)

    async def _import_loop(
        self,
        uow_factory: UowFactory,
        batch_id: int,
        source: ArtifactSource,
        tally: _ImportTally,
    ) -> None:
        seen = 0
        async for artifact in source.fetch_new():
            if seen and seen % _STATUS_CHECK_EVERY == 0:
                async with uow_factory() as uow:
                    if (await _load(uow, batch_id)).status == BacklogStatus.CANCELLED:
                        return
            seen += 1
            try:
                result = await ingest(
                    uow_factory,
                    self._object_store,
                    artifact,
                    source_kind=SourceKind.BACKLOG,
                    batch_id=batch_id,
                    priority=PRIORITY_BACKLOG,
                    clock=self._clock,
                    normaliser=self._normaliser,
                )
                await source.mark_processed(artifact.source_ref, "processed")
            except Exception as exc:
                # Type and content hash only: artifact content is never logged.
                logger.warning(
                    "backlog artifact failed: batch_id=%s error=%s", batch_id, type(exc).__name__
                )
                tally.failed += 1
                try:
                    await source.mark_processed(artifact.source_ref, "failed")
                except Exception as mark_exc:
                    logger.warning(
                        "backlog artifact could not be marked failed: error=%s",
                        type(mark_exc).__name__,
                    )
                continue
            if result.duplicate_of is not None:
                tally.duplicates += 1
            else:
                tally.ingested += len(result.item_ids)

    async def _finish_import(
        self, uow_factory: UowFactory, batch_id: int, tally: _ImportTally
    ) -> BacklogBatch:
        async with uow_factory() as uow:
            batch = await _load(uow, batch_id, lock=True)
            if batch.status == BacklogStatus.CANCELLED:
                return batch
            now = self._clock.now()
            batch.total = await uow.repo(BacklogBatchRepository).count_items(batch_id)
            batch.imported_at = now
            batch.status = ALLOWED_TRANSITIONS.get((batch.status, "imported"), batch.status)
            append_audit(
                batch,
                at=now,
                principal=SYSTEM_PRINCIPAL,
                action="imported",
                detail={
                    "ingested": tally.ingested,
                    "duplicates": tally.duplicates,
                    "failed": tally.failed,
                },
            )
            await uow.commit()
        logger.info(
            "backlog import finished: batch_id=%s ingested=%s duplicates=%s failed=%s",
            batch_id,
            tally.ingested,
            tally.duplicates,
            tally.failed,
        )
        return batch

    # ------------------------------------------------------------------ pause, resume, cancel

    async def pause(
        self, uow_factory: UowFactory, batch_id: int, *, principal: Principal
    ) -> BacklogBatch:
        async with uow_factory() as uow:
            batch = await _load(uow, batch_id, lock=True)
            if batch.status == BacklogStatus.PAUSED:
                return batch
            new_status = ALLOWED_TRANSITIONS.get((batch.status, "pause"))
            if new_status is None:
                raise BacklogTransitionError(batch.status, "pause")
            now = self._clock.now()
            batch.status = new_status
            parked = await uow.repo(BacklogBatchRepository).defer_outbox(
                batch_id, not_before=PAUSED_NOT_BEFORE
            )
            append_audit(
                batch, at=now, principal=principal, action="pause", detail={"parked": parked}
            )
            await uow.commit()
        logger.info("backlog batch paused: batch_id=%s parked=%s", batch_id, parked)
        return batch

    async def resume(
        self,
        uow_factory: UowFactory,
        batch_id: int,
        *,
        principal: Principal,
        can_import_mailbox: bool = True,
    ) -> BacklogBatch:
        """Back to RUNNING, or IMPORTING when the import never finished (the caller relaunches).

        The API passes ``can_import_mailbox=False``: it cannot relaunch a mailbox import, so such
        a batch must be resumed through the CLI.
        """
        async with uow_factory() as uow:
            batch = await _load(uow, batch_id, lock=True)
            if batch.status in {BacklogStatus.RUNNING, BacklogStatus.IMPORTING}:
                return batch
            new_status = ALLOWED_TRANSITIONS.get((batch.status, "resume"))
            if new_status is None:
                raise BacklogTransitionError(batch.status, "resume")
            now = self._clock.now()
            if batch.imported_at is None:
                if batch.source_kind == BacklogSourceKind.MAILBOX_FOLDER and not can_import_mailbox:
                    raise BacklogResumeViaCli(batch_id)
                new_status = BacklogStatus.IMPORTING
            batch.status = new_status
            released = await uow.repo(BacklogBatchRepository).release_outbox(batch_id, now=now)
            append_audit(
                batch,
                at=now,
                principal=principal,
                action="resume",
                detail={"released": released, "to": new_status.value},
            )
            await uow.commit()
        logger.info("backlog batch resumed: batch_id=%s released=%s", batch_id, released)
        return batch

    async def cancel(
        self, uow_factory: UowFactory, batch_id: int, *, principal: Principal
    ) -> BacklogBatch:
        async with uow_factory() as uow:
            batch = await _load(uow, batch_id, lock=True)
            if batch.status == BacklogStatus.CANCELLED:
                return batch
            new_status = ALLOWED_TRANSITIONS.get((batch.status, "cancel"))
            if new_status is None:
                raise BacklogTransitionError(batch.status, "cancel")
            now = self._clock.now()
            batch.status = new_status
            batch.finished_at = now
            # Paused rows drain: the throttle admits a cancelled batch's rows and the runners'
            # claim is a no-op for items that are no longer PENDING.
            released = await uow.repo(BacklogBatchRepository).release_outbox(batch_id, now=now)
            append_audit(batch, at=now, principal=principal, action="cancel")
            await uow.commit()
        archived = await archive_batch_items(
            uow_factory,
            batch_id,
            principal=principal,
            clock=self._clock,
            reason="backlog batch cancelled",
        )
        logger.info(
            "backlog batch cancelled: batch_id=%s archived=%s released=%s",
            batch_id,
            archived,
            released,
        )
        return batch

    # ------------------------------------------------------------------ promote

    async def promote(
        self,
        uow_factory: UowFactory,
        dry_batch_id: int,
        *,
        name: str,
        rate_limit: int | None,
        principal: Principal,
    ) -> BacklogBatch:
        """Re-run a finished dry-run batch for real, reusing the extractions already paid for."""
        try:
            validate_batch_name(name)
        except ValueError as exc:
            raise BacklogSourceError(str(exc)) from exc
        if rate_limit is not None and rate_limit < 1:
            raise BacklogSourceError("rate limit must be at least 1 per minute")
        now = self._clock.now()
        async with uow_factory() as uow:
            repo = uow.repo(BacklogBatchRepository)
            dry = await _load(uow, dry_batch_id)
            if not dry.dry_run or dry.status != BacklogStatus.DONE:
                raise BacklogTransitionError(dry.status, "promote")
            if await repo.by_name(name) is not None:
                raise BacklogNameTaken(name)
            real = BacklogBatch(
                name=name,
                source_kind=dry.source_kind,
                source_ref=dry.source_ref,
                dry_run=False,
                rate_limit_per_min=rate_limit,
                status=BacklogStatus.RUNNING,
                total=0,
                created_by=principal.subject,
                created_by_name=principal.display_name,
                created_at=now,
                started_at=now,
                imported_at=now,
                updated_at=now,
                promoted_from_id=dry.id,
                audit=[],
            )
            append_audit(
                real,
                at=now,
                principal=principal,
                action="promoted",
                detail={"from_batch": dry.id},
            )
            try:
                await repo.add(real)
            except Exception as exc:
                if is_unique_violation(exc):
                    raise BacklogNameTaken(name) from exc
                raise
            await uow.commit()
        repointed, skipped = await self._repoint_items(
            uow_factory, dry_batch_id, real.id, principal=principal
        )
        async with uow_factory() as uow:
            real = await _load(uow, real.id, lock=True)
            real.total = repointed
            append_audit(
                real,
                at=self._clock.now(),
                principal=principal,
                action="promote_items",
                detail={"repointed": repointed, "skipped": skipped},
            )
            await uow.commit()
        logger.info(
            "backlog batch promoted: from=%s to=%s repointed=%s skipped=%s",
            dry_batch_id,
            real.id,
            repointed,
            skipped,
        )
        return real

    async def _repoint_items(
        self, uow_factory: UowFactory, from_batch: int, to_batch: int, *, principal: Principal
    ) -> tuple[int, int]:
        repointed = 0
        skipped = 0
        after_id = 0
        resolve_index = PIPELINE_ORDER.index(Stage.RESOLVE_CUSTOMER)
        while True:
            async with uow_factory() as uow:
                items = await uow.repo(BacklogBatchRepository).items_in_states(
                    from_batch, _PROMOTABLE_STATES, limit=_CHUNK, after_id=after_id
                )
                if not items:
                    return repointed, skipped
                now = self._clock.now()
                for item in items:
                    after_id = max(after_id, item.id)
                    if is_locked_for_automation(item, now):
                        skipped += 1
                        continue
                    await self._repoint(uow, item, to_batch, resolve_index, principal, from_batch)
                    repointed += 1
                await uow.commit()

    async def _repoint(
        self,
        uow: UnitOfWork,
        item: WorkItem,
        to_batch: int,
        resolve_index: int,
        principal: Principal,
        from_batch: int,
    ) -> None:
        previous_stage = item.stage
        previous_state = item.state
        keeps_stage = (
            previous_state == ItemState.ESCALATED
            and PIPELINE_ORDER.index(previous_stage) < resolve_index
        )
        stage = previous_stage if keeps_stage else Stage.RESOLVE_CUSTOMER
        item.batch_id = to_batch
        item.priority = PRIORITY_BACKLOG
        item.stage = stage
        item.state = ItemState.PENDING
        item.attempts = 0
        item.payment_status = None
        item.last_error_code = None
        item.last_error_detail = None
        item.escalation_summary = None
        item.awaiting_since = None
        item.fix_hints = None
        item.claim_expires_at = None
        await uow.session.flush()
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.HUMAN_ACTION,
                **actor_fields(principal),
                from_stage=previous_stage,
                to_stage=stage,
                from_state=previous_state,
                to_state=ItemState.PENDING,
                reasoning="promoted from a dry-run backlog batch",
                payload={"from_batch": from_batch, "to_batch": to_batch},
            ),
            clock=self._clock,
        )
        await emit(
            uow,
            StageEvent.new(item.id, stage, clock=self._clock),
            priority=PRIORITY_BACKLOG,
            clock=self._clock,
        )

    # ------------------------------------------------------------------ progress

    async def find_batch_id(self, uow_factory: UowFactory, ref: str) -> int:
        """A batch id from ``ref``, which is either the numeric id or the unique name."""
        if ref.isdigit():
            return int(ref)
        async with uow_factory() as uow:
            batch = await uow.repo(BacklogBatchRepository).by_name(ref)
        if batch is None:
            raise BacklogSourceError(f"no backlog batch named {ref!r}")
        return batch.id

    async def source_ref(self, uow_factory: UowFactory, batch_id: int) -> str:
        """Where the batch reads from; kept off the API schema, used to relaunch an import."""
        async with uow_factory() as uow:
            return (await _load(uow, batch_id)).source_ref

    async def progress(
        self,
        uow: UnitOfWork,
        *,
        statuses: Collection[BacklogStatus] | None = None,
        batch_id: int | None = None,
        limit: int = 100,
    ) -> list[BatchProgress]:
        """Read-only progress for one batch or the newest batches with the given statuses."""
        repo = uow.repo(BacklogBatchRepository)
        if batch_id is not None:
            batch = await repo.get(batch_id)
            if batch is None:
                raise BacklogNotFound(batch_id)
            batches = [batch]
        else:
            batches = await repo.list_by_status(statuses, limit=limit)
        counts = await repo.item_counts([batch.id for batch in batches])
        default_rate = (await self._config.backlog()).rate_limit_per_minute
        now = self._clock.now()
        rows: list[BatchProgress] = []
        for batch in batches:
            batch_counts = counts[batch.id]
            rate = batch.rate_limit_per_min or default_rate
            rows.append(
                BatchProgress(
                    id=batch.id,
                    name=batch.name,
                    status=batch.status,
                    dry_run=batch.dry_run,
                    source_kind=batch.source_kind,
                    total=batch.total if batch.imported_at is not None else batch_counts.items,
                    processed=batch_counts.processed,
                    applied=batch_counts.applied,
                    escalated=batch_counts.escalated,
                    failed=batch_counts.failed,
                    awaiting=batch_counts.awaiting,
                    in_flight=batch_counts.in_flight,
                    rate_limit_per_minute=rate,
                    eta_minutes=estimate_eta_minutes(
                        batch_counts,
                        status=batch.status,
                        rate_per_min=rate,
                        started_at=batch.started_at,
                        now=now,
                    ),
                    started_at=batch.started_at,
                    finished_at=batch.finished_at,
                    created_by=batch.created_by,
                    promoted_from_id=batch.promoted_from_id,
                    import_error=batch.import_error,
                )
            )
        return rows
