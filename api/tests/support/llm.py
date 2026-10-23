"""Test support for the LLM layer: scripted clients and a valid synthetic extraction.

Import these directly (``from tests.support.llm import scripted_llm``); this module is not a
pytest plugin. Recorded fixtures under ``tests/fixtures/llm`` are synthetic and unverified
against a live model.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from cashapp.domain.extraction import (
    DateCandidate,
    DateKind,
    Extracted,
    ExtractedLine,
    LineKind,
    RemittanceExtraction,
    SourceLocation,
)
from cashapp.integrations.llm.base import LlmClient, LlmClients, LlmResult, LlmUsage
from cashapp.integrations.llm.fake import ReplayLlmClient, ScriptedStep

DEFAULT_CONFIDENCE = 0.95

# Fields of RemittanceExtraction that hold an Extracted[...] wrapper.
_EXTRACTED_FIELDS = frozenset(
    {
        "payer_name",
        "payer_bank_account",
        "remittance_reference",
        "payment_amount",
        "currency_raw",
        "currency",
        "payment_date",
    }
)

type Output = BaseModel | dict[str, Any] | ScriptedStep


def _step(output: Output, model_id: str) -> ScriptedStep:
    if isinstance(output, ScriptedStep):
        return output
    usage = LlmUsage(model_id=model_id, input_tokens=100, output_tokens=50, latency_ms=10)
    raw: Any = output  # a dict is validated against the schema when the step is consumed
    result: LlmResult[Any] = LlmResult(
        output=raw, refused=False, stop_reason="end_turn", usage=usage
    )
    return ScriptedStep(result=result)


def scripted_llm(
    outputs: Sequence[Output] | Mapping[str, Sequence[Output]] = (),
    *,
    model_id: str = "replay",
) -> ReplayLlmClient:
    """A replay client that answers with ``outputs`` in call order, or per purpose for a mapping."""
    if isinstance(outputs, Mapping):
        script: Mapping[str, Sequence[ScriptedStep]] = {
            purpose: [_step(o, model_id) for o in steps] for purpose, steps in outputs.items()
        }
        return ReplayLlmClient(model_id=model_id, script=script)
    return ReplayLlmClient(model_id=model_id, script=[_step(o, model_id) for o in outputs])


def make_llm_clients(
    *,
    reader_a: LlmClient | None = None,
    reader_b: LlmClient | None = None,
    adjudicator: LlmClient | None = None,
    workhorse: LlmClient | None = None,
) -> LlmClients:
    """Four roles; any not given is an empty replay client (it fails if it is called)."""
    return LlmClients(
        reader_a=reader_a or ReplayLlmClient(model_id="replay-a"),
        reader_b=reader_b or ReplayLlmClient(model_id="replay-b"),
        adjudicator=adjudicator or ReplayLlmClient(model_id="replay-adjudicator"),
        workhorse=workhorse or ReplayLlmClient(model_id="replay-workhorse"),
    )


def _wrap(value: Any) -> Any:
    if isinstance(value, Extracted):
        return value
    return Extracted(value=value, source=SourceLocation(part_no=1), confidence=DEFAULT_CONFIDENCE)


def _line(number: int, transaction_number: str, amount: str) -> ExtractedLine:
    return ExtractedLine(
        line_no=number,
        kind=LineKind.INVOICE,
        transaction_number=transaction_number,
        amount_paid=Decimal(amount),
        gross_amount=Decimal(amount),
        source=SourceLocation(part_no=1),
        confidence=DEFAULT_CONFIDENCE,
    )


def make_extraction(**overrides: Any) -> RemittanceExtraction:
    """A valid synthetic remittance. Plain override values for wrapper fields are wrapped."""
    data: dict[str, Any] = {
        "payer_name": "Acme Test Payer",
        "payer_bank_account": None,
        "remittance_reference": "REM-0001",
        "payment_amount": Decimal("1250.00"),
        "currency_raw": "USD",
        "currency": "USD",
        "currency_ambiguous": False,
        "dates": [
            DateCandidate(
                value=date(2026, 1, 10),
                kind=DateKind.PAYMENT,
                source=SourceLocation(part_no=1),
                confidence=DEFAULT_CONFIDENCE,
            )
        ],
        "payment_date": date(2026, 1, 10),
        "lines": [_line(1, "INV-1001", "1000.00"), _line(2, "2598014-1", "250.00")],
        "po_refs": [],
        "sales_order_refs": [],
        "ers_refs": [],
        "bank_fees": [],
        "notes": None,
    }
    data.update(overrides)
    for name in _EXTRACTED_FIELDS:
        data[name] = _wrap(data[name])
    return RemittanceExtraction.model_validate(data)
