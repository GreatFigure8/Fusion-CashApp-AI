"""Everything the flow monitor reads: the summary, tiles, stage tables, item detail, history, parts
and search. Read-only: no function here writes, and none commits.

Routers shape the results into JSON; the repository (``FlowQueryRepository``) is the only code
that touches the ORM for the new queries. The stream and the REST summary share one process-local
cache, so N open connections cost one computation per ``SUMMARY_CACHE_SECONDS``.
"""

import asyncio
import logging
import re
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import ceil
from typing import Any, Final, Literal, Protocol, cast

from cashapp.data.models.adjudication import Adjudication
from cashapp.data.models.applications import ApplicationLedger, LineResult
from cashapp.data.models.artifacts import ArtifactPart
from cashapp.data.models.customer_resolution import CustomerResolutionRow
from cashapp.data.models.extraction_reading import ExtractionReading
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.repositories.applications import (
    ApplicationLedgerRepository,
    LineResultRepository,
)
from cashapp.data.repositories.artifacts import ArtifactPartRepository
from cashapp.data.repositories.backlog import BacklogBatchRepository
from cashapp.data.repositories.customer_resolution import CustomerResolutionRepository
from cashapp.data.repositories.flow_query import FlowQueryRepository
from cashapp.data.repositories.history import HistoryRepository
from cashapp.data.repositories.match_candidates import MatchCandidateRepository
from cashapp.data.repositories.poller_heartbeat import PollerHeartbeatRepository
from cashapp.data.repositories.readings import ExtractionReadingRepository
from cashapp.data.repositories.reservations import ReservationRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.backlog import BacklogStatus, estimate_eta_minutes
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.extraction import ReaderSlot
from cashapp.domain.ledger import LedgerStatus
from cashapp.domain.money import Money, to_money
from cashapp.domain.paging import Page
from cashapp.domain.stages import PIPELINE_ORDER, ItemState, Stage
from cashapp.domain.status import SUCCESS_STATUSES, PaymentStatus
from cashapp.integrations.llm.cluster_metrics import ClusterMetrics
from cashapp.integrations.storage.base import ObjectNotFound, ObjectStore
from cashapp.integrations.storage.keys import text_key_for
from cashapp.observability.queue_stats import collect_queue_stats
from cashapp.services.config import RuntimeConfig
from cashapp.services.llm_usage.reporting import cohere_utilisation
from cashapp.services.locking import LockInfo, lock_info_for
from cashapp.services.poller_heartbeat import POLLER_NAMES

logger = logging.getLogger(__name__)

STREAM_TICK_SECONDS: Final = 5.0
SUMMARY_CACHE_SECONDS: Final = 4.0
OVERLAP_SECONDS: Final = 10.0
AGING_BUCKETS: Final = ("0-2d", "3-7d", "8-30d", ">30d")
THROUGHPUT_MINUTES: Final = 60
SEARCH_LIMIT: Final = 10
_ENTRY_CHUNK: Final = 500  # Oracle allows at most 1000 items in an IN list


class FlowTile(StrEnum):
    """One tile per stage, with the awaiting-receipt shelf right after receipt matching."""

    INTAKE = "INTAKE"
    CLASSIFY = "CLASSIFY"
    EXTRACT = "EXTRACT"
    ADJUDICATE = "ADJUDICATE"
    VALIDATE = "VALIDATE"
    RESOLVE_CUSTOMER = "RESOLVE_CUSTOMER"
    FAST_PATH = "FAST_PATH"
    MATCH_RECEIPT = "MATCH_RECEIPT"
    AWAITING_RECEIPT = "AWAITING_RECEIPT"
    MATCH_LINES = "MATCH_LINES"
    APPLY = "APPLY"
    WRITE_BACK = "WRITE_BACK"
    DONE = "DONE"


def _tile_order() -> tuple[FlowTile, ...]:
    """The response order: the pipeline's stages, awaiting receipt after MATCH_RECEIPT."""
    order: list[FlowTile] = []
    for stage in PIPELINE_ORDER:
        order.append(FlowTile(stage.value))
        if stage is Stage.MATCH_RECEIPT:
            order.append(FlowTile.AWAITING_RECEIPT)
    return tuple(order)


TILE_ORDER: Final[tuple[FlowTile, ...]] = _tile_order()
if set(TILE_ORDER) != set(FlowTile):  # a new Stage needs a new FlowTile member
    raise RuntimeError("FlowTile is out of step with the pipeline stages")

_WI_REF: Final = re.compile(r"^\s*(?:WI-)?(\d{1,18})\s*$", re.IGNORECASE)


# --------------------------------------------------------------------------- summary data


@dataclass(frozen=True, slots=True)
class TileData:
    tile: FlowTile
    in_queue: int
    in_progress: int
    errors: int
    throughput_per_min: tuple[int, ...]  # length 60, oldest minute first
    p95_dwell_s: float | None
    awaiting_buckets: Mapping[str, int] | None


@dataclass(frozen=True, slots=True)
class KpiData:
    in_today: int
    auto_applied_pct: float | None
    applied_by_currency: tuple[Money, ...]
    needs_person: int


@dataclass(frozen=True, slots=True)
class PollerData:
    name: str
    last_cycle_at: datetime | None


@dataclass(frozen=True, slots=True)
class BacklogData:
    id: int
    name: str
    processed: int
    total: int
    eta_minutes: int | None
    status: str


@dataclass(frozen=True, slots=True)
class FlowSummaryData:
    kpis: KpiData
    stages: tuple[TileData, ...]
    pollers: tuple[PollerData, ...]
    cohere_utilisation_pct: float | None
    backlog: tuple[BacklogData, ...]
    generated_at: datetime


# --------------------------------------------------------------------------- source adapters


class CohereUtilisationSource(Protocol):
    async def utilisation_pct(self, uow: UnitOfWork) -> float | None: ...


class BacklogProgressSource(Protocol):
    async def running(self, uow: UnitOfWork) -> list[BacklogData]: ...


class LedgerCohereSource:
    """Adapts s36: ledger-derived busy time, or the cluster's own metric when it is configured."""

    def __init__(self, cluster: ClusterMetrics | None = None, clock: Clock | None = None) -> None:
        self._cluster = cluster
        self._clock = clock

    async def utilisation_pct(self, uow: UnitOfWork) -> float | None:
        result = await cohere_utilisation(
            uow, window_minutes=60, clock=self._clock, cluster=self._cluster
        )
        return result.best_pct


class RunningBatchSource:
    """Adapts s35: RUNNING batches with their item counts and ETA."""

    def __init__(self, config: RuntimeConfig, clock: Clock | None = None) -> None:
        self._config = config
        self._clock = clock or SystemClock()

    async def running(self, uow: UnitOfWork) -> list[BacklogData]:
        repo = uow.repo(BacklogBatchRepository)
        batches = await repo.list_by_status([BacklogStatus.RUNNING])
        if not batches:
            return []
        counts = await repo.item_counts([batch.id for batch in batches])
        default_rate = (await self._config.snapshot()).backlog().rate_limit_per_minute
        now = self._clock.now()
        out: list[BacklogData] = []
        for batch in batches:
            batch_counts = counts.get(batch.id)
            if batch_counts is None:
                continue
            out.append(
                BacklogData(
                    id=batch.id,
                    name=batch.name,
                    processed=batch_counts.processed,
                    total=batch_counts.items,
                    eta_minutes=estimate_eta_minutes(
                        batch_counts,
                        status=batch.status,
                        rate_per_min=batch.rate_limit_per_min or default_rate,
                        started_at=batch.started_at,
                        now=now,
                    ),
                    status=batch.status.value,
                )
            )
        return out


def default_cohere_source(cluster: ClusterMetrics | None = None) -> CohereUtilisationSource:
    return LedgerCohereSource(cluster)


def default_backlog_source(config: RuntimeConfig) -> BacklogProgressSource:
    return RunningBatchSource(config)


# --------------------------------------------------------------------------- summary


def _day_start(now: datetime) -> datetime:
    """The UTC calendar day containing ``now``."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _nearest_rank_p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(ceil(0.95 * len(ordered)) - 1, 0)]


async def _throughput_and_dwell(
    uow: UnitOfWork, repo: FlowQueryRepository, now: datetime
) -> tuple[dict[Stage, list[int]], dict[Stage, float]]:
    """Leaves per minute and nearest-rank p95 dwell, both from the last hour of transitions."""
    leaves = await repo.leaves_since(now - timedelta(minutes=THROUGHPUT_MINUTES))
    per_minute: dict[Stage, list[int]] = defaultdict(lambda: [0] * THROUGHPUT_MINUTES)
    for _, stage, at in leaves:
        ago = max(int((now - at).total_seconds() // 60), 0)
        if ago < THROUGHPUT_MINUTES:
            per_minute[stage][THROUGHPUT_MINUTES - 1 - ago] += 1

    item_ids = sorted({item_id for item_id, _, _ in leaves})
    entries: dict[tuple[int, Stage], list[datetime]] = defaultdict(list)
    for start in range(0, len(item_ids), _ENTRY_CHUNK):
        chunk = item_ids[start : start + _ENTRY_CHUNK]
        for item_id, stage, at in await repo.stage_entries(chunk, before=now):
            entries[(item_id, stage)].append(at)
    for times in entries.values():
        times.sort()

    created: dict[int, datetime] = {}
    intake_ids = sorted({i for i, s, _ in leaves if s is Stage.INTAKE and (i, s) not in entries})
    if intake_ids:
        found = await repo.items_by_ids(intake_ids)
        created = {item_id: item.created_at for item_id, item in found.items()}

    dwells: dict[Stage, list[float]] = defaultdict(list)
    for item_id, stage, at in leaves:
        times = entries.get((item_id, stage))
        entered: datetime | None = None
        if times:
            index = bisect_right(times, at)
            entered = times[index - 1] if index else None
        elif stage is Stage.INTAKE:
            entered = created.get(item_id)
        if entered is not None:
            dwells[stage].append(max((at - entered).total_seconds(), 0.0))
    return per_minute, {
        stage: p95
        for stage, values in dwells.items()
        if (p95 := _nearest_rank_p95(values)) is not None
    }


async def _kpis(repo: FlowQueryRepository, now: datetime) -> KpiData:
    since = _day_start(now)
    finished = await repo.finished_since(since)
    done_auto = sum(
        1
        for _, state, status, human in finished
        if state is ItemState.DONE and status in SUCCESS_STATUSES and not human
    )
    applied = tuple(
        Money(to_money(amount), currency)
        for currency, amount in await repo.applied_by_currency_since(since)
    )
    return KpiData(
        in_today=await repo.created_count_since(since),
        auto_applied_pct=round(100 * done_auto / len(finished), 1) if finished else None,
        applied_by_currency=applied,
        needs_person=await repo.escalated_count(),
    )


async def flow_summary(
    uow: UnitOfWork,
    *,
    clock: Clock,
    cohere: CohereUtilisationSource,
    backlog: BacklogProgressSource,
) -> FlowSummaryData:
    now = clock.now()
    repo = uow.repo(FlowQueryRepository)
    stats = await collect_queue_stats(uow, clock=clock)
    counts: dict[tuple[Stage, ItemState], int] = {(s.stage, s.state): s.count for s in stats}
    awaiting_total = sum(s.count for s in stats if s.state is ItemState.AWAITING_RECEIPT)
    errors = await repo.error_counts_by_stage()
    buckets = await repo.awaiting_buckets(now=now)
    per_minute, p95 = await _throughput_and_dwell(uow, repo, now)
    done_today = await repo.done_count_since(_day_start(now))
    zeros = (0,) * THROUGHPUT_MINUTES

    tiles: list[TileData] = []
    for tile in TILE_ORDER:
        if tile is FlowTile.AWAITING_RECEIPT:
            tiles.append(
                TileData(
                    tile, awaiting_total, 0, 0, zeros, None, {k: buckets[k] for k in AGING_BUCKETS}
                )
            )
            continue
        stage = Stage(tile.value)
        if tile is FlowTile.DONE:
            tiles.append(TileData(tile, done_today, 0, 0, zeros, None, None))
            continue
        tiles.append(
            TileData(
                tile=tile,
                in_queue=counts.get((stage, ItemState.PENDING), 0),
                in_progress=counts.get((stage, ItemState.IN_PROGRESS), 0),
                errors=errors.get(stage, 0),
                throughput_per_min=tuple(per_minute[stage]) if stage in per_minute else zeros,
                p95_dwell_s=p95.get(stage),
                awaiting_buckets=None,
            )
        )

    heartbeats = {
        row.name: row.last_cycle_at for row in await uow.repo(PollerHeartbeatRepository).all()
    }
    pollers = tuple(PollerData(name, heartbeats.get(name)) for name in POLLER_NAMES)

    cohere_pct: float | None = None
    try:
        cohere_pct = await cohere.utilisation_pct(uow)
    except Exception as exc:
        logger.warning("cohere utilisation unavailable: error=%s", type(exc).__name__)
    running: list[BacklogData] = []
    try:
        running = await backlog.running(uow)
    except Exception as exc:
        logger.warning("backlog progress unavailable: error=%s", type(exc).__name__)

    return FlowSummaryData(
        kpis=await _kpis(repo, now),
        stages=tuple(tiles),
        pollers=pollers,
        cohere_utilisation_pct=cohere_pct,
        backlog=tuple(running),
        generated_at=now,
    )


class FlowSummaryCache:
    """Process-local, single-flight: concurrent callers share one computation per TTL."""

    def __init__(self, *, ttl_s: float = SUMMARY_CACHE_SECONDS, clock: Clock | None = None) -> None:
        self._ttl = timedelta(seconds=ttl_s)
        self._clock: Clock = clock or SystemClock()
        self._lock = asyncio.Lock()
        self._value: FlowSummaryData | None = None
        self._at: datetime | None = None

    def _fresh(self) -> FlowSummaryData | None:
        if self._value is None or self._at is None:
            return None
        return self._value if self._clock.now() - self._at < self._ttl else None

    async def get(self, compute: Callable[[], Awaitable[FlowSummaryData]]) -> FlowSummaryData:
        cached = self._fresh()
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._fresh()
            if cached is not None:
                return cached
            value = await compute()
            self._value = value
            self._at = self._clock.now()
            return value


# --------------------------------------------------------------------------- stream and tables


@dataclass(frozen=True, slots=True)
class ItemChangedData:
    id: int
    stage: Stage
    state: ItemState
    lock: LockInfo | None
    payment_status: PaymentStatus | None
    updated_at: datetime
    version: int


async def items_changed_since(
    uow: UnitOfWork, since: datetime, *, now: datetime, limit: int = 500
) -> list[ItemChangedData]:
    """Items whose UPDATED_AT is at or after ``since``: the one item query per stream tick."""
    rows = await uow.repo(FlowQueryRepository).changed_since(since, limit=limit)
    return [
        ItemChangedData(
            id=item.id,
            stage=item.stage,
            state=item.state,
            lock=lock_info_for(item, now),
            payment_status=item.payment_status,
            updated_at=item.updated_at,
            version=item.version,
        )
        for item in rows
    ]


async def stage_items(
    uow: UnitOfWork,
    tile: FlowTile,
    *,
    state: ItemState | None,
    page: int,
    page_size: int = 50,
    now: datetime,
) -> tuple[list[tuple[WorkItem, LockInfo | None]], int]:
    result = await uow.repo(FlowQueryRepository).stage_items(
        tile.value, state=state, offset=(page - 1) * page_size, limit=page_size
    )
    return [(item, lock_info_for(item, now)) for item in result.items], result.total


# --------------------------------------------------------------------------- item detail


class ItemNotFound(LookupError):  # noqa: N818 - pinned name
    def __init__(self, item_id: int) -> None:
        super().__init__(f"work item {item_id} not found")
        self.item_id = item_id


class PartNotFound(LookupError):  # noqa: N818 - pinned name
    def __init__(self, item_id: int, part_no: int, *, text: bool = False) -> None:
        super().__init__(f"part {part_no} of item {item_id} not found")
        self.text = text


class PartPurged(Exception):  # noqa: N818 - pinned name
    """The part's bytes were removed by the retention purge."""


@dataclass(frozen=True, slots=True)
class ReceiptRef:
    receipt_id: int
    receipt_number: str
    decided_by: str
    score: float | None
    reservation_status: str | None


@dataclass(frozen=True, slots=True)
class ItemDetailData:
    item: WorkItem
    lock: LockInfo | None
    adjudication: Adjudication | None
    readings: Mapping[ReaderSlot, ExtractionReading]
    parts: list[ArtifactPart]
    lines: list[tuple[LineResult, ApplicationLedger | None]]
    resolution: CustomerResolutionRow | None
    receipt: ReceiptRef | None


def _pair_lines(
    results: list[LineResult], ledger: list[ApplicationLedger]
) -> list[tuple[LineResult, ApplicationLedger | None]]:
    """Each line with its ledger row: the applied one if any, else the newest attempt."""
    by_line: dict[int, ApplicationLedger] = {}
    for row in ledger:  # ordered by apply_seq, id: later rows win, but APPLIED beats the rest
        held = by_line.get(row.line_no)
        if (
            held is None
            or held.status is not LedgerStatus.APPLIED
            or row.status is LedgerStatus.APPLIED
        ):
            by_line[row.line_no] = row
    return [(result, by_line.get(result.line_no)) for result in results]


async def _receipt_ref(uow: UnitOfWork, item_id: int) -> ReceiptRef | None:
    candidates = uow.repo(MatchCandidateRepository)
    chosen = await candidates.last_chosen(item_id)
    reservation = await uow.repo(ReservationRepository).active_for_item(item_id)
    if reservation is not None:
        same = chosen is not None and chosen.receipt_id == reservation.receipt_id
        return ReceiptRef(
            receipt_id=reservation.receipt_id,
            receipt_number=reservation.receipt_number or str(reservation.receipt_id),
            decided_by=chosen.decided_by.value if same and chosen is not None else "system",
            score=chosen.score if same and chosen is not None else None,
            reservation_status=reservation.status.value,
        )
    if chosen is None:
        return None
    return ReceiptRef(
        receipt_id=chosen.receipt_id,
        receipt_number=chosen.receipt_number or str(chosen.receipt_id),
        decided_by=chosen.decided_by.value,
        score=chosen.score,
        reservation_status=None,
    )


async def item_detail(uow: UnitOfWork, item_id: int, *, now: datetime) -> ItemDetailData:
    item = await uow.work_items.get(item_id)
    if item is None:
        raise ItemNotFound(item_id)
    lines = _pair_lines(
        await uow.repo(LineResultRepository).for_item(item_id),
        await uow.repo(ApplicationLedgerRepository).for_item(item_id),
    )
    return ItemDetailData(
        item=item,
        lock=lock_info_for(item, now),
        adjudication=await uow.repo(AdjudicationRepository).latest_for(item_id),
        readings=await uow.repo(ExtractionReadingRepository).latest_for(item_id),
        parts=await uow.repo(ArtifactPartRepository).for_item(item_id),
        lines=lines,
        resolution=await uow.repo(CustomerResolutionRepository).latest_row_for(item_id),
        receipt=await _receipt_ref(uow, item_id),
    )


def fusion_result_code(line: LineResult, ledger: ApplicationLedger | None) -> str | None:
    """The Fusion outcome code for a line: the ledger's error code, else the first message code."""
    if ledger is not None and ledger.error_code is not None:
        return ledger.error_code.value
    if ledger is not None and ledger.response_messages:
        for message in ledger.response_messages:
            code: Any = message
            if isinstance(message, dict):
                fields = cast("dict[str, Any]", message)
                code = fields.get("code") or fields.get("Code")
            if isinstance(code, str) and code:
                return code
    return line.error_code.value if line.error_code is not None else None


async def item_history(
    uow: UnitOfWork, item_id: int, *, page: int, page_size: int = 200
) -> Page[WorkItemHistory]:
    if await uow.work_items.get(item_id) is None:
        raise ItemNotFound(item_id)
    return await uow.repo(HistoryRepository).for_item(
        item_id, offset=(page - 1) * page_size, limit=page_size
    )


# --------------------------------------------------------------------------- parts


@dataclass(frozen=True, slots=True)
class PartContent:
    data: bytes
    media_type: str
    filename: str


_EXTENSIONS: Final[Mapping[str, str]] = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/tiff": "tif",
    "image/webp": "webp",
    "text/plain": "txt",
    "text/csv": "csv",
    "text/html": "html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


async def open_part(
    uow: UnitOfWork,
    store: ObjectStore,
    item_id: int,
    part_no: int,
    *,
    variant: Literal["original", "text"] = "original",
) -> PartContent:
    """Read one part's bytes. The file name is generated, never the source name (no PII)."""
    parts = await uow.repo(ArtifactPartRepository).for_item(item_id)
    part = next((p for p in parts if p.part_no == part_no), None)
    if part is None:
        raise PartNotFound(item_id, part_no)
    if part.purged_at is not None:
        raise PartPurged
    if variant == "text":
        if part.text_preview_chars is None:
            raise PartNotFound(item_id, part_no, text=True)
        key = text_key_for(part.object_key)
        media_type, extension = "text/plain; charset=utf-8", "txt"
    else:
        key = part.object_key
        media_type = part.media_type
        extension = _EXTENSIONS.get(part.media_type.split(";")[0].strip().lower(), "bin")
    try:
        data = await store.get(key)
    except ObjectNotFound as exc:
        raise PartPurged from exc
    return PartContent(data=data, media_type=media_type, filename=f"part-{part_no}.{extension}")


# --------------------------------------------------------------------------- search


@dataclass(frozen=True, slots=True)
class SearchHit:
    item_id: int
    kind: Literal["item", "receipt", "invoice"]
    match: str
    stage: Stage
    state: ItemState


def parse_work_item_ref(q: str) -> int | None:
    """``WI-20481`` or ``20481`` gives 20481; anything else gives None."""
    found = _WI_REF.match(q)
    return int(found.group(1)) if found else None


async def search_items(uow: UnitOfWork, q: str, *, limit: int = SEARCH_LIMIT) -> list[SearchHit]:
    """Items by WI id, receipt number or invoice number, for the command palette."""
    repo = uow.repo(FlowQueryRepository)
    refs: list[tuple[int, Literal["item", "receipt", "invoice"], str]] = []
    wanted = parse_work_item_ref(q)
    if wanted is not None:
        refs.append((wanted, "item", f"WI-{wanted}"))
    for item_id, kind, match in await repo.search_refs(q, limit=limit):
        refs.append((item_id, "receipt" if kind == "receipt" else "invoice", match))
    items = await repo.items_by_ids(sorted({item_id for item_id, _, _ in refs}))
    hits: list[SearchHit] = []
    seen: set[tuple[int, str]] = set()
    for item_id, kind, match in refs:
        item = items.get(item_id)
        if item is None or (item_id, kind) in seen:
            continue
        seen.add((item_id, kind))
        hits.append(SearchHit(item_id, kind, match, item.stage, item.state))
        if len(hits) >= limit:
            break
    return hits
