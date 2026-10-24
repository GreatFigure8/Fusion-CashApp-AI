"""The one intake path: hash, dedupe, store, normalise, and create work items in one transaction.

The poller calls this for every artifact; the backlog import (s35) reuses it. Marking the source
processed or failed is the caller's job, so a different source can drive this function.
Artifact content is never logged: only work item ids, content hashes and the source kind.
"""

import asyncio
import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from cashapp.data.models.artifacts import ArtifactPart
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.artifacts import ArtifactPartRepository, is_unique_violation
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.artifacts import (
    CandidateDocument,
    IncomingArtifact,
    NormalisationResult,
    Normalised,
    PartKind,
    Unsupported,
)
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.principal import Principal
from cashapp.domain.review import RECEIVED_FOR_REVIEW
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.work_item import PRIORITY_LIVE, HistoryAction, SourceKind
from cashapp.integrations.storage.base import ObjectStore
from cashapp.integrations.storage.keys import original_key, part_key, part_text_key
from cashapp.pipeline.events import StageEvent, emit
from cashapp.services.actor import actor_fields
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.normalise import normalise

logger = logging.getLogger(__name__)

type Normaliser = Callable[[IncomingArtifact], NormalisationResult]

_SOURCE_REF_MAX = 1000
_NOTES_IN_HISTORY = 50


@dataclass(frozen=True, slots=True)
class IngestResult:
    item_ids: list[int]  # items that entered the pipeline (or the one ESCALATED unsupported item)
    duplicate_of: int | None  # set only when nothing new was created
    envelope_id: int | None = None


async def ingest(
    uow_factory: UowFactory,
    object_store: ObjectStore,
    artifact: IncomingArtifact,
    *,
    source_kind: SourceKind,
    batch_id: int | None = None,
    priority: int = PRIORITY_LIVE,
    clock: Clock | None = None,
    normaliser: Normaliser = normalise,
    actor: Principal | None = None,
    received_payload: Mapping[str, Any] | None = None,
) -> IngestResult:
    """Turn one artifact into work items exactly once; a repeat only adds a history row.

    ``actor`` is set only for a person's upload: the "received" row then names them and carries
    ``received_payload``. Left ``None`` every row is written as the system, as before.
    """
    clock = clock or SystemClock()
    raw_hash = hashlib.sha256(artifact.data).hexdigest()
    run = _Ingest(
        uow_factory=uow_factory,
        object_store=object_store,
        artifact=artifact,
        raw_hash=raw_hash,
        source_kind=source_kind,
        batch_id=batch_id,
        priority=priority,
        clock=clock,
        normaliser=normaliser,
        actor=actor,
        received_payload=received_payload,
    )
    try:
        return await run.once()
    except Exception as exc:
        if not is_unique_violation(exc):
            raise
        # Another process inserted the same hash between our check and our commit. The retry
        # finds it and lands in the duplicate branch.
        logger.info("unique-key race at intake; rechecking: hash=%s", raw_hash)
        return await run.once()


@dataclass(slots=True)
class _Ingest:
    uow_factory: UowFactory
    object_store: ObjectStore
    artifact: IncomingArtifact
    raw_hash: str
    source_kind: SourceKind
    batch_id: int | None
    priority: int
    clock: Clock
    normaliser: Normaliser
    actor: Principal | None = None
    received_payload: Mapping[str, Any] | None = None

    def _by_actor(self, entry: HistoryEntry) -> HistoryEntry:
        """The entry as written by the uploading person; unchanged for system intake."""
        if self.actor is None:
            return entry
        return replace(entry, **actor_fields(self.actor))

    @property
    def _received_from(self) -> str:
        return f"duplicate received from {self.source_kind.value}:{self.artifact.source_ref}"

    async def once(self) -> IngestResult:
        async with self.uow_factory() as uow:
            existing = await uow.work_items.by_content_hash(self.raw_hash)
            if existing is not None:
                await self._record_duplicate(uow, existing)
                await uow.commit()
                logger.info(
                    "duplicate artifact: work_item_id=%s hash=%s source=%s",
                    existing.id,
                    self.raw_hash,
                    self.source_kind.value,
                )
                return IngestResult(item_ids=[], duplicate_of=existing.id)

        await self.object_store.put(
            original_key(self.raw_hash),
            self.artifact.data,
            self.artifact.content_type or "application/octet-stream",
            {"sha256": self.raw_hash, "source_kind": self.source_kind.value},
        )
        result = await asyncio.to_thread(self.normaliser, self.artifact)
        if isinstance(result, Unsupported):
            return await self._store_unsupported(result)
        return await self._store_normalised(result)

    async def _record_duplicate(self, uow: UnitOfWork, existing: WorkItem) -> None:
        await record_history(
            uow,
            existing.id,
            self._by_actor(
                HistoryEntry(action=HistoryAction.DECISION, reasoning=self._received_from)
            ),
            clock=self.clock,
        )

    def _new_item(
        self,
        *,
        content_hash: str,
        stage: Stage,
        state: ItemState,
        parent_id: int | None = None,
        **extra: Any,
    ) -> WorkItem:
        return WorkItem(
            parent_id=parent_id,
            source_kind=self.source_kind,
            source_ref=self.artifact.source_ref[:_SOURCE_REF_MAX],
            content_hash=content_hash,
            artifact_key=original_key(self.raw_hash),
            stage=stage,
            state=state,
            attempts=0,
            priority=self.priority,
            batch_id=self.batch_id,
            info_flags=[],
            **extra,
        )

    async def _store_unsupported(self, result: Unsupported) -> IngestResult:
        summary = f"Unsupported artifact: {result.reason.value}"
        notes = [
            {
                "source_path": note.source_path,
                "media_type": note.media_type,
                "reason": note.reason.value,
            }
            for note in result.notes[:_NOTES_IN_HISTORY]
        ]
        async with self.uow_factory() as uow:
            item = await uow.work_items.add(
                self._new_item(
                    content_hash=self.raw_hash,
                    stage=Stage.CLASSIFY,
                    state=ItemState.ESCALATED,
                    last_error_code=ErrorCode.UNSUPPORTED_ARTIFACT,
                    last_error_detail={
                        "reason": result.reason.value,
                        "media_type": result.media_type,
                    },
                    escalation_summary=summary,
                )
            )
            await record_history(
                uow,
                item.id,
                HistoryEntry(
                    action=HistoryAction.STAGE_TRANSITION,
                    to_stage=Stage.CLASSIFY,
                    to_state=ItemState.ESCALATED,
                    error_code=ErrorCode.UNSUPPORTED_ARTIFACT,
                    reasoning=summary,
                    payload={"notes": notes},
                ),
                clock=self.clock,
            )
            # No event: an escalated item waits for a person.
            await uow.commit()
        logger.info(
            "unsupported artifact escalated: work_item_id=%s hash=%s source=%s",
            item.id,
            self.raw_hash,
            self.source_kind.value,
        )
        return IngestResult(item_ids=[item.id], duplicate_of=None)

    async def _store_normalised(self, result: Normalised) -> IngestResult:
        async with self.uow_factory() as uow:
            new_docs: list[CandidateDocument] = []
            duplicates: dict[int, WorkItem] = {}
            seen: set[str] = set()
            for doc in result.documents:
                if doc.document_hash in seen:
                    continue
                seen.add(doc.document_hash)
                existing = await uow.work_items.by_content_hash(doc.document_hash)
                if existing is None:
                    new_docs.append(doc)
                else:
                    duplicates[existing.id] = existing

            if not new_docs:
                for existing in duplicates.values():
                    await self._record_duplicate(uow, existing)
                await uow.commit()
                first = next(iter(duplicates.values()))
                logger.info(
                    "all documents already known: work_item_id=%s hash=%s source=%s",
                    first.id,
                    self.raw_hash,
                    self.source_kind.value,
                )
                return IngestResult(item_ids=[], duplicate_of=first.id)

        # Parts are stored before the transaction that references them. Keys are content-addressed,
        # so a retry rewrites identical bytes and an orphan from a failed commit is harmless.
        for doc in new_docs:
            await self._store_parts(doc)

        async with self.uow_factory() as uow:
            envelope_id: int | None = None
            if len(result.documents) >= 2:
                envelope = await uow.work_items.add(
                    self._new_item(
                        content_hash=self.raw_hash,
                        stage=Stage.INTAKE,
                        state=ItemState.ARCHIVED,
                    )
                )
                envelope_id = envelope.id
                await record_history(
                    uow,
                    envelope.id,
                    HistoryEntry(
                        action=HistoryAction.DECISION,
                        reasoning="envelope",
                        payload={"documents": len(result.documents), "new": len(new_docs)},
                    ),
                    clock=self.clock,
                )

            item_ids: list[int] = []
            for doc in new_docs:
                item_id = await self._create_child(uow, doc, envelope_id)
                item_ids.append(item_id)

            for existing_id in duplicates:
                await record_history(
                    uow,
                    existing_id,
                    self._by_actor(
                        HistoryEntry(action=HistoryAction.DECISION, reasoning=self._received_from)
                    ),
                    clock=self.clock,
                )
            await uow.commit()

        logger.info(
            "artifact ingested: work_item_ids=%s envelope_id=%s hash=%s source=%s",
            item_ids,
            envelope_id,
            self.raw_hash,
            self.source_kind.value,
        )
        return IngestResult(item_ids=item_ids, duplicate_of=None, envelope_id=envelope_id)

    async def _create_child(
        self, uow: UnitOfWork, doc: CandidateDocument, envelope_id: int | None
    ) -> int:
        item = await uow.work_items.add(
            self._new_item(
                content_hash=doc.document_hash,
                stage=Stage.CLASSIFY,
                state=ItemState.PENDING,
                parent_id=envelope_id,
            )
        )
        parts_repo = uow.repo(ArtifactPartRepository)
        for number, part in enumerate(doc.parts, start=1):
            await parts_repo.add(
                ArtifactPart(
                    work_item_id=item.id,
                    part_no=number,
                    kind=part.kind,
                    media_type=part.media_type,
                    object_key=part_key(doc.document_hash, number),
                    source_path=part.source_path[:_SOURCE_REF_MAX] if part.source_path else None,
                    size_bytes=len(part.data),
                    text_preview_chars=(len(part.text) or None) if part.text is not None else None,
                )
            )
        await record_history(
            uow,
            item.id,
            self._by_actor(
                HistoryEntry(
                    action=HistoryAction.STAGE_TRANSITION,
                    to_stage=Stage.CLASSIFY,
                    to_state=ItemState.PENDING,
                    reasoning="received" if self.actor is None else RECEIVED_FOR_REVIEW,
                    payload={
                        "parts": len(doc.parts),
                        "document_hash": doc.document_hash,
                        "parent_id": envelope_id,
                        **(self.received_payload or {}),
                    },
                )
            ),
            clock=self.clock,
        )
        event = StageEvent.new(item.id, Stage.CLASSIFY, clock=self.clock)
        await emit(uow, event, priority=self.priority, clock=self.clock)
        return item.id

    async def _store_parts(self, doc: CandidateDocument) -> None:
        for number, part in enumerate(doc.parts, start=1):
            await self.object_store.put(
                part_key(doc.document_hash, number),
                part.data,
                part.media_type,
                {
                    "sha256": hashlib.sha256(part.data).hexdigest(),
                    "source_kind": self.source_kind.value,
                },
            )
            if part.text is not None and part.kind != PartKind.TEXT:
                await self.object_store.put(
                    part_text_key(doc.document_hash, number),
                    part.text.encode("utf-8"),
                    "text/plain; charset=utf-8",
                    {
                        "sha256": hashlib.sha256(part.text.encode("utf-8")).hexdigest(),
                        "source_kind": self.source_kind.value,
                    },
                )
