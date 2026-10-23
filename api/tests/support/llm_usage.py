"""Test helpers for the LLM usage ledger."""

from datetime import UTC, datetime
from typing import Any

from cashapp.domain.llm_usage import LlmRole, UsageEntry, UsageOutcome, station_of
from cashapp.integrations.llm.base import LlmClient
from cashapp.integrations.llm.metered import MeteredLlmClient, UsageRecorder
from cashapp.services.llm_usage.recorder import InMemoryUsageRecorder


def make_usage_entry(**overrides: Any) -> UsageEntry:
    """A valid ``UsageEntry``; keyword arguments override any field."""
    fields: dict[str, Any] = {
        "role": LlmRole.READER_A,
        "provider": "anthropic",
        "model_id": "claude-opus-5-5",
        "purpose": "extract.reader_a",
        "work_item_id": None,
        "prompt_version": None,
        "schema_version": None,
        "effort": None,
        "input_tokens": 1000,
        "output_tokens": 100,
        "latency_ms": 1500,
        "outcome": UsageOutcome.OK,
        "error_code": None,
        "occurred_at": datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    fields.setdefault("station", station_of(fields["purpose"]))
    return UsageEntry(**fields)


def metered(
    inner: LlmClient, role: LlmRole, recorder: UsageRecorder | None = None
) -> tuple[MeteredLlmClient, UsageRecorder]:
    """A metered client over ``inner`` and the recorder it writes to (in memory by default)."""
    used = recorder if recorder is not None else InMemoryUsageRecorder()
    return MeteredLlmClient(inner, role, used), used
