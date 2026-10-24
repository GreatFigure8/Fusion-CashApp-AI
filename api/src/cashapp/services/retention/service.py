"""The retention purge: remove raw artifacts, extraction payloads and history payloads of terminal
items once their configured retention period has passed, and keep the decision trail.

Every destructive step re-checks eligibility under a row lock, and the only external side effect
(the Object Storage delete) always runs after a committed tombstone and PENDING marker.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from cashapp.data.models.artifacts import ArtifactPart
from cashapp.data.models.retention import RetentionPurge
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.repositories.artifacts import ArtifactPartRepository, is_unique_violation
from cashapp.data.repositories.mcp_call_log import McpCallLogRepository
from cashapp.data.repositories.readings import ExtractionReadingRepository
from cashapp.data.repositories.retention import RetentionRepository
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.principal import SYSTEM_PRINCIPAL, Principal
from cashapp.domain.retention import (
    RETENTION_AUDIT_KEY,
    TOMBSTONE_ARTIFACT,
    TOMBSTONE_KIND,
    PurgeKind,
    PurgeReport,
    PurgeStatus,
)
from cashapp.domain.stages import TERMINAL_STATES
from cashapp.domain.work_item import HistoryAction
from cashapp.integrations.storage.base import ObjectStore
from cashapp.integrations.storage.keys import text_key_for, validate_key
from cashapp.services.actor import actor_fields
from cashapp.services.config import ConfigAudit
from cashapp.services.config_groups import RetentionConfig
from cashapp.services.history import HistoryEntry, record_history

logger = logging.getLogger(__name__)

_DEFAULT_BATCH = 50


@dataclass(frozen=True, slots=True)
class _Pending:
    """A committed artifact purge whose objects are still to be deleted."""

    purge_id: int
    item_id: int
    keys: tuple[str, ...]


@dataclass(slots=True)
class _Tally:
    artifacts: int = 0
    parts: int = 0
    readings: int = 0
    adjudications: int = 0
    history_payloads: int = 0
    kept_shared: int = 0
    resumed: int = 0
    skipped: int = 0
    lab_replay_items: int = 0
    deleted_keys: set[str] = field(default_factory=lambda: set[str]())
    would_delete_keys: set[str] = field(default_factory=lambda: set[str]())


class RetentionService:
    def __init__(self, config: RetentionConfig, *, batch_size: int = _DEFAULT_BATCH) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._config = config
        self._batch = batch_size

    async def purge(
        self,
        uow_factory: UowFactory,
        object_store: ObjectStore,
        now: datetime,
        *,
        dry_run: bool = False,
        limit: int = 500,
        principal: Principal = SYSTEM_PRINCIPAL,
    ) -> PurgeReport:
        tally = _Tally()
        if limit >= 1:
            if not dry_run:
                await self._resume(uow_factory, object_store, now, limit, tally)
            artifact_cut = self._cutoff(self._config.raw_artifact_days, now, "raw_artifact_days")
            extraction_cut = self._cutoff(self._config.extraction_days, now, "extraction_days")
            history_cut = self._cutoff(
                self._config.history_payload_days, now, "history_payload_days"
            )
            if artifact_cut is not None:
                await self._purge_artifacts(
                    uow_factory, object_store, now, artifact_cut, limit, dry_run, principal, tally
                )
            if extraction_cut is not None:
                await self._purge_extraction(
                    uow_factory, now, extraction_cut, limit, dry_run, tally
                )
            if history_cut is not None:
                await self._purge_history(uow_factory, now, history_cut, limit, dry_run, tally)
                if not dry_run:
                    await self._purge_mcp_call_log(uow_factory, history_cut)
                await self._purge_lab_items(uow_factory, history_cut, limit, dry_run, tally)
        deleted = tally.would_delete_keys if dry_run else tally.deleted_keys
        report = PurgeReport(
            dry_run=dry_run,
            ran_at=now,
            artifacts=tally.artifacts,
            parts=tally.parts,
            readings=tally.readings,
            adjudications=tally.adjudications,
            history_payloads=tally.history_payloads,
            objects_deleted=len(deleted),
            objects_kept_shared=tally.kept_shared,
            resumed=tally.resumed,
            skipped=tally.skipped,
            lab_replay_items=tally.lab_replay_items,
        )
        logger.info(
            "retention purge: dry_run=%s artifacts=%d parts=%d readings=%d adjudications=%d "
            "history_payloads=%d objects=%d kept_shared=%d resumed=%d skipped=%d",
            dry_run,
            report.artifacts,
            report.parts,
            report.readings,
            report.adjudications,
            report.history_payloads,
            report.objects_deleted,
            report.objects_kept_shared,
            report.resumed,
            report.skipped,
        )
        return report

    @staticmethod
    async def record_run(
        uow_factory: UowFactory, report: PurgeReport, principal: Principal
    ) -> None:
        """Audit one purge run (including dry runs) against ``retention.purge``."""
        async with uow_factory() as uow:
            await ConfigAudit.record(
                uow,
                RETENTION_AUDIT_KEY,
                None,
                report.to_json(),
                principal,
                f"retention purge (dry_run={report.dry_run})",
            )
            await uow.commit()

    # -- eligibility ---------------------------------------------------------------------------

    @staticmethod
    def _cutoff(days: int | None, now: datetime, name: str) -> datetime | None:
        if days is None:
            return None
        if days <= 0:
            logger.warning("retention period %s=%d is not positive; category skipped", name, days)
            return None
        return now - timedelta(days=days)

    # -- artifacts -----------------------------------------------------------------------------

    async def _resume(
        self,
        uow_factory: UowFactory,
        object_store: ObjectStore,
        now: datetime,
        limit: int,
        tally: _Tally,
    ) -> None:
        """Finish purges a crash left PENDING: delete their objects, then confirm them."""
        async with uow_factory() as uow:
            rows = await uow.repo(RetentionRepository).pending(limit=limit)
            entries = [_Pending(row.id, row.work_item_id, tuple(row.object_keys)) for row in rows]
        if entries:
            done = await self._complete(uow_factory, object_store, entries, now, tally)
            tally.resumed += done

    async def _purge_artifacts(
        self,
        uow_factory: UowFactory,
        object_store: ObjectStore,
        now: datetime,
        cutoff: datetime,
        limit: int,
        dry_run: bool,
        principal: Principal,
        tally: _Tally,
    ) -> None:
        remaining = limit
        while remaining > 0:
            size = remaining if dry_run else min(self._batch, remaining)
            async with uow_factory() as uow:
                candidates = await uow.repo(RetentionRepository).artifact_candidates(
                    cutoff, limit=size
                )
                if not candidates:
                    return
                entries, handled = await self._tombstone_batch(
                    uow, candidates, now, cutoff, dry_run, principal, tally
                )
                if not dry_run:
                    await uow.commit()  # tombstone + PENDING marker durable before any delete
            remaining -= len(candidates)
            if dry_run:
                return  # nothing changes, so a second pass would see the same candidates
            if entries:
                await self._complete(uow_factory, object_store, entries, now, tally)
            if handled == 0:
                return  # every candidate was skipped; do not spin on them

    async def _tombstone_batch(
        self,
        uow: UnitOfWork,
        candidate_ids: Sequence[int],
        now: datetime,
        cutoff: datetime,
        dry_run: bool,
        principal: Principal,
        tally: _Tally,
    ) -> tuple[list[_Pending], int]:
        """Lock each candidate, re-check it, and write its tombstone and PENDING marker."""
        locked: list[WorkItem] = []
        for item_id in candidate_ids:
            item = await uow.work_items.get_for_update(item_id, skip_locked=True)
            if item is None or item.state not in TERMINAL_STATES or item.updated_at >= cutoff:
                tally.skipped += 1
                continue
            locked.append(item)
        if not locked:
            return [], 0
        locked_ids = [item.id for item in locked]
        parts_by_item = await uow.repo(ArtifactPartRepository).for_items(locked_ids)
        keys_by_item = {item.id: _object_keys(item, parts_by_item[item.id]) for item in locked}
        all_keys = {key for keys in keys_by_item.values() for key in keys}
        shared = await uow.repo(RetentionRepository).keys_still_referenced(
            all_keys, excluding_item_ids=locked_ids
        )
        entries: list[_Pending] = []
        handled = 0
        for item in locked:
            parts = parts_by_item[item.id]
            keys = keys_by_item[item.id]
            deletable = [key for key in keys if key not in shared]
            kept = len(keys) - len(deletable)
            live_parts = [part for part in parts if part.purged_at is None]
            if dry_run:
                tally.artifacts += 1
                tally.parts += len(live_parts)
                tally.kept_shared += kept
                tally.would_delete_keys.update(deletable)
                handled += 1
                continue
            try:
                async with uow.session.begin_nested():
                    purge_row = await uow.repo(RetentionRepository).add(
                        RetentionPurge(
                            work_item_id=item.id,
                            kind=PurgeKind.ARTIFACT,
                            status=PurgeStatus.PENDING,
                            object_keys=deletable,
                            created_at=now,
                        )
                    )
                    total_bytes = sum(part.size_bytes for part in parts)
                    await record_history(
                        uow,
                        item.id,
                        HistoryEntry(
                            action=HistoryAction.DECISION,
                            **actor_fields(principal),
                            reasoning=TOMBSTONE_ARTIFACT.format(
                                hash=item.content_hash, parts=len(parts), bytes=total_bytes
                            ),
                            payload={
                                "kind": TOMBSTONE_KIND,
                                "content_hash": item.content_hash,
                                "parts": [
                                    {
                                        "part_no": part.part_no,
                                        "kind": part.kind.value,
                                        "size_bytes": part.size_bytes,
                                    }
                                    for part in parts
                                ],
                                "total_bytes": total_bytes,
                                "object_keys_deleted": len(deletable),
                                "object_keys_kept_shared": kept,
                                "policy_days": self._config.raw_artifact_days,
                            },
                            at=now,
                        ),
                    )
            except IntegrityError as exc:
                if not is_unique_violation(exc):
                    raise
                tally.skipped += 1  # another purge got there first
                continue
            tally.artifacts += 1
            tally.kept_shared += kept
            handled += 1
            entries.append(_Pending(purge_row.id, item.id, tuple(deletable)))
        return entries, handled

    async def _complete(
        self,
        uow_factory: UowFactory,
        object_store: ObjectStore,
        entries: Sequence[_Pending],
        now: datetime,
        tally: _Tally,
    ) -> int:
        """Delete each entry's objects, then mark its parts purged and confirm it.

        An entry whose delete fails stays PENDING for the next run. Returns entries confirmed.
        """
        done: list[_Pending] = []
        for entry in entries:
            if await self._delete_keys(object_store, entry, tally):
                done.append(entry)
        if not done:
            return 0
        async with uow_factory() as uow:
            parts_by_item = await uow.repo(ArtifactPartRepository).for_items(
                [entry.item_id for entry in done]
            )
            retention = uow.repo(RetentionRepository)
            rows: list[RetentionPurge] = []
            for entry in done:
                row = await retention.get(entry.purge_id)
                if row is not None:
                    rows.append(row)
            for parts in parts_by_item.values():
                live = [part for part in parts if part.purged_at is None]
                await uow.repo(ArtifactPartRepository).mark_purged(live, at=now)
                tally.parts += len(live)
            await retention.confirm(rows, at=now)
            await uow.commit()
        return len(done)

    @staticmethod
    async def _delete_keys(object_store: ObjectStore, entry: _Pending, tally: _Tally) -> bool:
        for key in entry.keys:
            if key in tally.deleted_keys:
                continue
            try:
                await object_store.delete(validate_key(key))
            except Exception as exc:
                logger.error(
                    "retention delete failed: item=%d error=%s", entry.item_id, type(exc).__name__
                )
                return False
            tally.deleted_keys.add(key)
        return True

    # -- extraction and history payloads -------------------------------------------------------

    async def _purge_extraction(
        self,
        uow_factory: UowFactory,
        now: datetime,
        cutoff: datetime,
        limit: int,
        dry_run: bool,
        tally: _Tally,
    ) -> None:
        remaining = limit
        while remaining > 0:
            size = remaining if dry_run else min(self._batch, remaining)
            async with uow_factory() as uow:
                retention = uow.repo(RetentionRepository)
                ids = await retention.extraction_candidates(cutoff, limit=size)
                if not ids:
                    return
                if dry_run:
                    tally.readings += await retention.count_readings(ids)
                    tally.adjudications += await retention.count_adjudications(ids)
                    return
                readings = await uow.repo(ExtractionReadingRepository).purge_outputs(ids, at=now)
                adjudications = await uow.repo(AdjudicationRepository).purge_payloads(ids, at=now)
                await uow.commit()
            tally.readings += readings
            tally.adjudications += adjudications
            remaining -= len(ids)
            if readings + adjudications == 0:
                return

    @staticmethod
    async def _purge_mcp_call_log(uow_factory: UowFactory, cutoff: datetime) -> None:
        """MCP call-log rows age out with the history payloads (no key of their own)."""
        async with uow_factory() as uow:
            await uow.repo(McpCallLogRepository).purge_before(cutoff)
            await uow.commit()

    async def _purge_history(
        self,
        uow_factory: UowFactory,
        now: datetime,
        cutoff: datetime,
        limit: int,
        dry_run: bool,
        tally: _Tally,
    ) -> None:
        remaining = limit
        while remaining > 0:
            size = remaining if dry_run else min(self._batch, remaining)
            async with uow_factory() as uow:
                retention = uow.repo(RetentionRepository)
                ids = await retention.history_candidates(cutoff, limit=size)
                if not ids:
                    return
                if dry_run:
                    tally.history_payloads += len(ids)
                    return
                purged = await retention.purge_history_payloads(ids, at=now)
                await uow.commit()
            tally.history_payloads += purged
            remaining -= len(ids)
            if purged == 0:
                return

    async def _purge_lab_items(
        self,
        uow_factory: UowFactory,
        cutoff: datetime,
        limit: int,
        dry_run: bool,
        tally: _Tally,
    ) -> None:
        """Delete the per-item results of finished lab replays past the history cutoff.

        Never a RUNNING replay and never without a cutoff: the candidate query and the DELETE
        both require a terminal status and ``FINISHED_AT < cutoff`` (guard before any mutation).
        """
        remaining = limit
        while remaining > 0:
            size = remaining if dry_run else min(self._batch, remaining)
            async with uow_factory() as uow:
                retention = uow.repo(RetentionRepository)
                ids = await retention.lab_item_candidates(cutoff, limit=size)
                if not ids:
                    return
                if dry_run:
                    tally.lab_replay_items += await retention.count_lab_items(ids)
                    return
                purged = await retention.purge_lab_items(ids, cutoff)
                await uow.commit()
            tally.lab_replay_items += purged
            remaining -= len(ids)
            if purged == 0:
                return


def _object_keys(item: WorkItem, parts: Sequence[ArtifactPart]) -> list[str]:
    """Every object an item owns: the original, each part and each part's text sibling."""
    keys: list[str] = []
    if item.artifact_key is not None:
        keys.append(validate_key(item.artifact_key))
    for part in parts:
        keys.append(validate_key(part.object_key))
        if part.text_preview_chars is not None:
            keys.append(text_key_for(part.object_key))
    return list(dict.fromkeys(keys))
