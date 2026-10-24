"""The replay engine: re-decide past items under live and candidate matching config, side by side.

Read-only by construction. It holds a ``ReadOnlyFusion`` (no write method exists), no event bus
and no reservation service, and it writes only ``LAB_*`` rows. One Fusion read per item feeds
both decisions; the scorer applies each config's own window to the same receipts.
"""

import asyncio
import dataclasses
import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from cashapp.data.models.lab import LabReplayItem
from cashapp.data.repositories.lab import (
    LabReplayItemRepository,
    LabReplayRepository,
)
from cashapp.data.uow import UowFactory
from cashapp.domain import config_keys as ck
from cashapp.domain.clock import Clock
from cashapp.domain.lab import ChangeKind, ReplayOutcome, ReplayStatus, classify_change
from cashapp.domain.money import to_money
from cashapp.integrations.fusion.errors import FusionError
from cashapp.services.config import (
    ConfigSnapshot,
    RuntimeConfig,
    lookup_key,
    validate_value,
)
from cashapp.services.config_groups import MatchingConfig
from cashapp.services.lab.inputs import (
    PastItem,
    ReceiptPool,
    load_past_item,
    read_receipt_pool,
    unique_numbers,
)
from cashapp.services.lab.readonly import ReadOnlyFusion
from cashapp.services.lab.tasks import ProgressEvent, ReplayProgressHub
from cashapp.services.matching.decision import (
    ReceiptMatchDecision,
    decide_lines,
    decide_receipt,
    index_line_transactions,
)

logger = logging.getLogger(__name__)

_BATCH: Final = 20
_ZERO: Final = Decimal("0.00")
_OUTCOME_OF: Final[Mapping[str, ReplayOutcome]] = {
    "none": ReplayOutcome.NO_RECEIPT,
    "ambiguous": ReplayOutcome.AMBIGUOUS,
    "variance": ReplayOutcome.VARIANCE,
}
_ERROR_MAX: Final = 900


def candidate_matching(live: MatchingConfig, changes: Mapping[str, object]) -> MatchingConfig:
    """The live matching config with the candidate's overrides, each through ``validate_value``."""
    fields: dict[str, Any] = {}
    for name, raw in changes.items():
        value = validate_value(lookup_key(name), raw)
        if name == ck.MATCHING_DATE_WINDOW_DAYS.name:
            fields["date_window_days"] = value
        elif name == ck.MATCHING_TOLERANCES.name:
            fields["tolerances"] = value
        elif name == ck.MATCHING_BANK_FEE_BANDS.name:
            fields["bank_fee_bands"] = tuple(value)
        elif name == ck.MATCHING_SCORER_WEIGHTS.name:
            fields["scorer_weights"] = value
        elif name == ck.MATCHING_MIN_SCORE.name:
            fields["min_score"] = value
    return dataclasses.replace(live, **fields)


@dataclass(frozen=True, slots=True)
class SideResult:
    outcome: ReplayOutcome
    receipt_id: int | None
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ItemResult:
    item: PastItem
    before: SideResult
    after: SideResult
    since_applied: bool

    @property
    def kind(self) -> ChangeKind:
        if self.since_applied:
            return ChangeKind.UNCHANGED  # applied since: flagged, never counted as a change
        return classify_change(self.before.outcome, self.after.outcome)

    @property
    def changed(self) -> bool:
        return self.kind is not ChangeKind.UNCHANGED or (
            not self.since_applied
            and ReplayOutcome.NO_INPUT not in (self.before.outcome, self.after.outcome)
            and self.before.receipt_id != self.after.receipt_id
        )


@dataclass(slots=True)
class _Money:
    matched: Decimal = _ZERO
    unmatched: Decimal = _ZERO
    items: int = 0


@dataclass(slots=True)
class Tally:
    done: int = 0
    changed: int = 0
    newly_matched: int = 0
    newly_failed: int = 0
    newly_ambiguous: int = 0
    money: dict[str, _Money] = dataclasses.field(
        default_factory=lambda: defaultdict[str, _Money](_Money)
    )

    def add(self, result: ItemResult) -> None:
        self.done += 1
        if not result.changed:
            return
        self.changed += 1
        kind, currency = result.kind, result.item.currency or "?"
        amount = to_money(result.item.amount) if result.item.amount is not None else _ZERO
        if kind is ChangeKind.NEWLY_MATCHED:
            self.newly_matched += 1
            self.money[currency].matched += amount
            self.money[currency].items += 1
        elif kind is ChangeKind.NEWLY_FAILED:
            self.newly_failed += 1
            self.money[currency].unmatched += amount
            self.money[currency].items += 1
        elif kind is ChangeKind.NEWLY_AMBIGUOUS:
            self.newly_ambiguous += 1
            self.money[currency].unmatched += amount
            self.money[currency].items += 1

    def money_json(self) -> list[dict[str, Any]]:
        """Per currency, never summed across currencies; amounts as 2 dp strings."""
        return [
            {
                "currency": currency,
                "newly_matched": f"{m.matched:.2f}",
                "newly_unmatched": f"{m.unmatched:.2f}",
                "items": m.items,
            }
            for currency, m in sorted(self.money.items())
        ]

    def summary(self) -> dict[str, Any]:
        return {
            "done": self.done,
            "changed": self.changed,
            "newly_matched": self.newly_matched,
            "newly_failed": self.newly_failed,
            "newly_ambiguous": self.newly_ambiguous,
            "money_by_currency": self.money_json(),
        }


def _decision_detail(decision: ReceiptMatchDecision) -> dict[str, Any]:
    qualifying = [c for c in decision.scored.candidates if c.qualifies]
    ranked = sorted((c.score for c in qualifying), reverse=True)
    return {
        "rule": decision.rule,
        "outcome": decision.outcome,
        "candidates": len(decision.scored.candidates),
        "qualifying": len(qualifying),
        "best_score": ranked[0] if ranked else None,
        "winner_receipt_number": decision.winner.receipt.receipt_number
        if decision.winner is not None
        else None,
    }


class ReplayEngine:
    def __init__(
        self,
        uow_factory: UowFactory,
        config: RuntimeConfig,
        fusion: ReadOnlyFusion,
        hub: ReplayProgressHub,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._config = config
        self._fusion = fusion
        self._hub = hub
        self._clock = clock

    # --- one item ---------------------------------------------------------------------------

    async def _lines_outcome(
        self,
        past: PastItem,
        decision: ReceiptMatchDecision,
        config: MatchingConfig,
        found: Sequence[Any],
        applications: dict[int, list[Any]],
    ) -> SideResult:
        winner = decision.winner
        assert winner is not None  # noqa: S101 - only called for a matched receipt decision
        receipt = winner.receipt
        resolution = past.resolution
        assert resolution is not None  # noqa: S101 - a base exists only with a resolution
        if receipt.receipt_id not in applications:
            applications[receipt.receipt_id] = await self._fusion.list_receipt_applications(
                receipt.receipt_id
            )
        owners = resolution.owners()
        transactions, ambiguous = index_line_transactions(found, past.lines, owners)
        plan = decide_lines(
            past.lines,
            transactions,
            owners,
            receipt.unapplied_amount,
            applications[receipt.receipt_id],
            past.currency or receipt.currency,
            config,
            ambiguous=ambiguous,
            header_amount=past.amount,
        )
        detail = _decision_detail(decision)
        detail["steps"] = len(plan.steps)
        detail["line_verdicts"] = len(plan.results)
        outcome = ReplayOutcome.MATCHED if plan.steps else ReplayOutcome.LINES_FAILED
        return SideResult(outcome, receipt.receipt_id, detail)

    async def _side(
        self,
        past: PastItem,
        pool: ReceiptPool,
        config: MatchingConfig,
        found: Sequence[Any],
        applications: dict[int, list[Any]],
    ) -> SideResult:
        assert past.base is not None  # noqa: S101
        decision = decide_receipt(
            past.base, pool.receipts, config, aliases=past.aliases, evidence=pool.evidence
        )
        if decision.outcome != "matched" or decision.winner is None:
            outcome = _OUTCOME_OF.get(decision.outcome, ReplayOutcome.NO_RECEIPT)
            return SideResult(outcome, None, _decision_detail(decision))
        return await self._lines_outcome(past, decision, config, found, applications)

    async def evaluate(
        self, item_id: int, live: MatchingConfig, candidate: MatchingConfig, window_days: int
    ) -> ItemResult:
        past = await load_past_item(self._uow_factory, item_id)
        missing = SideResult(ReplayOutcome.NO_INPUT, None, {"reason": "missing_input"})
        if past.base is None or past.resolution is None:
            return ItemResult(past, missing, missing, False)
        try:
            pool = await read_receipt_pool(
                self._fusion,
                past,
                window_days=max(live.date_window_days, candidate.date_window_days),
            )
            found = (
                await self._fusion.find_transactions(unique_numbers(past.lines))
                if past.lines
                else []
            )
            applications: dict[int, list[Any]] = {}
            before = await self._side(past, pool, live, found, applications)
            after = await self._side(past, pool, candidate, found, applications)
        except FusionError as exc:
            # A read that failed is this item's outcome, never the run's, and never retried.
            err = SideResult(
                ReplayOutcome.NO_INPUT, None, {"reason": "fusion_error", "code": exc.code.value}
            )
            return ItemResult(past, err, err, False)
        return ItemResult(past, before, after, pool.since_applied)

    # --- the run ---------------------------------------------------------------------------

    async def run(
        self,
        replay_id: int,
        item_ids: Sequence[int],
        changes: Mapping[str, object],
        window_days: int,
    ) -> None:
        started = self._clock.now()
        tally = Tally()
        total = len(item_ids)
        try:
            snapshot: ConfigSnapshot = await self._config.snapshot()
            live = snapshot.matching()
            candidate = candidate_matching(live, changes)
            limit = max(1, snapshot.get(ck.LAB_MAX_CONCURRENCY))
            gate = asyncio.Semaphore(limit)

            async def one(item_id: int) -> ItemResult:
                async with gate:
                    return await self.evaluate(item_id, live, candidate, window_days)

            for start in range(0, total, _BATCH):
                batch = item_ids[start : start + _BATCH]
                results = await asyncio.gather(*(one(i) for i in batch))
                for result in results:
                    tally.add(result)
                await self._persist_batch(replay_id, results, tally, total)
                self._hub.publish(
                    replay_id,
                    ProgressEvent(
                        "progress",
                        {
                            "replay_id": replay_id,
                            "status": ReplayStatus.RUNNING.value,
                            "done": tally.done,
                            "total": total,
                        },
                    ),
                )
            await self._finish(replay_id, ReplayStatus.DONE, tally, total, started, None)
        except asyncio.CancelledError:
            await self._finish(replay_id, ReplayStatus.FAILED, tally, total, started, "cancelled")
            raise
        except Exception as exc:
            logger.exception("lab replay failed: replay_id=%d", replay_id)
            message = f"{type(exc).__name__}: {exc}"[:_ERROR_MAX]
            await self._finish(replay_id, ReplayStatus.FAILED, tally, total, started, message)

    async def _persist_batch(
        self, replay_id: int, results: Sequence[ItemResult], tally: Tally, total: int
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.repo(LabReplayItemRepository).add_many(
                [
                    LabReplayItem(
                        replay_id=replay_id,
                        work_item_id=r.item.item_id,
                        amount=r.item.amount,
                        currency=r.item.currency,
                        before_outcome=r.before.outcome.value,
                        after_outcome=r.after.outcome.value,
                        before_receipt_id=r.before.receipt_id,
                        after_receipt_id=r.after.receipt_id,
                        changed=r.changed,
                        since_applied=r.since_applied,
                        detail={"before": r.before.detail, "after": r.after.detail},
                    )
                    for r in results
                ]
            )
            await uow.repo(LabReplayRepository).mark_progress(
                replay_id, tally.done, total, self._clock.now()
            )
            await uow.commit()

    async def _finish(
        self,
        replay_id: int,
        status: ReplayStatus,
        tally: Tally,
        total: int,
        started: datetime,
        error: str | None,
    ) -> None:
        now = self._clock.now()
        duration_ms = int((now - started).total_seconds() * 1000)
        summary = tally.summary()
        summary["total"] = total
        async with self._uow_factory() as uow:
            await uow.repo(LabReplayRepository).finish(
                replay_id, status, summary, now, duration_ms, error
            )
            await uow.commit()
        if status is ReplayStatus.DONE:
            event = ProgressEvent(
                "done",
                {
                    "replay_id": replay_id,
                    "status": status.value,
                    "done": tally.done,
                    "total": total,
                    "changed": tally.changed,
                    "newly_matched": tally.newly_matched,
                    "newly_failed": tally.newly_failed,
                    "newly_ambiguous": tally.newly_ambiguous,
                    "duration_ms": duration_ms,
                },
            )
        else:
            event = ProgressEvent(
                "failed",
                {"replay_id": replay_id, "status": status.value, "message": error or "failed"},
            )
        self._hub.publish(replay_id, event)
