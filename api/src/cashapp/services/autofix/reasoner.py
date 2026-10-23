"""The plain-language "why it is stuck" summary written when an item goes to a person.

The workhorse model (Haiku) writes it from a bounded facts block that never contains artifact text
or extracted lines. Any failure falls back to a deterministic template, so escalation is never
blocked and a failed call never looks like a normal result.
"""

import json
import re
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from cashapp.data.models.work_item import WorkItem
from cashapp.integrations.llm.base import LlmClient, LlmClients, LlmRequest, TextPart
from cashapp.observability.logging import get_logger
from cashapp.pipeline.errors import StageError
from cashapp.services.autofix.attempts import AttemptRecord
from cashapp.services.autofix.prompts import (
    DESC_SUMMARY,
    PROMPT_VERSION,
    SUMMARY_MAX_TOKENS,
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_TIMEOUT_CAP_S,
)
from cashapp.services.config_groups import ModelRole

logger = get_logger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_DETAIL_VALUE_MAX = 200
_DETAIL_KEYS_MAX = 20
_REASONING_MAX = 300
_ATTEMPTS_MAX = 10


class Reasoner(Protocol):
    async def summarise(
        self, item: WorkItem, error: StageError, attempts: Sequence[AttemptRecord]
    ) -> str: ...


class EscalationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description=DESC_SUMMARY, max_length=1200)


def limit_sentences(text: str, n: int = 3, *, max_chars: int = 600) -> str:
    """At most ``n`` sentences and ``max_chars`` characters, whitespace collapsed."""
    collapsed = " ".join(text.split())
    if not collapsed:
        return ""
    kept = " ".join(_SENTENCE_END.split(collapsed)[:n])
    if len(kept) > max_chars:
        kept = kept[:max_chars].rstrip()
    return kept


def template_summary(item: WorkItem, error: StageError, attempts: Sequence[AttemptRecord]) -> str:
    """A deterministic summary built from the error and the attempts; no model involved."""
    first = f"{error.message.rstrip('.')} (at {item.stage.value.replace('_', ' ').lower()})."
    mine = [record for record in attempts if record.error_code == error.code]
    if mine:
        tried = len([record for record in mine if record.decision != "escalate"])
        second = f"The system tried {tried} automatic fix attempt(s) without resolving it."
    elif error.code.spec.always_person:
        second = "This kind of problem is always decided by a person."
    else:
        second = "No automatic fix applies to this problem."
    third = "A person needs to review the item, correct the data if needed and requeue it."
    return limit_sentences(f"{first} {second} {third}")


class TemplateReasoner:
    """Used when no model client is available."""

    def __init__(self) -> None:
        pass

    async def summarise(
        self, item: WorkItem, error: StageError, attempts: Sequence[AttemptRecord]
    ) -> str:
        return template_summary(item, error, attempts)


def _short(value: Any) -> Any:
    if isinstance(value, str):
        return value[:_DETAIL_VALUE_MAX]
    if isinstance(value, bool | int | float) or value is None:
        return value
    return str(value)[:_DETAIL_VALUE_MAX]


def _facts_json(item: WorkItem, error: StageError, attempts: Sequence[AttemptRecord]) -> str:
    detail = {
        str(key)[:60]: _short(value) for key, value in list(error.detail.items())[:_DETAIL_KEYS_MAX]
    }
    facts: dict[str, Any] = {
        "stage": item.stage.value,
        "error_code": error.code.value,
        "error_description": error.message[:_DETAIL_VALUE_MAX],
        "error_detail": detail,
        "payer_name": item.payer_name,
        "payment_amount": str(item.payment_amount) if item.payment_amount is not None else None,
        "currency": item.currency,
        "payment_date": item.payment_date.isoformat() if item.payment_date is not None else None,
        "attempts": [
            {
                "error_code": record.error_code.value if record.error_code else None,
                "decision": record.decision,
                "reasoning": (record.reasoning or "")[:_REASONING_MAX],
            }
            for record in list(attempts)[-_ATTEMPTS_MAX:]
        ],
    }
    return json.dumps(facts, default=str, sort_keys=True)


class LlmReasoner:
    """Asks the workhorse model for the summary. Never raises."""

    def __init__(self, llm: LlmClient | LlmClients, role: ModelRole) -> None:
        client = llm.workhorse if isinstance(llm, LlmClients) else llm
        self._client = client.with_model(role.model_id)
        self._role = role

    async def summarise(
        self, item: WorkItem, error: StageError, attempts: Sequence[AttemptRecord]
    ) -> str:
        request = LlmRequest(
            system=SUMMARY_SYSTEM_PROMPT,
            parts=(TextPart(_facts_json(item, error, attempts)),),
            max_tokens=SUMMARY_MAX_TOKENS,
            timeout_s=min(float(self._role.timeout_s), SUMMARY_TIMEOUT_CAP_S),
            purpose="autofix.workhorse",
            effort=self._role.effort,
            work_item_id=item.id,
            prompt_version=PROMPT_VERSION,
        )
        try:
            result = await self._client.parse(request, EscalationSummary)
        except Exception as exc:
            # Type only: a message may carry remittance content.
            logger.warning(
                "autofix.summary_fallback",
                extra={"reason": type(exc).__name__, "work_item_id": item.id},
            )
            return template_summary(item, error, attempts)
        text = limit_sentences(result.output.summary) if result.output is not None else ""
        if result.refused or not text:
            logger.warning(
                "autofix.summary_fallback",
                extra={"reason": "refused" if result.refused else "empty", "work_item_id": item.id},
            )
            return template_summary(item, error, attempts)
        return text
