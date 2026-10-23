"""Run cost: every model call of the run, metered in memory and priced with s36's table.

Nothing here touches the database. Usage rows carry ids, counts and codes only, never prompt or
output text. A model with no price is listed, never summed as zero.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from cashapp.domain.llm_usage import LlmRole, UsageEntry, to_usd
from cashapp.evals.models import CostSummary, RoleCost
from cashapp.integrations.llm.base import LlmClient, LlmClients
from cashapp.integrations.llm.metered import MeteredLlmClient
from cashapp.services.llm_usage.pricing import compute_cost

__all__ = ["EvalUsageRecorder", "UsageRow", "format_usd", "meter_clients", "summarise_cost"]


@dataclass(frozen=True, slots=True)
class UsageRow:
    role: str
    model_id: str
    input_tokens: int | None
    output_tokens: int | None
    outcome: str
    cost_usd: Decimal | None  # None: failed before usage was known, or no price for the model


class EvalUsageRecorder:
    """Satisfies s36's ``UsageRecorder``; keeps the rows in memory for the cost summary."""

    def __init__(self) -> None:
        self.rows: list[UsageRow] = []

    async def record(self, entry: UsageEntry) -> None:
        self.rows.append(
            UsageRow(
                role=entry.role.value,
                model_id=entry.model_id,
                input_tokens=entry.input_tokens,
                output_tokens=entry.output_tokens,
                outcome=entry.outcome.value,
                cost_usd=compute_cost(entry.model_id, entry.input_tokens, entry.output_tokens),
            )
        )


def meter_clients(clients: LlmClients, recorder: EvalUsageRecorder) -> LlmClients:
    """Wrap each role in s36's ``MeteredLlmClient`` so every call lands in ``recorder``."""

    def wrap(inner: LlmClient, role: LlmRole) -> LlmClient:
        return MeteredLlmClient(inner, role, recorder)

    return LlmClients(
        reader_a=wrap(clients.reader_a, LlmRole.READER_A),
        reader_b=wrap(clients.reader_b, LlmRole.READER_B),
        adjudicator=wrap(clients.adjudicator, LlmRole.ADJUDICATOR),
        workhorse=wrap(clients.workhorse, LlmRole.WORKHORSE),
    )


def format_usd(value: Decimal) -> str:
    """Six decimals, except an exact zero which reads ``0.00``."""
    return "0.00" if value == 0 else f"{to_usd(value):.6f}"


def _priced(row: UsageRow) -> bool:
    """False when tokens were reported but no price exists for the model."""
    has_tokens = row.input_tokens is not None and row.output_tokens is not None
    return row.cost_usd is not None or not has_tokens


def _group(rows: list[UsageRow]) -> RoleCost:
    known = sum((r.cost_usd for r in rows if r.cost_usd is not None), Decimal(0))
    return RoleCost(
        calls=len(rows),
        input_tokens=sum(r.input_tokens or 0 for r in rows),
        output_tokens=sum(r.output_tokens or 0 for r in rows),
        cost_usd=format_usd(known) if all(_priced(r) for r in rows) else None,
    )


def summarise_cost(recorder: EvalUsageRecorder, *, mode: Literal["live", "replay"]) -> CostSummary:
    """Totals for the run. In replay the usage was recorded, not spent, so ``spent_usd`` is zero."""
    rows = recorder.rows
    by_role: dict[str, list[UsageRow]] = {}
    by_model: dict[str, list[UsageRow]] = {}
    for row in rows:
        by_role.setdefault(row.role, []).append(row)
        by_model.setdefault(row.model_id, []).append(row)
    known = sum((r.cost_usd for r in rows if r.cost_usd is not None), Decimal(0))
    unknown = sorted({r.model_id for r in rows if not _priced(r)})
    return CostSummary(
        mode=mode,
        calls=len(rows),
        input_tokens=sum(r.input_tokens or 0 for r in rows),
        output_tokens=sum(r.output_tokens or 0 for r in rows),
        spent_usd=format_usd(known) if mode == "live" else "0.00",
        recorded_usage_usd=format_usd(known),
        by_role={name: _group(items) for name, items in sorted(by_role.items())},
        by_model={name: _group(items) for name, items in sorted(by_model.items())},
        unknown_price_models=unknown,
    )
