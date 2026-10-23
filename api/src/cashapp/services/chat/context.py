"""The server-side context the chat model answers from: an item summary or the flow's counts.

Everything here is read from the database inside a short read-only unit of work. No artifact
text goes in: the extraction is scrubbed of every source location (and so every quote), and the
free-text fields an artifact could fill (notes, bank account) are dropped.
"""

import json
from datetime import UTC, datetime
from typing import Any, Final, cast

from cashapp.data.models.adjudication import AdjudicationPurged
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.repositories.chat_context import ChatContextRepository
from cashapp.data.repositories.work_items import WorkItemRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.observability.queue_stats import collect_queue_stats
from cashapp.services.chat.errors import ChatNotFound

HISTORY_ENTRIES: Final = 10
DETAIL_VALUE_MAX: Final = 200
REASONING_MAX: Final = 400

# Dropped from the extraction: a source holds page, region and the quoted artifact text; the rest
# are free text or account identifiers the model does not need to explain a stuck item.
_DROPPED_KEYS: Final = frozenset({"source", "notes", "payer_bank_account"})
# Trimmed in this order when the document is over budget.
_TRIM_ORDER: Final = ("recent_history", "lines", "candidate_receipts")


def scrub_extraction(final: dict[str, Any]) -> dict[str, Any]:
    """The extraction without any source location, quote or artifact free text."""

    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            mapping = cast("dict[str, Any]", node)
            return {k: clean(v) for k, v in mapping.items() if k not in _DROPPED_KEYS}
        if isinstance(node, list):
            return [clean(v) for v in cast("list[Any]", node)]
        return node

    cleaned: dict[str, Any] = clean(final)
    return cleaned


def _dump(doc: dict[str, Any]) -> str:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def fit_context(doc: dict[str, Any], max_chars: int) -> str:
    """The document as sorted-key JSON of at most ``max_chars`` characters.

    Over budget, it trims ``recent_history``, then ``lines``, then ``candidate_receipts`` (halving
    each, newest or first entries kept) and marks ``truncated: true``; as a last resort it drops
    the extraction and the error detail. Character count is a proxy for tokens.
    """
    text = _dump(doc)
    if len(text) <= max_chars:
        return text
    work = dict(doc)
    work["truncated"] = True
    for key in _TRIM_ORDER:
        current = work.get(key)
        if not isinstance(current, list):
            continue
        rows = cast("list[Any]", current)
        while rows and len(_dump(work)) > max_chars:
            half = len(rows) // 2
            rows = rows[half:] if key == "recent_history" else rows[:half]
            work[key] = rows
    for key in ("extraction", "last_error_detail"):
        if len(_dump(work)) > max_chars:
            work.pop(key, None)
    return _dump(work)


def _clip(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else text[:limit]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class ChatContextBuilder:
    """Builds the context documents; reads only, never commits."""

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def item_context(self, uow: UnitOfWork, item_id: int) -> dict[str, Any]:
        item = await uow.repo(WorkItemRepository).get(item_id)
        if item is None:
            raise ChatNotFound(item_id)
        doc = self._item_header(item)
        doc["extraction"], lines = await self._extraction(uow, item_id)
        if lines is not None:
            doc["lines"] = lines
        history = await uow.repo(ChatContextRepository).list(
            where=[WorkItemHistory.work_item_id == item_id],
            order_by=[WorkItemHistory.at.desc(), WorkItemHistory.id.desc()],
            limit=HISTORY_ENTRIES,
        )
        doc["recent_history"] = [self._history_entry(row) for row in reversed(history.items)]
        return doc

    async def flow_context(self, uow: UnitOfWork, now: datetime | None = None) -> dict[str, Any]:
        moment = now if now is not None else self._clock.now()
        start_of_day = datetime(moment.year, moment.month, moment.day, tzinfo=UTC)
        stats = await collect_queue_stats(uow, clock=self._clock)
        failures = await uow.repo(ChatContextRepository).failures_by_code_since(start_of_day)
        return {
            "as_of": moment.isoformat(),
            "stages": [
                {
                    "stage": stat.stage.value,
                    "state": stat.state.value,
                    "count": stat.count,
                    "oldest_age_s": stat.oldest_age_s,
                }
                for stat in stats
            ],
            "failures_today": [{"error_code": code.value, "items": n} for code, n in failures],
        }

    def _item_header(self, item: WorkItem) -> dict[str, Any]:
        now = self._clock.now()
        locked = item.lock_owner is not None and (
            item.lock_expires_at is None or item.lock_expires_at > now
        )
        detail = item.last_error_detail or {}
        return {
            "wi": f"WI-{item.id}",
            "stage": item.stage.value,
            "state": item.state.value,
            "attempts": item.attempts,
            "last_error_code": item.last_error_code.value if item.last_error_code else None,
            "last_error_detail": {k: _clip(v, DETAIL_VALUE_MAX) for k, v in detail.items()},
            "escalation_summary": item.escalation_summary,
            "payer_name": item.payer_name,
            "currency": item.currency,
            "payment_amount": str(item.payment_amount) if item.payment_amount is not None else None,
            "payment_date": item.payment_date.isoformat() if item.payment_date else None,
            "payment_status": item.payment_status.value if item.payment_status else None,
            "info_flags": list(item.info_flags),
            "lock": {"owner_name": item.lock_owner_name} if locked else None,
        }

    async def _extraction(
        self, uow: UnitOfWork, item_id: int
    ) -> tuple[dict[str, Any], list[Any] | None]:
        adjudication = await uow.repo(AdjudicationRepository).latest_for(item_id)
        if adjudication is None:
            return {"available": False}, None
        try:
            result = adjudication.result()
        except AdjudicationPurged:
            return {"purged": True}, None
        final = scrub_extraction(result.final.model_dump(mode="json"))
        lines = final.pop("lines", None)
        extraction: dict[str, Any] = {
            "final": final,
            "confidence": result.confidence,
            "missing_reader": adjudication.missing_reader.value
            if adjudication.missing_reader
            else None,
            "disagreements": [d.model_dump(mode="json") for d in result.disagreements],
        }
        return extraction, cast("list[Any]", lines) if isinstance(lines, list) else None

    @staticmethod
    def _history_entry(row: WorkItemHistory) -> dict[str, Any]:
        return {
            "at": _iso(row.at),
            "action": row.action.value,
            "to_stage": row.to_stage.value if row.to_stage else None,
            "error_code": row.error_code.value if row.error_code else None,
            "reasoning": _clip(row.reasoning, REASONING_MAX) if row.reasoning else None,
        }
