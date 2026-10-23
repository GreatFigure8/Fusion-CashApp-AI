"""Builders for adjudication tests: a decision over two readings and seeded reader rows."""

from typing import Any

from cashapp.data.models.extraction_reading import ExtractionReading
from cashapp.data.repositories.readings import ExtractionReadingRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.adjudication import (
    HEADER_FIELDS,
    AdjudicatorDecision,
    FieldChoice,
    LineChoice,
    ModelSource,
)
from cashapp.domain.extraction import (
    SCHEMA_VERSION,
    ReaderSlot,
    ReadingStatus,
    RemittanceExtraction,
)

_MODELS = {ReaderSlot.A: "claude-opus-5-5", ReaderSlot.B: "cohere.command-a-vision"}


def make_adjudicator_decision(
    a: RemittanceExtraction, b: RemittanceExtraction | None = None, **overrides: Any
) -> AdjudicatorDecision:
    """Default: final is A, every source is "A" ("both" where A and B agree), confidence 0.95."""
    field_choices: list[FieldChoice] = []
    for name in HEADER_FIELDS:
        same = b is not None and getattr(a, name) == getattr(b, name)
        source: ModelSource = "both" if same else "A"
        field_choices.append(FieldChoice(field_path=name, source=source))
    line_choices: list[LineChoice] = []
    for line in a.lines:
        in_b = b is not None and any(other.model_dump() == line.model_dump() for other in b.lines)
        line_choices.append(LineChoice(line_no=line.line_no, source="both" if in_b else "A"))
    values: dict[str, Any] = {
        "final": a,
        "field_choices": field_choices,
        "line_choices": line_choices,
        "disagreements": [],
        "confidence": 0.95,
    }
    values.update(overrides)
    return AdjudicatorDecision(**values)


async def seed_readings(
    uow: UnitOfWork,
    item_id: int,
    *,
    a: RemittanceExtraction | ReadingStatus | None,
    b: RemittanceExtraction | ReadingStatus | None,
    attempt: int = 1,
) -> dict[ReaderSlot, ExtractionReading]:
    """Insert one reading row per given slot (None skips the slot, a status makes a bare row)."""
    repo = uow.repo(ExtractionReadingRepository)
    rows: dict[ReaderSlot, ExtractionReading] = {}
    for slot, given in ((ReaderSlot.A, a), (ReaderSlot.B, b)):
        if given is None:
            continue
        ok = isinstance(given, RemittanceExtraction)
        rows[slot] = await repo.add(
            ExtractionReading(
                work_item_id=item_id,
                reader=slot,
                model_id=_MODELS[slot],
                prompt_version="1",
                schema_version=SCHEMA_VERSION,
                status=ReadingStatus.OK if ok else given,
                output=given.model_dump(mode="json") if ok else None,
                attempt=attempt,
            )
        )
    return rows
