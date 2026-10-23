"""Request and response schemas for the matching lab endpoints."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from cashapp.domain.lab import CandidateStatus, ReplayOutcome, ReplayStatus
from cashapp.domain.money import MoneyStr
from cashapp.services.lab.service import (
    Candidate,
    CandidateList,
    ConfigDiff,
    MoneyByCurrency,
    Promotion,
    Replay,
    ReplayItemView,
    ReplayResult,
    ReplaySummary,
)

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Rationale = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class CandidateCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: Annotated[dict[str, JsonValue], Field(min_length=1)]
    rationale: Rationale


class ReplayStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_days: int | None = None


class PromoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replay_id: str
    reason: Reason
    expected_version: Annotated[int, Field(ge=0, strict=True)]


class DiscardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class ConfigDiffRow(BaseModel):
    key: str
    before: JsonValue
    after: JsonValue

    @classmethod
    def of(cls, diff: ConfigDiff) -> "ConfigDiffRow":
        return cls(key=diff.key, before=diff.before, after=diff.after)


class ReplaySummaryOut(BaseModel):
    id: str
    status: ReplayStatus
    done: int
    total: int

    @classmethod
    def of(cls, summary: ReplaySummary) -> "ReplaySummaryOut":
        return cls(id=summary.id, status=summary.status, done=summary.done, total=summary.total)


class CandidateOut(BaseModel):
    id: str
    status: CandidateStatus
    base_version: int
    live_version: int
    changes: dict[str, JsonValue]
    config_diff: list[ConfigDiffRow]
    rationale: str
    created_by: str
    created_by_name: str
    created_at: datetime
    latest_replay: ReplaySummaryOut | None
    promoted_version: int | None

    @classmethod
    def of(cls, candidate: Candidate) -> "CandidateOut":
        return cls(
            id=candidate.id,
            status=candidate.status,
            base_version=candidate.base_version,
            live_version=candidate.live_version,
            changes=dict(candidate.changes),
            config_diff=[ConfigDiffRow.of(d) for d in candidate.config_diff],
            rationale=candidate.rationale,
            created_by=candidate.created_by,
            created_by_name=candidate.created_by_name,
            created_at=candidate.created_at,
            latest_replay=ReplaySummaryOut.of(candidate.latest_replay)
            if candidate.latest_replay is not None
            else None,
            promoted_version=candidate.promoted_version,
        )


class CandidateListOut(BaseModel):
    items: list[CandidateOut]
    open_count: int
    live_version: int

    @classmethod
    def of(cls, listing: CandidateList) -> "CandidateListOut":
        return cls(
            items=[CandidateOut.of(c) for c in listing.items],
            open_count=listing.open_count,
            live_version=listing.live_version,
        )


class ReplayStartOut(BaseModel):
    id: str
    candidate_id: str
    status: Literal["RUNNING"]
    total: int

    @classmethod
    def of(cls, replay: Replay) -> "ReplayStartOut":
        return cls(
            id=replay.id, candidate_id=replay.candidate_id, status="RUNNING", total=replay.total
        )


class LabMoneyByCurrencyOut(BaseModel):
    currency: str
    newly_matched: MoneyStr
    newly_unmatched: MoneyStr
    items: int

    @classmethod
    def of(cls, row: MoneyByCurrency) -> "LabMoneyByCurrencyOut":
        return cls.model_validate(
            {
                "currency": row.currency,
                "newly_matched": row.newly_matched,
                "newly_unmatched": row.newly_unmatched,
                "items": row.items,
            }
        )


class ReplayItemOut(BaseModel):
    item_id: int
    amount: MoneyStr | None
    currency: str | None
    before: ReplayOutcome
    after: ReplayOutcome
    receipt_before: int | None
    receipt_after: int | None
    since_applied: bool

    @classmethod
    def of(cls, item: ReplayItemView) -> "ReplayItemOut":
        return cls(
            item_id=item.item_id,
            amount=item.amount,
            currency=item.currency,
            before=item.before,
            after=item.after,
            receipt_before=item.receipt_before,
            receipt_after=item.receipt_after,
            since_applied=item.since_applied,
        )


class ReplayResultOut(BaseModel):
    id: str
    candidate_id: str
    status: ReplayStatus
    window_days: int
    live_version: int
    base_version: int
    done: int
    total: int
    changed: int
    newly_matched: int
    newly_failed: int
    newly_ambiguous: int
    money_by_currency: list[LabMoneyByCurrencyOut]
    items: list[ReplayItemOut]
    config_diff: list[ConfigDiffRow]
    duration_ms: int | None
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    stale_message: str | None

    @classmethod
    def of(cls, result: ReplayResult) -> "ReplayResultOut":
        return cls(
            id=result.id,
            candidate_id=result.candidate_id,
            status=result.status,
            window_days=result.window_days,
            live_version=result.live_version,
            base_version=result.base_version,
            done=result.done,
            total=result.total,
            changed=result.changed,
            newly_matched=result.newly_matched,
            newly_failed=result.newly_failed,
            newly_ambiguous=result.newly_ambiguous,
            money_by_currency=[LabMoneyByCurrencyOut.of(m) for m in result.money_by_currency],
            items=[ReplayItemOut.of(i) for i in result.items],
            config_diff=[ConfigDiffRow.of(d) for d in result.config_diff],
            duration_ms=result.duration_ms,
            started_at=result.started_at,
            finished_at=result.finished_at,
            error=result.error,
            stale_message=result.stale_message,
        )


class PromoteOut(BaseModel):
    candidate_id: str
    replay_id: str
    new_version: int
    keys: list[str]
    promoted_by: str
    promoted_at: datetime

    @classmethod
    def of(cls, promotion: Promotion) -> "PromoteOut":
        return cls(
            candidate_id=promotion.candidate_id,
            replay_id=promotion.replay_id,
            new_version=promotion.new_version,
            keys=promotion.keys,
            promoted_by=promotion.promoted_by,
            promoted_at=promotion.promoted_at,
        )


class ReplayStreamFrameOut(BaseModel):
    """Documents the SSE payloads: ``progress``, ``done`` and ``failed`` carry subsets of this."""

    replay_id: str
    status: ReplayStatus
    done: int | None = None
    total: int | None = None
    changed: int | None = None
    newly_matched: int | None = None
    newly_failed: int | None = None
    newly_ambiguous: int | None = None
    duration_ms: int | None = None
    message: str | None = None
