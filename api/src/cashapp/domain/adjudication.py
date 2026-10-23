"""The adjudicator's decision and the stored result that traces every value to a reader.

``AdjudicatorDecision`` is what the model returns (provenance as lists, because structured outputs
need ``additionalProperties: false`` on every object). ``AdjudicationResult`` is what is stored and
read by later stations: the final extraction, a source for every header field and line, the
disagreements and a confidence. ``human`` is a source only code may write.
"""

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from statistics import fmean
from typing import Annotated, Any, Final, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field

from cashapp.domain import adjudication_text as text
from cashapp.domain.extraction import (
    ExtractedLine,
    ReaderSlot,
    RemittanceExtraction,
)
from cashapp.domain.money import money_eq, to_money

ADJUDICATION_SCHEMA_VERSION: Final = "1"
SINGLE_READER_CONFIDENCE_FACTOR: Final = 0.8

Source = Literal["A", "B", "both", "human"]
ModelSource = Literal["A", "B", "both"]

_REASON_MAX: Final = 300
_UPPER_FIELDS: Final = frozenset({"currency"})
# Free text: a combined note is not a fact the matcher relies on.
_FREE_TEXT_FIELDS: Final = frozenset({"notes"})

HEADER_FIELDS: Final[tuple[str, ...]] = tuple(
    name for name in RemittanceExtraction.model_fields if name != "lines"
)


class AdjudicationOrigin(StrEnum):
    MODEL = "MODEL"
    HUMAN = "HUMAN"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldChoice(_Strict):
    field_path: Annotated[str, Field(description=text.DESC_FIELD_PATH)]
    source: Annotated[ModelSource, Field(description=text.DESC_SOURCE_CHOICE)]


class LineChoice(_Strict):
    line_no: Annotated[int, Field(description=text.DESC_LINE_NO)]
    source: Annotated[ModelSource, Field(description=text.DESC_SOURCE_CHOICE)]


class LineProvenance(_Strict):
    line_no: int
    source: Source


class ModelDisagreement(_Strict):
    """A disagreement as the model reports it: it can only have chosen A, B or both."""

    field_path: Annotated[str, Field(description=text.DESC_DISAGREEMENT_PATH)]
    value_a: Annotated[str | None, Field(description=text.DESC_VALUE_A)]
    value_b: Annotated[str | None, Field(description=text.DESC_VALUE_B)]
    chosen: Annotated[ModelSource, Field(description=text.DESC_CHOSEN)]
    reason: Annotated[str, Field(max_length=_REASON_MAX, description=text.DESC_REASON)]


class Disagreement(_Strict):
    field_path: str
    value_a: str | None
    value_b: str | None
    chosen: Source
    reason: Annotated[str, Field(max_length=_REASON_MAX)]


class AdjudicatorDecision(_Strict):
    final: Annotated[RemittanceExtraction, Field(description=text.DESC_FINAL)]
    field_choices: Annotated[list[FieldChoice], Field(description=text.DESC_FIELD_CHOICES)]
    line_choices: Annotated[list[LineChoice], Field(description=text.DESC_LINE_CHOICES)]
    disagreements: Annotated[list[ModelDisagreement], Field(description=text.DESC_DISAGREEMENTS)]
    confidence: Annotated[float, Field(ge=0, le=1, description=text.DESC_DECISION_CONFIDENCE)]


class AdjudicationResult(_Strict):
    final: RemittanceExtraction
    provenance: dict[str, Source]
    line_provenance: list[LineProvenance]
    disagreements: list[Disagreement]
    confidence: Annotated[float, Field(ge=0, le=1)]

    @classmethod
    def from_decision(cls, decision: AdjudicatorDecision) -> Self:
        return cls(
            final=decision.final,
            provenance={c.field_path: c.source for c in decision.field_choices},
            line_provenance=[
                LineProvenance(line_no=c.line_no, source=c.source) for c in decision.line_choices
            ],
            disagreements=[Disagreement(**d.model_dump()) for d in decision.disagreements],
            confidence=decision.confidence,
        )

    @classmethod
    def from_stored(
        cls,
        *,
        final: Mapping[str, Any],
        provenance: Mapping[str, Any],
        disagreements: Sequence[Mapping[str, Any]] | None,
        confidence: float | Decimal,
    ) -> Self:
        return cls(
            final=RemittanceExtraction.model_validate(final),
            provenance=dict(provenance.get("fields", {})),
            line_provenance=[LineProvenance(**row) for row in provenance.get("lines", [])],
            disagreements=[Disagreement(**row) for row in (disagreements or [])],
            confidence=float(confidence),
        )

    def provenance_json(self) -> dict[str, Any]:
        """The stored PROVENANCE document: header sources and line sources in one column."""
        return {
            "fields": dict(self.provenance),
            "lines": [row.model_dump() for row in self.line_provenance],
        }


def _line_rows(lines: Sequence[ExtractedLine], source: Source) -> list[LineProvenance]:
    return [LineProvenance(line_no=line.line_no, source=source) for line in lines]


def single_reader_result(reading: RemittanceExtraction, slot: ReaderSlot) -> AdjudicationResult:
    """The result when only one reader produced a usable reading: no comparison, no model call."""
    source: Source = "A" if slot is ReaderSlot.A else "B"
    confidences = list(reading.field_confidences().values())
    mean = fmean(confidences) if confidences else 0.0
    return AdjudicationResult(
        final=reading,
        provenance=dict.fromkeys(HEADER_FIELDS, source),
        line_provenance=_line_rows(reading.lines, source),
        disagreements=[],
        confidence=round(mean * SINGLE_READER_CONFIDENCE_FACTOR, 4),
    )


def human_result(final: RemittanceExtraction) -> AdjudicationResult:
    """A person's corrected extraction: every value is theirs, confidence 1."""
    return AdjudicationResult(
        final=final,
        provenance=dict.fromkeys(HEADER_FIELDS, "human"),
        line_provenance=_line_rows(final.lines, "human"),
        disagreements=[],
        confidence=1.0,
    )


# --- grounding ------------------------------------------------------------------------------


def _norm(name: str, value: Any) -> Any:
    """A hashable, comparable form of a value: stripped strings, upper-case currency, 2 dp money."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        return str(to_money(value))
    if isinstance(value, str):
        stripped = value.strip()
        return stripped.upper() if name in _UPPER_FIELDS else stripped
    if isinstance(value, BaseModel):
        return _norm(name, value.model_dump(mode="json"))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _norm(name, dataclasses.asdict(value))
    if isinstance(value, Mapping):
        mapping = cast("Mapping[Any, Any]", value)
        return tuple(sorted((str(k), _norm(name, v)) for k, v in mapping.items()))
    if isinstance(value, list | tuple | set | frozenset):
        items = cast("Iterable[Any]", value)
        return frozenset(_norm(name, v) for v in items)
    return value


def _header_value(name: str, extraction: RemittanceExtraction) -> Any:
    """The comparable value of a header field: an Extracted compares its value only."""
    value: Any = getattr(extraction, name)
    if name == "dates":
        return frozenset((c.value.isoformat(), c.kind.value) for c in extraction.dates)
    if isinstance(value, list):
        return _norm(name, cast("list[Any]", value))
    if isinstance(value, BaseModel) and hasattr(value, "confidence"):
        return _norm(name, getattr(value, "value", None))  # Extracted[...]
    return _norm(name, value)


def _header_grounded(
    name: str,
    final: RemittanceExtraction,
    source: Source,
    a: RemittanceExtraction,
    b: RemittanceExtraction,
) -> bool:
    if source == "human":
        return True
    if name in _FREE_TEXT_FIELDS and source == "both":
        return True
    value = _header_value(name, final)
    value_a = _header_value(name, a)
    value_b = _header_value(name, b)
    if source == "A":
        return value == value_a
    if source == "B":
        return value == value_b
    if isinstance(value, frozenset):
        # A combined list may take items from either reading.
        return value <= (value_a | value_b)
    return value in (value_a, value_b)


def _line_matches(line: ExtractedLine, candidates: Sequence[ExtractedLine]) -> bool:
    for other in candidates:
        if line.kind != other.kind:
            continue
        if line.transaction_number.strip() != other.transaction_number.strip():
            continue
        if line.amount_paid is None or other.amount_paid is None:
            if line.amount_paid is None and other.amount_paid is None:
                return True
            continue
        if money_eq(line.amount_paid, other.amount_paid):
            return True
    return False


def check_grounding(
    result: AdjudicationResult, a: RemittanceExtraction, b: RemittanceExtraction
) -> list[str]:
    """The field paths whose final value neither reader produced, or that have no provenance."""
    violations: list[str] = []
    for name in HEADER_FIELDS:
        source = result.provenance.get(name)
        if source is None or not _header_grounded(name, result.final, source, a, b):
            violations.append(name)
    line_sources = {row.line_no: row.source for row in result.line_provenance}
    for index, line in enumerate(result.final.lines):
        path = f"lines[{index}]"
        source = line_sources.get(line.line_no)
        if source is None:
            violations.append(path)
        elif source == "human":
            continue
        else:
            pool = {"A": a.lines, "B": b.lines, "both": [*a.lines, *b.lines]}[source]
            if not _line_matches(line, pool):
                violations.append(path)
    return violations
