"""The matching lab service: propose, replay, promote, discard.

Owns its transactions and takes the ``Principal`` as an argument. A candidate is a set of
proposed ``matching.*`` values kept apart from live config. A replay re-decides past items under
both and never writes to Fusion. Promote goes through the same ``ConfigWriter`` as
``PUT /config/{key}``, with the candidate and replay ids recorded on the history rows.
"""

import asyncio
import contextlib
import datetime
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from pydantic import JsonValue

from cashapp.data.models.lab import LabCandidate, LabReplay, LabReplayItem
from cashapp.data.repositories.config import ConfigChangeRepository
from cashapp.data.repositories.lab import (
    LabCandidateRepository,
    LabPastItemRepository,
    LabReplayItemRepository,
    LabReplayRepository,
)
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain import config_keys as ck
from cashapp.domain.clock import Clock
from cashapp.domain.lab import (
    LAB_KEYS,
    RATIONALE_MAX,
    CandidateStatus,
    ReplayOutcome,
    ReplayStatus,
    bound_errors,
    format_candidate_id,
    format_replay_id,
    parse_candidate_id,
    parse_replay_id,
)
from cashapp.domain.principal import Permission, Principal
from cashapp.integrations.fusion.client import FusionClient
from cashapp.services.config import (
    ChangeTag,
    ConfigConflict,
    ConfigForbidden,
    ConfigValidationError,
    ConfigWriter,
    KeyChange,
    RuntimeConfig,
    list_config_entries,
    lookup_key,
    to_json,
    validate_value,
)
from cashapp.services.lab.csv import CsvRow, replay_items_csv
from cashapp.services.lab.errors import (
    LabCandidateClosed,
    LabCandidateNotFound,
    LabForbidden,
    LabInvalidId,
    LabInvalidValue,
    LabKeyNotAllowed,
    LabOutOfBounds,
    LabReasonRequired,
    LabReplayNotDone,
    LabReplayNotFound,
    LabReplayRunning,
    LabStale,
    LabWindowOutOfRange,
)
from cashapp.services.lab.readonly import ReadOnlyFusion
from cashapp.services.lab.replay import ReplayEngine
from cashapp.services.lab.tasks import (
    BOOT_ID,
    HEARTBEAT_STALE_SECONDS,
    LabTaskRegistry,
    ProgressEvent,
)

__all__ = [
    "Candidate",
    "CandidateList",
    "ConfigDiff",
    "LabService",
    "MoneyByCurrency",
    "ProgressEvent",
    "Promotion",
    "Replay",
    "ReplayItemView",
    "ReplayResult",
    "ReplaySummary",
]

ITEMS_IN_RESULT: Final = 200
_CSV_PAGE: Final = 500
_STREAM_POLL_SECONDS: Final = 2.0


# --------------------------------------------------------------------------- result types


@dataclass(frozen=True, slots=True)
class ConfigDiff:
    key: str
    before: JsonValue
    after: JsonValue


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    id: str
    status: ReplayStatus
    done: int
    total: int


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    status: CandidateStatus
    base_version: int
    live_version: int
    changes: Mapping[str, JsonValue]
    config_diff: list[ConfigDiff]
    rationale: str
    created_by: str
    created_by_name: str
    created_at: datetime.datetime
    latest_replay: ReplaySummary | None
    promoted_version: int | None


@dataclass(frozen=True, slots=True)
class CandidateList:
    items: list[Candidate]
    open_count: int
    live_version: int


@dataclass(frozen=True, slots=True)
class Replay:
    id: str
    candidate_id: str
    status: ReplayStatus
    total: int


@dataclass(frozen=True, slots=True)
class MoneyByCurrency:
    currency: str
    newly_matched: str
    newly_unmatched: str
    items: int


@dataclass(frozen=True, slots=True)
class ReplayItemView:
    item_id: int
    amount: Decimal | None
    currency: str | None
    before: ReplayOutcome
    after: ReplayOutcome
    receipt_before: int | None
    receipt_after: int | None
    since_applied: bool


@dataclass(frozen=True, slots=True)
class ReplayResult:
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
    money_by_currency: list[MoneyByCurrency]
    items: list[ReplayItemView]
    config_diff: list[ConfigDiff]
    duration_ms: int | None
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    error: str | None
    stale_message: str | None


@dataclass(frozen=True, slots=True)
class Promotion:
    candidate_id: str
    replay_id: str
    new_version: int
    keys: list[str]
    promoted_by: str
    promoted_at: datetime.datetime


# --------------------------------------------------------------------------- helpers


def _need(principal: Principal, permission: Permission) -> None:
    if not principal.can(permission):
        raise LabForbidden(
            f"Missing permission {permission.value}", details=[{"permission": permission.value}]
        )


def _candidate_number(value: str) -> int:
    number = parse_candidate_id(value)
    if number is None:
        raise LabInvalidId(f"{value!r} is not a candidate id")
    return number


def _replay_number(value: str) -> int:
    number = parse_replay_id(value)
    if number is None:
        raise LabInvalidId(f"{value!r} is not a replay id")
    return number


def _diff(candidate: LabCandidate) -> list[ConfigDiff]:
    return [
        ConfigDiff(key=key, before=candidate.base_values.get(key), after=value)
        for key, value in candidate.changes.items()
    ]


def _terminal(replay: LabReplay) -> bool:
    return replay.status is not ReplayStatus.RUNNING


class LabService:
    def __init__(
        self,
        uow_factory: UowFactory,
        config: RuntimeConfig,
        fusion: FusionClient,
        tasks: LabTaskRegistry,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._config = config
        self._fusion = ReadOnlyFusion(fusion)
        self._tasks = tasks
        self._clock = clock
        self._writer = ConfigWriter(clock)

    # --- reads shared by several methods -----------------------------------------------------

    @staticmethod
    async def _live_version(uow: UnitOfWork) -> int:
        return await uow.repo(ConfigChangeRepository).lab_version(LAB_KEYS)

    def _summary(self, replay: LabReplay, live_version: int) -> ReplaySummary:
        return ReplaySummary(
            id=format_replay_id(replay.id),
            status=self._effective_status(replay, live_version),
            done=replay.done,
            total=replay.total,
        )

    @staticmethod
    def _effective_status(replay: LabReplay, live_version: int) -> ReplayStatus:
        if replay.status is ReplayStatus.DONE and replay.live_version != live_version:
            return ReplayStatus.STALE
        return replay.status

    def _candidate_out(
        self, row: LabCandidate, live_version: int, latest: LabReplay | None
    ) -> Candidate:
        return Candidate(
            id=format_candidate_id(row.id),
            status=row.status,
            base_version=row.base_version,
            live_version=live_version,
            changes=dict(row.changes),
            config_diff=_diff(row),
            rationale=row.rationale,
            created_by=row.created_by,
            created_by_name=row.created_by_name,
            created_at=row.created_at,
            latest_replay=self._summary(latest, live_version) if latest is not None else None,
            promoted_version=row.promoted_version,
        )

    async def _fail_lost_run(self, uow: UnitOfWork, replay: LabReplay) -> LabReplay:
        """A RUNNING replay whose runner is gone (restart) is reported and persisted as FAILED."""
        if replay.status is not ReplayStatus.RUNNING or self._tasks.is_running(replay.id):
            return replay
        now = self._clock.now()
        if (now - replay.heartbeat_at).total_seconds() <= HEARTBEAT_STALE_SECONDS:
            return replay
        await uow.repo(LabReplayRepository).finish(
            replay.id,
            ReplayStatus.FAILED,
            {},
            now,
            int((now - replay.started_at).total_seconds() * 1000),
            "The replay stopped before it finished (the service restarted).",
        )
        await uow.commit()
        refreshed = await uow.repo(LabReplayRepository).get_for_update(replay.id)
        return refreshed if refreshed is not None else replay

    async def _load_replay(self, uow: UnitOfWork, replay_id: str) -> tuple[LabReplay, LabCandidate]:
        number = _replay_number(replay_id)
        replay = await uow.repo(LabReplayRepository).get(number)
        if replay is None:
            raise LabReplayNotFound(f"No replay {replay_id}")
        replay = await self._fail_lost_run(uow, replay)
        candidate = await uow.repo(LabCandidateRepository).get(replay.candidate_id)
        if candidate is None:
            raise LabReplayNotFound(f"No replay {replay_id}")
        return replay, candidate

    # --- candidates ---------------------------------------------------------------------------

    async def create_candidate(
        self, changes: Mapping[str, object], rationale: str, principal: Principal
    ) -> Candidate:
        _need(principal, Permission.LAB_RUN)
        text = rationale.strip()
        if not text or len(text) > RATIONALE_MAX:
            raise LabReasonRequired(f"A rationale of 1 to {RATIONALE_MAX} characters is required")
        if not changes:
            raise LabInvalidValue("A candidate needs at least one change")
        refused = sorted(k for k in changes if k not in LAB_KEYS)
        if refused:
            raise LabKeyNotAllowed(
                f"Only matching settings can be proposed: {', '.join(refused)}",
                details=[{"key": k} for k in refused],
            )
        cleaned: dict[str, JsonValue] = {}
        for name, raw in changes.items():
            key = lookup_key(name)
            try:
                json_value = to_json(key, validate_value(key, raw))
            except ConfigValidationError as exc:
                raise LabInvalidValue(str(exc), details=exc.errors) from exc
            violations = bound_errors(name, json_value)
            if violations:
                raise LabOutOfBounds(
                    f"{name} is outside the lab's bounds",
                    details=[{"key": name, "msg": v} for v in violations],
                )
            cleaned[name] = json_value
        async with self._uow_factory() as uow:
            entries = {e.key: e for e in await list_config_entries(uow)}
            live = {k: entries[k].value for k in cleaned}
            unchanged = sorted(k for k in cleaned if cleaned[k] == live[k])
            if unchanged:
                raise LabInvalidValue(
                    f"No change from live config: {', '.join(unchanged)}",
                    details=[{"key": k} for k in unchanged],
                )
            row = await uow.repo(LabCandidateRepository).add(
                LabCandidate(
                    changes=cleaned,
                    base_version=await self._live_version(uow),
                    base_key_versions={k: entries[k].version for k in cleaned},
                    base_values=live,
                    rationale=text,
                    status=CandidateStatus.OPEN,
                    created_by=principal.subject,
                    created_by_name=principal.display_name,
                    created_at=self._clock.now(),
                )
            )
            version = row.base_version
            await uow.commit()
        return self._candidate_out(row, version, None)

    async def list_candidates(
        self, principal: Principal, *, limit: int = 20, status: CandidateStatus | None = None
    ) -> CandidateList:
        _need(principal, Permission.LAB_RUN)
        async with self._uow_factory() as uow:
            rows = await uow.repo(LabCandidateRepository).list_recent(limit, status=status)
            latest = await uow.repo(LabReplayRepository).latest_for_candidates([r.id for r in rows])
            open_count = await uow.repo(LabCandidateRepository).count_open()
            live = await self._live_version(uow)
        return CandidateList(
            items=[self._candidate_out(r, live, latest.get(r.id)) for r in rows],
            open_count=open_count,
            live_version=live,
        )

    async def get_candidate(self, candidate_id: str, principal: Principal) -> Candidate:
        _need(principal, Permission.LAB_RUN)
        number = _candidate_number(candidate_id)
        async with self._uow_factory() as uow:
            row = await uow.repo(LabCandidateRepository).get(number)
            if row is None:
                raise LabCandidateNotFound(f"No candidate {candidate_id}")
            latest = await uow.repo(LabReplayRepository).latest_for(number)
            live = await self._live_version(uow)
        return self._candidate_out(row, live, latest)

    async def discard(
        self, candidate_id: str, principal: Principal, reason: str | None = None
    ) -> Candidate:
        _need(principal, Permission.LAB_RUN)
        number = _candidate_number(candidate_id)
        async with self._uow_factory() as uow:
            row = await uow.repo(LabCandidateRepository).get_for_update(number)
            if row is None:
                raise LabCandidateNotFound(f"No candidate {candidate_id}")
            if row.status is not CandidateStatus.OPEN:
                raise LabCandidateClosed(f"Candidate {candidate_id} is already {row.status.value}")
            row.status = CandidateStatus.DISCARDED
            row.closed_by = principal.subject
            row.closed_at = self._clock.now()
            row.close_reason = reason.strip()[:1000] if reason and reason.strip() else None
            await uow.session.flush()
            latest = await uow.repo(LabReplayRepository).latest_for(number)
            live = await self._live_version(uow)
            out = self._candidate_out(row, live, latest)
            await uow.commit()
        return out

    # --- replays -------------------------------------------------------------------------------

    async def replay(
        self, candidate_id: str, window_days: int | None, principal: Principal
    ) -> Replay:
        _need(principal, Permission.LAB_RUN)
        number = _candidate_number(candidate_id)
        snapshot = await self._config.snapshot()
        days = window_days if window_days is not None else snapshot.get(ck.LAB_DEFAULT_WINDOW_DAYS)
        longest = snapshot.get(ck.LAB_MAX_WINDOW_DAYS)
        if days < 1 or days > longest:
            raise LabWindowOutOfRange(f"Window must be between 1 and {longest} days")
        max_items = snapshot.get(ck.LAB_MAX_ITEMS)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            row = await uow.repo(LabCandidateRepository).get_for_update(number)
            if row is None:
                raise LabCandidateNotFound(f"No candidate {candidate_id}")
            if row.status is not CandidateStatus.OPEN:
                raise LabCandidateClosed(f"Candidate {candidate_id} is already {row.status.value}")
            running = await uow.repo(LabReplayRepository).running_for(number)
            if running is not None:
                running = await self._fail_lost_run(uow, running)
                if running.status is ReplayStatus.RUNNING:
                    raise LabReplayRunning(
                        f"Replay {format_replay_id(running.id)} is still running"
                    )
            item_ids = await uow.repo(LabPastItemRepository).past_items(
                now - datetime.timedelta(days=days), max_items
            )
            replay = await uow.repo(LabReplayRepository).add(
                LabReplay(
                    candidate_id=number,
                    status=ReplayStatus.RUNNING,
                    window_days=days,
                    live_version=await self._live_version(uow),
                    done=0,
                    total=len(item_ids),
                    changed=0,
                    newly_matched=0,
                    newly_failed=0,
                    newly_ambiguous=0,
                    money_by_currency=[],
                    started_by=principal.subject,
                    started_at=now,
                    heartbeat_at=now,
                    runner_boot_id=BOOT_ID,
                )
            )
            changes = dict(row.changes)
            replay_id, total = replay.id, replay.total
            await uow.commit()  # RUNNING is durable before the work is handed off
        engine = ReplayEngine(
            self._uow_factory, self._config, self._fusion, self._tasks.hub, self._clock
        )
        self._tasks.start(replay_id, engine.run(replay_id, item_ids, changes, days))
        return Replay(
            id=format_replay_id(replay_id),
            candidate_id=format_candidate_id(number),
            status=ReplayStatus.RUNNING,
            total=total,
        )

    async def get_replay(self, replay_id: str, principal: Principal) -> ReplayResult:
        _need(principal, Permission.LAB_RUN)
        async with self._uow_factory() as uow:
            replay, candidate = await self._load_replay(uow, replay_id)
            live = await self._live_version(uow)
            rows = await uow.repo(LabReplayItemRepository).page(
                replay.id, 0, ITEMS_IN_RESULT, changed_only=True
            )
        status = self._effective_status(replay, live)
        return ReplayResult(
            id=format_replay_id(replay.id),
            candidate_id=format_candidate_id(candidate.id),
            status=status,
            window_days=replay.window_days,
            live_version=replay.live_version,
            base_version=candidate.base_version,
            done=replay.done,
            total=replay.total,
            changed=replay.changed,
            newly_matched=replay.newly_matched,
            newly_failed=replay.newly_failed,
            newly_ambiguous=replay.newly_ambiguous,
            money_by_currency=[
                MoneyByCurrency(
                    currency=str(m["currency"]),
                    newly_matched=str(m["newly_matched"]),
                    newly_unmatched=str(m["newly_unmatched"]),
                    items=int(m["items"]),
                )
                for m in replay.money_by_currency
            ],
            items=[_item_view(r) for r in rows],
            config_diff=_diff(candidate),
            duration_ms=replay.duration_ms,
            started_at=replay.started_at,
            finished_at=replay.finished_at,
            error=replay.error,
            stale_message=f"Live config moved to v{live}" if status is ReplayStatus.STALE else None,
        )

    def _event_for(self, replay: LabReplay) -> ProgressEvent:
        """The frame that describes a replay as it is now (terminal frames close the stream)."""
        base: dict[str, Any] = {
            "replay_id": format_replay_id(replay.id),
            "status": replay.status.value,
        }
        if replay.status is ReplayStatus.FAILED:
            return ProgressEvent("failed", {**base, "message": replay.error or "failed"})
        if replay.status is ReplayStatus.DONE:
            return ProgressEvent(
                "done",
                {
                    **base,
                    "done": replay.done,
                    "total": replay.total,
                    "changed": replay.changed,
                    "newly_matched": replay.newly_matched,
                    "newly_failed": replay.newly_failed,
                    "newly_ambiguous": replay.newly_ambiguous,
                    "duration_ms": replay.duration_ms,
                },
            )
        return ProgressEvent("progress", {**base, "done": replay.done, "total": replay.total})

    def _relabel(self, event: ProgressEvent) -> ProgressEvent:
        data = dict(event.data)
        raw = data.get("replay_id")
        if isinstance(raw, int):
            data["replay_id"] = format_replay_id(raw)
        return ProgressEvent(event.kind, data)

    async def stream(
        self, replay_id: str, principal: Principal
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Progress frames until the replay ends. Events come from the in-process hub; a slow
        tick re-reads the row, which also serves a stream opened on another replica. The tick
        lives only as long as this request, so it is not a poller."""
        _need(principal, Permission.LAB_RUN)
        number = _replay_number(replay_id)
        async with self._uow_factory() as uow:
            replay, _ = await self._load_replay(uow, replay_id)
        if _terminal(replay):
            yield self._event_for(replay)
            return
        source = self._tasks.hub.subscribe(number)
        pending: asyncio.Future[ProgressEvent] | None = None
        last_done = -1
        try:
            while True:
                if pending is None:
                    pending = asyncio.ensure_future(anext(source))
                finished, _ = await asyncio.wait({pending}, timeout=_STREAM_POLL_SECONDS)
                if finished:
                    try:
                        event = self._relabel(pending.result())
                    except StopAsyncIteration:
                        return
                    pending = None
                    last_done = int(event.data.get("done", last_done))
                    yield event
                    if event.terminal:
                        return
                    continue
                async with self._uow_factory() as uow:
                    replay, _ = await self._load_replay(uow, replay_id)
                event = self._event_for(replay)
                if event.terminal or replay.done != last_done:
                    last_done = replay.done
                    yield event
                    if event.terminal:
                        return
        finally:
            if pending is not None:
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                    await pending
            await source.aclose()

    async def items_csv(self, replay_id: str, principal: Principal) -> AsyncIterator[str]:
        _need(principal, Permission.LAB_RUN)
        number = _replay_number(replay_id)
        async with self._uow_factory() as uow:
            await self._load_replay(uow, replay_id)  # 404 before any byte is streamed
        return self._csv_lines(number)

    async def _csv_lines(self, number: int) -> AsyncIterator[str]:
        header_sent = False
        offset = 0
        while True:
            async with self._uow_factory() as uow:
                rows = await uow.repo(LabReplayItemRepository).page(number, offset, _CSV_PAGE)
            offset += len(rows)
            page = [
                CsvRow(
                    item_id=r.work_item_id,
                    amount=r.amount,
                    currency=r.currency,
                    before=r.before_outcome,
                    after=r.after_outcome,
                    receipt_before=r.before_receipt_id,
                    receipt_after=r.after_receipt_id,
                    since_applied=r.since_applied,
                )
                for r in rows
            ]
            for line in replay_items_csv(page, header=not header_sent):
                yield line
            header_sent = True
            if len(rows) < _CSV_PAGE:
                return

    # --- promote --------------------------------------------------------------------------------

    async def promote(
        self,
        candidate_id: str,
        replay_id: str,
        reason: str,
        expected_version: int,
        principal: Principal,
    ) -> Promotion:
        _need(principal, Permission.CONFIG_WRITE)
        if not reason.strip():
            raise LabReasonRequired("A reason is required")
        number = _candidate_number(candidate_id)
        replay_number = _replay_number(replay_id)
        async with self._uow_factory() as uow:
            row = await uow.repo(LabCandidateRepository).get_for_update(number)
            if row is None:
                raise LabCandidateNotFound(f"No candidate {candidate_id}")
            if row.status is not CandidateStatus.OPEN:
                raise LabCandidateClosed(f"Candidate {candidate_id} is already {row.status.value}")
            replay = await uow.repo(LabReplayRepository).get(replay_number)
            if replay is None:
                raise LabReplayNotFound(f"No replay {replay_id}")
            if replay.candidate_id != number:
                raise LabReplayNotDone(f"Replay {replay_id} belongs to another candidate")
            replay = await self._fail_lost_run(uow, replay)
            if replay.status is ReplayStatus.RUNNING:
                raise LabReplayNotDone(f"Replay {replay_id} is still running")
            if replay.status is not ReplayStatus.DONE:
                raise LabReplayNotDone(f"Replay {replay_id} did not finish")
            live = await self._live_version(uow)
            if live != expected_version or replay.live_version != live:
                raise LabStale(live)
            changes = [
                KeyChange(key, value, row.base_key_versions.get(key, 0))
                for key, value in row.changes.items()
            ]
            try:
                await self._writer.set_many(
                    uow,
                    changes,
                    principal,
                    reason,
                    tag=ChangeTag(
                        change_set_id=row.id, lab_candidate_id=row.id, lab_replay_id=replay.id
                    ),
                )
            except ConfigConflict as exc:
                raise LabStale(live) from exc
            except ConfigValidationError as exc:
                raise LabInvalidValue(str(exc), details=exc.errors) from exc
            except ConfigForbidden as exc:
                raise LabForbidden(str(exc)) from exc
            now = self._clock.now()
            new_version = await self._live_version(uow)
            row.status = CandidateStatus.PROMOTED
            row.closed_by = principal.subject
            row.closed_at = now
            row.close_reason = reason.strip()[:1000]
            row.promoted_version = new_version
            await uow.session.flush()
            await uow.commit()
        self._config.invalidate()
        return Promotion(
            candidate_id=format_candidate_id(number),
            replay_id=format_replay_id(replay_number),
            new_version=new_version,
            keys=list(row.changes),
            promoted_by=principal.display_name,
            promoted_at=now,
        )


def _item_view(row: LabReplayItem) -> ReplayItemView:
    return ReplayItemView(
        item_id=row.work_item_id,
        amount=row.amount,
        currency=row.currency,
        before=ReplayOutcome(row.before_outcome),
        after=ReplayOutcome(row.after_outcome),
        receipt_before=row.before_receipt_id,
        receipt_after=row.after_receipt_id,
        since_applied=row.since_applied,
    )
