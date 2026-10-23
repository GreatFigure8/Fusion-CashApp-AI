"""Human correction of an extraction: the one writer of ``ORIGIN=HUMAN`` adjudication rows."""

from decimal import Decimal

from cashapp.data.models.adjudication import Adjudication
from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.adjudication import (
    ADJUDICATION_SCHEMA_VERSION,
    AdjudicationOrigin,
    human_result,
)
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.extraction import RemittanceExtraction
from cashapp.domain.principal import Principal
from cashapp.domain.work_item import ActorKind, HistoryAction
from cashapp.services.history import HistoryEntry, record_history


def _changed_paths(previous: RemittanceExtraction | None, new: RemittanceExtraction) -> list[str]:
    """Field paths that differ from the previous final extraction (paths only, never values)."""
    new_dump = new.model_dump(mode="json")
    if previous is None:
        return [
            *(k for k in new_dump if k != "lines"),
            *(f"lines[{i}]" for i in range(len(new.lines))),
        ]
    old_dump = previous.model_dump(mode="json")
    paths = [k for k in new_dump if k != "lines" and new_dump[k] != old_dump.get(k)]
    old_lines = old_dump["lines"]
    new_lines = new_dump["lines"]
    for index in range(max(len(old_lines), len(new_lines))):
        old_line = old_lines[index] if index < len(old_lines) else None
        new_line = new_lines[index] if index < len(new_lines) else None
        if old_line != new_line:
            paths.append(f"lines[{index}]")
    return paths


async def save_human_correction(
    uow: UnitOfWork,
    item_id: int,
    final: RemittanceExtraction,
    principal: Principal,
    *,
    clock: Clock | None = None,
) -> Adjudication:
    """Store a person's corrected extraction as the item's current one.

    Flushes only: the caller (the requeue service) owns the transaction.
    """
    if principal.is_system:
        raise ValueError("A human correction needs a human principal")
    clock = clock or SystemClock()
    repo = uow.repo(AdjudicationRepository)
    previous = await repo.latest_for(item_id)
    previous_final: RemittanceExtraction | None = None
    if previous is not None and previous.final is not None:
        previous_final = RemittanceExtraction.model_validate(previous.final)

    result = human_result(final)
    row = await repo.add(
        Adjudication(
            work_item_id=item_id,
            origin=AdjudicationOrigin.HUMAN,
            model_id=None,
            prompt_version=None,
            schema_version=ADJUDICATION_SCHEMA_VERSION,
            reading_a_id=previous.reading_a_id if previous is not None else None,
            reading_b_id=previous.reading_b_id if previous is not None else None,
            missing_reader=previous.missing_reader if previous is not None else None,
            final=final.model_dump(mode="json"),
            provenance=result.provenance_json(),
            disagreements=[],
            confidence=Decimal("1.0000"),
            edited_by=principal.subject,
            created_at=clock.now(),
        )
    )
    await record_history(
        uow,
        item_id,
        HistoryEntry(
            action=HistoryAction.HUMAN_ACTION,
            actor_kind=ActorKind.USER,
            actor_id=principal.subject,
            actor_name=principal.display_name,
            reasoning="extraction corrected",
            payload={
                "adjudication_id": row.id,
                "changed_fields": _changed_paths(previous_final, final),
            },
        ),
        clock=clock,
    )
    return row
