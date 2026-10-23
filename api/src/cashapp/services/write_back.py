"""Write-back: tell the story in Fusion by attaching the remittance and noting what was applied.

Takes the Fusion client and object store as plain arguments (``WriteBackDeps``), never a request.
It reads ``LINE_RESULT`` and ``APPLICATION_LEDGER`` and never writes either: a write-back failure
must not undo applications. After each successful Fusion write it commits one FUSION_WRITE
history row, so a later failure never loses the record of what Fusion already holds.
"""

import mimetypes
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self, cast

from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.repositories.applications import (
    ApplicationLedgerRepository,
    LineResultRepository,
)
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.stages import Stage
from cashapp.domain.work_item import HistoryAction, SourceKind
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import AttachmentRef
from cashapp.integrations.storage.base import ObjectNotFound, ObjectStore
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.roles import Container
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.receipt_note import NoteItem, NoteLine, WriteBackMode, compose_receipt_note

__all__ = [
    "OBJECT_STORE_ERROR",
    "WriteBackDeps",
    "WriteBackMode",
    "WriteBackResult",
    "attachment_name",
    "receipts_for_write_back",
    "write_back",
]

OBJECT_STORE_ERROR = "OBJECT_STORE_ERROR"
_SUFFIX = re.compile(r"^\.[a-z0-9]{1,8}$")
_HISTORY_PAGE = 200


@dataclass(frozen=True, slots=True)
class WriteBackDeps:
    fusion: FusionClient
    object_store: ObjectStore

    @classmethod
    def from_container(cls, c: Container) -> Self:
        return cls(fusion=c.resolve(FusionClient), object_store=c.resolve(ObjectStore))


@dataclass(frozen=True, slots=True)
class WriteBackResult:
    note_written: bool  # a PATCH was sent this call
    attachment_ref: AttachmentRef | None  # None only when the artifact is unavailable
    note_already_present: bool = False
    attachment_reused: bool = False


@dataclass(frozen=True, slots=True)
class _Failure:
    step: str
    cause: str
    retryable: bool
    fusion_code: str | None = None
    http_status: int | None = None
    outcome_unknown: bool = False


def attachment_name(item: WorkItem) -> tuple[str, str]:
    """``(filename, content_type)``: ``.eml`` for emails, else a whitelisted original suffix."""
    base = f"remittance-WI-{item.id}"
    if item.source_kind is SourceKind.MAILBOX:
        return f"{base}.eml", "message/rfc822"
    suffix = ""
    if item.source_ref:
        dot = item.source_ref.rfind(".")
        candidate = item.source_ref[dot:].lower() if dot >= 0 else ""
        if _SUFFIX.match(candidate):
            suffix = candidate
    if suffix:
        guessed, _ = mimetypes.guess_type(f"x{suffix}")
        return f"{base}{suffix}", guessed or "application/octet-stream"
    return f"{base}.bin", "application/octet-stream"


def _failure_from_fusion(step: str, exc: FusionError) -> _Failure:
    return _Failure(
        step=step,
        cause=exc.code.value,
        retryable=exc.retryable,
        fusion_code=exc.fusion_code,
        http_status=exc.http_status,
        outcome_unknown=exc.outcome_unknown,
    )


async def _all_history(uow: UnitOfWork, item_id: int) -> list[WorkItemHistory]:
    rows: list[WorkItemHistory] = []
    offset = 0
    while True:
        page = await uow.history.for_item(item_id, offset=offset, limit=_HISTORY_PAGE)
        rows.extend(page.items)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            return rows


async def receipts_for_write_back(uow: UnitOfWork, item_id: int) -> list[int]:
    """Receipt ids to write back to: the hand-off payload plus every receipt in the ledger."""
    found: set[int] = set()
    latest: WorkItemHistory | None = None
    for row in await _all_history(uow, item_id):
        if row.action is HistoryAction.STAGE_TRANSITION and row.to_stage is Stage.WRITE_BACK:
            latest = row
    if latest is not None and isinstance(latest.payload, dict):
        raw = latest.payload.get("receipt_id")
        if isinstance(raw, int) and not isinstance(raw, bool):
            found.add(raw)
    for entry in await uow.repo(ApplicationLedgerRepository).for_item(item_id):
        found.add(int(entry.receipt_id))
    return sorted(found)


def _recorded_attachment(
    history: list[WorkItemHistory], receipt_id: int, filename: str
) -> AttachmentRef | None:
    for row in reversed(history):
        payload = row.payload
        if (
            row.action is HistoryAction.FUSION_WRITE
            and isinstance(payload, dict)
            and payload.get("op") == "attach"
            and payload.get("receipt_id") == receipt_id
            and payload.get("filename") == filename
        ):
            attachment_id = payload.get("attachment_id")
            title = payload.get("title")
            return AttachmentRef(
                receipt_id=receipt_id,
                attachment_id=str(attachment_id) if attachment_id is not None else None,
                filename=filename,
                title=str(title) if title is not None else None,
            )
    return None


async def _artifact_key(uow: UnitOfWork, item: WorkItem) -> str | None:
    if item.artifact_key:
        return item.artifact_key
    if item.parent_id is not None:
        parent = await uow.work_items.get(item.parent_id)
        if parent is not None:
            return parent.artifact_key
    return None


async def _attach(
    uow: UnitOfWork,
    item: WorkItem,
    receipt_id: int,
    *,
    mode: WriteBackMode,
    deps: WriteBackDeps,
    clock: Clock,
) -> tuple[AttachmentRef | None, bool, _Failure | None]:
    filename, content_type = attachment_name(item)
    title = filename.rsplit(".", 1)[0]

    recorded = _recorded_attachment(await _all_history(uow, item.id), receipt_id, filename)
    if recorded is not None:
        return recorded, True, None

    try:
        for existing in await deps.fusion.list_receipt_attachments(receipt_id):
            if existing.filename == filename or existing.title == title:
                return existing, True, None
    except FusionError as exc:
        return None, False, _failure_from_fusion("attach", exc)

    key = await _artifact_key(uow, item)
    skipped: str | None = None
    content = b""
    if key is None:
        skipped = "artifact_unavailable"
    else:
        try:
            content = await deps.object_store.get(key)
        except ObjectNotFound:
            skipped = "artifact_unavailable"
        except Exception:
            return None, False, _Failure("attach", OBJECT_STORE_ERROR, retryable=True)
    if skipped is not None:
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.FUSION_WRITE,
                reasoning="Remittance not attached: the original artifact is not available.",
                payload={
                    "op": "attach",
                    "mode": mode,
                    "receipt_id": receipt_id,
                    "attachment_ref": None,
                    "attachment_skipped": skipped,
                },
            ),
            clock=clock,
        )
        await uow.commit()
        return None, False, None

    try:
        ref = await deps.fusion.attach_to_receipt(
            receipt_id, filename, content, content_type, title
        )
    except FusionError as exc:
        return None, False, _failure_from_fusion("attach", exc)
    await record_history(
        uow,
        item.id,
        HistoryEntry(
            action=HistoryAction.FUSION_WRITE,
            reasoning=f"Attached the remittance to receipt {receipt_id} in Fusion.",
            payload={
                "op": "attach",
                "mode": mode,
                "receipt_id": receipt_id,
                "attachment_id": ref.attachment_id,
                "filename": filename,
                "title": title,
                "reused": False,
            },
        ),
        clock=clock,
    )
    await uow.commit()
    return ref, False, None


async def _note(
    uow: UnitOfWork,
    item: WorkItem,
    receipt_id: int,
    line_results: Sequence[NoteLine],
    *,
    mode: WriteBackMode,
    deps: WriteBackDeps,
    note_max_chars: int,
    clock: Clock,
) -> tuple[bool, bool, _Failure | None]:
    """``(note_written, note_already_present, failure)``."""
    try:
        existing = (await deps.fusion.get_receipt(receipt_id)).comments
        text = compose_receipt_note(
            cast("NoteItem", item),
            line_results,
            note_max_chars,
            existing=existing,
            mode=mode,
            on=clock.now().date(),
        )
        if text == existing:
            return False, True, None
        await deps.fusion.set_receipt_comment(receipt_id, text)
    except FusionError as exc:
        return False, False, _failure_from_fusion("note", exc)
    await record_history(
        uow,
        item.id,
        HistoryEntry(
            action=HistoryAction.FUSION_WRITE,
            reasoning=f"Wrote the outcome note on receipt {receipt_id} in Fusion.",
            payload={
                "op": "note",
                "mode": mode,
                "receipt_id": receipt_id,
                "chars": len(text),
                "note": text,
                "previous_note": existing,
            },
        ),
        clock=clock,
    )
    await uow.commit()
    return True, False, None


async def write_back(
    uow: UnitOfWork,
    item: WorkItem,
    receipt_id: int,
    *,
    mode: WriteBackMode,
    deps: WriteBackDeps,
    note_max_chars: int,
    clock: Clock,
) -> WriteBackResult:
    """Attach the remittance and set the note; raises ``StageError(WRITE_BACK_FAILED)``.

    Both steps are attempted even when the first fails. Never writes ``APPLICATION_LEDGER`` or
    ``LINE_RESULT``. ``detail`` keys: cause, step, retryable, fusion_code, http_status,
    outcome_unknown, failures.
    """
    line_results = list(await uow.repo(LineResultRepository).for_item(item.id))
    failures: list[_Failure] = []

    ref, reused, attach_failure = await _attach(
        uow, item, receipt_id, mode=mode, deps=deps, clock=clock
    )
    if attach_failure is not None:
        failures.append(attach_failure)

    written, present, note_failure = await _note(
        uow,
        item,
        receipt_id,
        cast("Sequence[NoteLine]", line_results),
        mode=mode,
        deps=deps,
        note_max_chars=note_max_chars,
        clock=clock,
    )
    if note_failure is not None:
        failures.append(note_failure)

    if failures:
        first = failures[0]
        raise StageError(
            ErrorCode.WRITE_BACK_FAILED,
            detail={
                "cause": first.cause,
                "step": first.step,
                "retryable": all(f.retryable for f in failures),
                "fusion_code": first.fusion_code,
                "http_status": first.http_status,
                "outcome_unknown": any(f.outcome_unknown for f in failures),
                "receipt_id": receipt_id,
                "failures": [
                    {"step": f.step, "cause": f.cause, "retryable": f.retryable} for f in failures
                ],
            },
        )
    return WriteBackResult(
        note_written=written,
        attachment_ref=ref,
        note_already_present=present,
        attachment_reused=reused,
    )
