# Plan: s35-backlog-reprocessing

Issue #35. Wave 5 (money path). Paths: `cashapp/` = `api/src/cashapp/`. API only; the progress bar UI is s19's.

## Standards followed

- CLAUDE.md: same stations and the same rules as live traffic. There is no separate code path: a backlog item is a normal `WORK_ITEM` with `BATCH_ID` and `PRIORITY=10`, and it is driven by the same `StageRunner`s. There is no scheduler and no third poller. Rate limiting is the outbox relay's `PublishThrottle` hook (s03), and batch completion runs as an intake-poller `CycleHook` (s06, the s45/s41 precedent). The layering rules hold: routers never import SQLAlchemy, repositories never commit, and services take `Principal` as a plain argument. A human action is recorded in item history with `actor_fields(principal)` (s40). There is one error shape (`ApiError`). Money is `Decimal`.
- research.md a3/a6: the Fusion write rails stay intact. A dry run makes **zero** Fusion write calls, which is proven with a fake that fails on any write. There are exactly two implementations per external system, and no new fake variant ships in `src/`.
- `python-web-app:building-python-web-apps`: logic lives in services, and deps are `Annotated` aliases (`UowFactoryDep`, `RuntimeConfigDep`, `require_permission`). Mutations are POST only. Job status rule: `IMPORTING` is written before the import is handed off. A failure writes `IMPORT_ERROR` and leaves the batch resumable. Every schema change is an Alembic revision.
- `python-library-quality:guarding-destructive-operations` (applied to the API `folder` argument): name validation and resolved-path containment are two independent checks, and both run before any file is touched. FolderSource then moves the files into `processed/` and `failed/`.
- s02 naming rules apply: lowercase SQLAlchemy names, no reserved words, enum columns are `VARCHAR2(40)` with no CHECK, and identifiers are at most 30 characters.

## Files to touch

New (owned):

| Path | Content |
|---|---|
| `cashapp/domain/backlog.py` | `BacklogStatus`, `BacklogSourceKind`, `ALLOWED_TRANSITIONS`, `BatchCounts`, `BatchProgress`, `estimate_eta_minutes`, `validate_batch_name`, `BATCH_NAME_PATTERN` (pure) |
| `cashapp/data/models/backlog.py` | `BacklogBatch` ORM model (picked up by s02's `load_all_models`) |
| `cashapp/data/repositories/backlog.py` | `BacklogBatchRepository` (batch queries, item counts, the outbox pause/resume/drain updates for a batch, the live-waiting probe, the items-for-promotion/cancel queries) |
| `cashapp/services/backlog/__init__.py` | re-exports the public names below (no import side effects) |
| `cashapp/services/backlog/service.py` | `BacklogService`, `BacklogError` + subclasses, `backlog_error_to_api` |
| `cashapp/services/backlog/sources.py` | `resolve_backlog_folder`, `build_backlog_mailbox_source`, `BACKLOG_SUBDIR` |
| `cashapp/services/backlog/throttle.py` | `TokenBucket`, `BacklogThrottle`, `build_backlog_throttle` |
| `cashapp/services/backlog/dry_run.py` | `is_dry_run`, `record_dry_run_line`, `settle_dry_run_reservation`, `DRY_RUN_KEY_PREFIX` |
| `cashapp/services/backlog/hook.py` | `BacklogCycleHook` (completion and cancel sweep) |
| `cashapp/api/routers/backlog.py` | `router` (prefix `/backlog`), schemas `BacklogBatchCreate`, `BacklogBatchOut`, `BacklogPromote`, `get_backlog_service` dependency |
| `cashapp/tools/backlog/__init__.py`, `__main__.py`, `cli.py` | typer app: `import`, `promote`, `status`, `pause`, `resume`, `cancel` |
| `api/alembic/versions/s35_backlog_batch.py` | the one revision |
| `api/tests/support/backlog.py` | `make_batch(**overrides)`, `WriteForbiddenFusionClient` (test-only decorator around s05's `FakeFusionClient`: any write method → `AssertionError`), `folder_with_artifacts(tmp_path, n)` |
| tests in the TEST PLAN | written and run in step 5 only |

Edited (small, append-style; the merger checks the overlap):

- `cashapp/data/models/work_item.py` (s02): `batch_id` gets `ForeignKey("backlog_batch.id", name="FK_WORK_ITEM_BATCH_ID")`, and `__table_args__` gets `Index("IX_WORK_ITEM_BATCH_STATE", "batch_id", "state")`. Nothing else changes.
- `cashapp/workers/container.py` (s30): one `_SERVICES` entry `"cashapp.pipeline.relay:PublishThrottle" -> "cashapp.services.backlog.throttle:build_backlog_throttle"`. With it, s03's `RELAY_ROLE` resolves `BacklogThrottle` and does not fall back to `AllowAllThrottle`.
- `cashapp/pollers/intake/hooks.py` (s06): append at the bottom, guarded against double registration: `if not any(isinstance(h, BacklogCycleHook) for h in CYCLE_HOOKS): CYCLE_HOOKS.append(BacklogCycleHook())`. This is the same pattern as s45.
- **s15's apply station** (`cashapp/stations/apply/runner.py`, or the module that defines `ApplyRunner`). There are three insertions, with no reordering of s15's logic:
  1. At the start of `process`: `dry = await is_dry_run(ctx.uow, ctx.item)`. This runs **before** the `fusion.write_enabled` check, and when `dry` is set that check is skipped, so a dry run works while writes are disabled.
  2. In the per-row loop, before `apply_gate.slot(...)`: `if dry: await record_dry_run_line(ctx.uow, row, clock=ctx.clock); await ctx.uow.commit(); continue`. No Fusion call is made for the row: no `list_receipt_applications` and no `apply_receipt`.
  3. After the loop: build s15's `HeaderResult(..., dry_run=dry)` so that `roll_up` grades the `ALLOCATION_DRY_RUN` lines. When `dry` is set, call `await settle_dry_run_reservation(ctx.uow, ctx.item.id)` (it releases the reservation) instead of `ReservationRepository.consume`. The history payload gets `"dry_run": dry`. The item still returns `Advance(WRITE_BACK)`.
- **s17's write-back**:
  - `cashapp/services/write_back.py`: `WriteBackResult` gains `skipped: Literal["dry_run"] | None = None`, an additive field. The first statement of `write_back(...)` is `if await is_dry_run(uow, item): return WriteBackResult(note_written=False, attachment_ref=None, skipped="dry_run")`. Because the guard is inside the service, it also covers s16's fast path, which calls `write_back` too.
  - `cashapp/stations/write_back/runner.py`: when `result.skipped`, write a `DECISION` history row ("write-back skipped: dry-run batch") instead of `FUSION_WRITE`, then `Finish(item.payment_status)` as usual. Final state: DONE.

Not touched: `main.py`, lockfiles, `settings.py`, s03's relay and runner, s06's `ingest` (already public with the `source_kind`/`batch_id`/`priority` keywords), s13.

## Design

### Lifecycle

```
POST / CLI import ──► IMPORTING ──(import finished)──► RUNNING ──(no PENDING/IN_PROGRESS items; hook)──► DONE
                          │  ▲                            │  ▲
                        pause resume                    pause resume
                          ▼  │                            ▼  │
                          PAUSED  ─────────────────────── PAUSED
any non-terminal ──cancel──► CANCELLED          DONE dry-run batch ──promote──► new RUNNING real batch
```

`ALLOWED_TRANSITIONS` is a pure table in `domain/backlog.py`. Pause on `PAUSED`, resume on a running batch and cancel on `CANCELLED` are idempotent no-ops that return the batch. Any other transition from `DONE` or `CANCELLED` raises `BacklogTransitionError`, which maps to 409.

- **Import** (`run_import`): it first sets `STARTED_AT` if it is null. Then, for each artifact from `source.fetch_new()`, it calls `ingest(uow_factory, object_store, artifact, source_kind=SourceKind.BACKLOG, batch_id=batch.id, priority=PRIORITY_BACKLOG, clock=clock, normaliser=normaliser)` and then `source.mark_processed(ref, "processed")`. On an exception it logs the type and sha256 only, marks the artifact `"failed"`, increments `failed`, and continues.
  - Every 50 artifacts it re-reads the batch status. On `CANCELLED` it stops. On `PAUSED` it keeps importing: pause throttles the pipeline, not intake.
  - At the end, in one transaction: `TOTAL = count(items with BATCH_ID)` (envelope items carry no batch id), `IMPORTED_AT = now`, and `STATUS` goes `IMPORTING → RUNNING`; a `PAUSED` batch stays `PAUSED`. An audit entry `{action: "imported", ingested, duplicates, failed}` is added.
  - An exception that escapes the loop writes `IMPORT_ERROR` (exception type plus a truncated message, never content). The status stays `IMPORTING`, so `resume` re-runs the import idempotently: dedupe plus FolderSource's move to `processed/` means only the remaining files are read.
- **Dedupe**: a backlog artifact already seen as live mail is a duplicate (s06 history row "duplicate received from BACKLOG:…") and is not added to the batch. This is by design.
- **Dry-run artifacts and the later real run**: the folder files are moved into `processed/`, and their content hashes are now taken. So a real run after a dry run uses **promote**, not a re-import.
  - `promote(uow_factory, dry_batch_id, *, name, rate_limit, principal)` requires a `DONE` dry-run batch. It creates a real batch (`DRY_RUN=0`, `PROMOTED_FROM_ID`, status `RUNNING`, `IMPORTED_AT=now`).
  - It then re-points every item of the dry batch whose state is in {DONE, ESCALATED, AWAITING_RECEIPT} and which is not locked (`is_locked_for_automation`), in chunks of 200 per transaction:
    - `batch_id = new`, `priority = 10`, `state = PENDING`, `attempts = 0`
    - clear `payment_status`, `last_error_*`, `escalation_summary`, `awaiting_since` and `fix_hints`
    - `stage = RESOLVE_CUSTOMER`. An escalated item whose stage comes before `RESOLVE_CUSTOMER` in `PIPELINE_ORDER` keeps its stage.
    - write a `HUMAN_ACTION` history row with `actor_fields(principal)` and payload `{from_batch, to_batch}`, and `emit(StageEvent.new(...), priority=PRIORITY_BACKLOG)`.
  - The adjudicated extraction is reused, so there are no new Opus/Cohere calls; Fusion data is re-read fresh. ARCHIVED items (non-remittances) and locked items are skipped and counted. `TOTAL` is the number re-pointed.
- **Cancel**: in one transaction, `STATUS = CANCELLED` and `FINISHED_AT = now`. Then, in chunks, every item of the batch with state in {PENDING, AWAITING_RECEIPT, ESCALATED} that is not locked is set to `ARCHIVED`, with a `HUMAN_ACTION` history row "backlog batch cancelled". The batch's paused outbox rows get `NOT_BEFORE = now` so they drain: the throttle admits rows of a cancelled batch without limit, and the runners' claim skips them because the item isn't PENDING.
  - Items that were `IN_PROGRESS` at that moment finish their current stage. The hook's cancel sweep (below) archives them on a later cycle, so the effect is eventually complete without a new loop.
- **Pause**: sets `STATUS = PAUSED`. It also moves the batch's unpublished outbox rows to `NOT_BEFORE = PAUSED_NOT_BEFORE` (a fixed sentinel, `2999-01-01T00:00:00Z`). s02's `claim_batch` then stops claiming them, so a paused batch can't crowd out other batches in the relay's 100-row window. Rows emitted after the pause, by items that were in flight, are refused by the throttle. **Resume** sets `NOT_BEFORE = now` on the rows that hold the sentinel, and sets `STATUS` back to `RUNNING`, or to `IMPORTING` when `IMPORTED_AT` is null. In that case the API relaunches the folder import in the background; a `MAILBOX_FOLDER` batch must be resumed through the CLI and gets a 409 `backlog_resume_via_cli`.
- **Completion** (`BacklogCycleHook.on_cycle`, which runs after each intake-poller cycle):
  - For each `RUNNING` batch with `IMPORTED_AT` set and no item in PENDING or IN_PROGRESS, set `STATUS = DONE` and `FINISHED_AT = now`.
  - For each `CANCELLED` batch, archive any remaining unlocked PENDING, AWAITING_RECEIPT or ESCALATED items, at most 500 per cycle.
  - AWAITING_RECEIPT items count as settled for `DONE`. They are still reported as `awaiting`, and s14 keeps waking them.

### Dry run (AC3)

- `is_dry_run(uow, item)` returns False when `item.batch_id is None`. Otherwise it does one PK `get` through `BacklogBatchRepository` and returns `batch.dry_run`.
- `record_dry_run_line(uow, row, *, clock)`:
  - On the ledger row, through s15's `ApplicationLedgerRepository.mark(row, "DRY_RUN", idempotency_key=f"{DRY_RUN_KEY_PREFIX}{row.id}", applied_at=clock.now(), applied_by=SYSTEM_ACTOR_ID)`. Re-keying keeps the unique `IDEMPOTENCY_KEY` (`item:receipt:trx`) free, so a promoted real run can insert its PLANNED row. The original request JSON stays on the row as the audit of what would have been sent.
  - On the line, through `LineResultRepository.upsert(item_id, line_no, line_status=LineStatus.ALLOCATION_DRY_RUN, applied_amount=row.amount, discount_amount=row.discount_amount, residual=<s15's computed residual>)`.
  - It never calls Fusion.
- `settle_dry_run_reservation(uow, item_id)` calls `ReservationRepository.release(item_id, "dry_run")` (s13), so a dry run never holds a receipt.
- Fusion **reads** (lookups, matching, receipt candidates) happen in a dry run exactly as in a real one. They are throttled by the same per-batch rate, because every stage hop goes through the outbox.

### Throttle (AC4)

```
admit(row):
  if row.priority >= PRIORITY_LIVE:          # live: never delayed, no DB access
      self._live_seen_at = now; return True
  if row.work_item_id is None: return True
  batch = await self._batch_for_item(row.work_item_id)   # item->batch LRU (10k, TTL 10 s); batch info TTL 2 s
  if batch is None: return True                          # low priority but not a batch item
  if batch.status in (CANCELLED, DONE): return True      # drain; runners' claim makes it a no-op
  if batch.status is PAUSED: return False
  if await self._live_waiting(now): return False         # live rows pending -> backlog waits
  return self._bucket(batch.id, rate).try_take(now)
```

- `_live_waiting(now)`: if a live row was seen in the last `live_check_seconds` (default 1.0), it is true. Otherwise it uses `BacklogBatchRepository.live_outbox_waiting(now=now, min_priority=PRIORITY_LIVE)`: `EXISTS(published_at IS NULL AND not_before <= now AND priority >= :p)`. That runs in its own read-only UoW and is cached for `live_check_seconds`.
  - Within one relay cycle, live rows sort first (priority desc), so backlog rows in a batch that also held live rows are refused and go out on the next cycle, after the live rows are marked published.
  - A live row whose publish keeps failing also blocks backlog. That is intended: "only when no live rows are waiting".
- `rate = batch.rate_limit_per_min or snapshot.backlog().rate_limit_per_minute` (s28). The snapshot is cached with the batch info, so a change to the global default applies within the TTL.
- `TokenBucket(rate_per_min, *, capacity=1, clock)`: refill `rate/60` tokens per second, capacity 1, starting full. This gives smooth pacing (20/min means one row every 3 s). In any 60-s window it admits at most `rate + 1` (the starting token), and the sustained rate is exactly `rate`. Buckets are rebuilt when a batch's rate changes.
- The relay retries refused rows after `throttle_wait_seconds` (s03). A paused batch's rows are out of the claim window (`NOT_BEFORE` sentinel), so they cost nothing.
- `build_backlog_throttle(container) -> BacklogThrottle` uses `container.uow_factory`, `container.config` and `container.clock`.

### Counts and ETA (AC5/AC6)

- `BacklogBatchRepository.item_counts(batch_ids) -> dict[int, BatchCounts]` is one `GROUP BY batch_id, state, payment_status` query, using the `IX_WORK_ITEM_BATCH_STATE` index.
  - `processed = DONE + ARCHIVED + ESCALATED`
  - `applied = DONE with payment_status ∈ SUCCESS_STATUSES` (for a dry-run batch, read this as "would apply")
  - `escalated = ESCALATED`
  - `failed = DONE with payment_status ∉ SUCCESS_STATUSES or null`
  - `awaiting = AWAITING_RECEIPT`
  - `in_flight = PENDING + IN_PROGRESS`
  - `total = TOTAL` once imported, else the live item count.
- `estimate_eta_minutes(counts, *, status, rate, started_at, now) -> int | None`:
  - `None` when PAUSED, CANCELLED or IMPORTING with no items yet; `0` when DONE or `in_flight == 0`.
  - Otherwise, if `processed > 0` and at least 1 minute has elapsed, it is `ceil(in_flight × elapsed_min / processed)` (observed throughput). Else it is `ceil(in_flight × len(CONSUMED_STAGES) / rate)`, since each stage hop is one throttled outbox row.

## Interfaces provided (pinned)

```python
# cashapp/domain/backlog.py
class BacklogStatus(StrEnum): IMPORTING RUNNING PAUSED DONE CANCELLED          # value == name
class BacklogSourceKind(StrEnum): FOLDER MAILBOX_FOLDER
TERMINAL_BATCH_STATUSES: frozenset[BacklogStatus] = {DONE, CANCELLED}
ALLOWED_TRANSITIONS: Mapping[tuple[BacklogStatus, str], BacklogStatus]   # (status, action) -> new status; action in pause|resume|cancel|imported|complete
BATCH_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
def validate_batch_name(name: str) -> str                                  # ValueError
@dataclass(frozen=True, slots=True)
class BatchCounts:
    items: int; processed: int; applied: int; escalated: int; failed: int; awaiting: int; in_flight: int
@dataclass(frozen=True, slots=True)
class BatchProgress:                     # what the API and s19 render
    id: int; name: str; status: BacklogStatus; dry_run: bool; source_kind: BacklogSourceKind
    total: int; processed: int; applied: int; escalated: int; failed: int; awaiting: int; in_flight: int
    rate_limit_per_minute: int           # effective (batch value or config default)
    eta_minutes: int | None; started_at: datetime | None; finished_at: datetime | None
    created_by: str; promoted_from_id: int | None; import_error: str | None
def estimate_eta_minutes(counts: BatchCounts, *, status: BacklogStatus, rate_per_min: int,
                         started_at: datetime | None, now: datetime) -> int | None
```

```python
# cashapp/data/models/backlog.py   (__tablename__ = "backlog_batch")
class BacklogBatch(Base):
    id: Mapped[int]                         # identity PK  PK_BACKLOG_BATCH
    name: Mapped[str]                       # String(100), unique UQ_BACKLOG_BATCH_NAME
    source_kind: Mapped[BacklogSourceKind]  # StrEnumType
    source_ref: Mapped[str]                 # String(1000): absolute folder path or mailbox folder name
    dry_run: Mapped[bool]                   # Boolean(create_constraint=False), not null, default False
    rate_limit_per_min: Mapped[int | None]  # null -> config backlog.rate_limit_per_minute
    status: Mapped[BacklogStatus]           # not null, default IMPORTING
    total: Mapped[int]                      # not null, default 0
    created_by: Mapped[str]                 # String(255): principal.subject
    created_by_name: Mapped[str | None]     # String(255)
    created_at: Mapped[datetime]            # UtcDateTime default utcnow
    started_at: Mapped[datetime | None]
    imported_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    updated_at: Mapped[datetime]            # default/onupdate utcnow
    import_error: Mapped[str | None]        # Text
    promoted_from_id: Mapped[int | None]    # FK backlog_batch.id  FK_BACKLOG_BATCH_PROMOTED
    audit: Mapped[list[dict[str, Any]]]     # JsonDoc, default []: {at, actor_id, actor_name, action, detail}
    # index IX_BACKLOG_BATCH_STATUS (status)

# cashapp/data/repositories/backlog.py
PAUSED_NOT_BEFORE: Final[datetime]          # 2999-01-01T00:00:00Z
class BacklogBatchRepository(BaseRepository[BacklogBatch]):
    async def by_name(self, name: str) -> BacklogBatch | None
    async def list_by_status(self, statuses: Collection[BacklogStatus] | None, *, limit: int = 100) -> list[BacklogBatch]  # created_at desc
    async def item_counts(self, batch_ids: Sequence[int]) -> dict[int, BatchCounts]
    async def count_items(self, batch_id: int) -> int
    async def has_unsettled_items(self, batch_id: int) -> bool          # any PENDING / IN_PROGRESS
    async def items_in_states(self, batch_id: int, states: Collection[ItemState], *, limit: int) -> list[WorkItem]  # FOR UPDATE SKIP LOCKED
    async def batch_for_item(self, work_item_id: int) -> BacklogBatch | None
    async def defer_outbox(self, batch_id: int, *, not_before: datetime) -> int      # pause: unpublished rows of the batch's items
    async def release_outbox(self, batch_id: int, *, now: datetime) -> int           # resume/cancel: rows at the sentinel -> now
    async def live_outbox_waiting(self, *, now: datetime, min_priority: int) -> bool
```

```python
# cashapp/services/backlog/service.py
class BacklogError(Exception): ...
class BacklogNotFound(BacklogError): batch_id: int                      # -> 404 backlog_not_found
class BacklogNameTaken(BacklogError): name: str                         # -> 409 backlog_name_taken
class BacklogTransitionError(BacklogError): status: BacklogStatus; action: str   # -> 409 backlog_invalid_transition
class BacklogSourceError(BacklogError): reason: str                     # -> 422 backlog_source_invalid
class BacklogResumeViaCli(BacklogError): batch_id: int                  # -> 409 backlog_resume_via_cli
def backlog_error_to_api(exc: BacklogError) -> ApiError

class BacklogService:
    def __init__(self, *, object_store: ObjectStore, config: RuntimeConfig, clock: Clock | None = None,
                 normaliser: Normaliser = normalise) -> None
    async def import_batch(self, uow_factory: UowFactory, source: ArtifactSource, *, name: str, dry_run: bool,
                           rate_limit: int | None, principal: Principal,
                           source_kind: BacklogSourceKind = BacklogSourceKind.FOLDER,
                           source_ref: str) -> BacklogBatch          # = create_batch + run_import (CLI path)
    async def create_batch(self, uow_factory: UowFactory, *, name: str, dry_run: bool, rate_limit: int | None,
                           source_kind: BacklogSourceKind, source_ref: str, principal: Principal) -> BacklogBatch   # IMPORTING, committed
    async def run_import(self, uow_factory: UowFactory, batch_id: int, source: ArtifactSource) -> BacklogBatch
    async def pause(self, uow_factory: UowFactory, batch_id: int, *, principal: Principal) -> BacklogBatch
    async def resume(self, uow_factory: UowFactory, batch_id: int, *, principal: Principal) -> BacklogBatch
        # returns the batch; caller relaunches run_import when status is IMPORTING
    async def cancel(self, uow_factory: UowFactory, batch_id: int, *, principal: Principal) -> BacklogBatch
    async def promote(self, uow_factory: UowFactory, dry_batch_id: int, *, name: str, rate_limit: int | None,
                      principal: Principal) -> BacklogBatch
    async def progress(self, uow: UnitOfWork, *, statuses: Collection[BacklogStatus] | None = None,
                       batch_id: int | None = None, limit: int = 100) -> list[BatchProgress]
        # read-only; s19's /flow/summary may call this in-process instead of over HTTP

# cashapp/services/backlog/sources.py
BACKLOG_SUBDIR: Final = "backlog"
def resolve_backlog_folder(settings: Settings, folder: str) -> Path
    # API only: folder is relative (segments [A-Za-z0-9._-]+, no "..", not absolute); result =
    # (Path(settings.intake.drop_folder) / "backlog" / folder).resolve(), must be inside that root and an
    # existing directory -> else BacklogSourceError. The intake poller never reads sub-directories.
def build_backlog_mailbox_source(settings: Settings, folder: str) -> MailboxSource
    # loads "cashapp.integrations.mail.factory:build_mailbox_source(settings, folder=...)"; absent (s33 follow-up
    # not built yet) -> BacklogSourceError("mailbox adapter not available")

# cashapp/services/backlog/throttle.py
class TokenBucket:
    def __init__(self, rate_per_min: int, *, clock: Clock, capacity: float = 1.0) -> None
    def try_take(self) -> bool
class BacklogThrottle:                      # satisfies s03 PublishThrottle
    def __init__(self, uow_factory: UowFactory, config: RuntimeConfig, clock: Clock, *,
                 live_check_seconds: float = 1.0, batch_cache_seconds: float = 2.0,
                 item_cache_size: int = 10_000) -> None
    async def admit(self, row: OutboxRow) -> bool
def build_backlog_throttle(container: Container) -> BacklogThrottle

# cashapp/services/backlog/dry_run.py
DRY_RUN_KEY_PREFIX: Final = "dry-run:"
async def is_dry_run(uow: UnitOfWork, item: WorkItem) -> bool
async def record_dry_run_line(uow: UnitOfWork, row: ApplicationLedger, *, clock: Clock) -> None
async def settle_dry_run_reservation(uow: UnitOfWork, item_id: int) -> None

# cashapp/services/backlog/hook.py
class BacklogCycleHook:                    # satisfies s06 CycleHook
    async def on_cycle(self, container: Container, now: datetime) -> None
```

HTTP (router `cashapp/api/routers/backlog.py`; every route declares `responses=ERROR_RESPONSES`):

| Method and path | Permission | Body / query | Response |
|---|---|---|---|
| `POST /backlog/batches` | `backlog:run` | `BacklogBatchCreate{name: str, folder: str, dry_run: bool = False, rate_limit_per_minute: int \| None (1..10000)}` | **202** `BacklogBatchOut` (status `IMPORTING`); the import runs as a FastAPI `BackgroundTasks` call to `run_import` |
| `GET /backlog/batches` | `items:read` | `?status=RUNNING&status=PAUSED` (repeatable, optional), `?limit` (≤ 200, default 100) | 200 `list[BacklogBatchOut]`, newest first |
| `GET /backlog/batches/{id}` | `items:read` | | 200 `BacklogBatchOut` or 404 |
| `POST /backlog/batches/{id}/pause` | `backlog:run` | | 200 `BacklogBatchOut` |
| `POST /backlog/batches/{id}/resume` | `backlog:run` | | 200 `BacklogBatchOut` (relaunches the folder import when `IMPORTING`) |
| `POST /backlog/batches/{id}/cancel` | `backlog:run` | | 200 `BacklogBatchOut` |
| `POST /backlog/batches/{id}/promote` | `backlog:run` | `BacklogPromote{name: str, rate_limit_per_minute: int \| None}` | 201 `BacklogBatchOut` (new batch) |

`BacklogBatchOut` = `{id, name, status, dry_run, source_kind, total, processed, applied, escalated, failed, awaiting, in_flight, rate_limit_per_minute, eta_minutes: int|null, started_at: datetime|null, finished_at: datetime|null, created_by, promoted_from_id: int|null, import_error: str|null}`. That is AC5's exact field set plus additive fields. `SOURCE_REF` is not exposed. The schema is built from `BatchProgress`, never from the ORM model.

CLI (`uv run python -m cashapp.tools.backlog …`; it builds an s30 `WorkerContainer(get_settings())` and resolves `ObjectStore`). The principal is `Principal.from_roles(subject=f"cli:{getpass.getuser()}", display_name=..., email=None, groups=(), roles=(Role.ADMIN,))`.
- `import --folder PATH --name B-0007 [--dry-run] [--rate 20]`: uses `FolderSource(Path(PATH), clock=SystemClock())`. CLI paths are trusted operator input, but the folder must exist.
- `import --mailbox-folder NAME --name … [--dry-run] [--rate N]`: uses `build_backlog_mailbox_source`.
- `promote --batch ID|NAME --name NEW [--rate N]`, `status [--batch ID|NAME]` (prints the `BatchProgress` table), `pause|resume|cancel --batch ID|NAME`.
- Exit codes: 0 on success, 2 on a `BacklogError` (the message goes to stderr).

## Migrations

- One hand-written revision, `api/alembic/versions/s35_backlog_batch.py`, `revision = "s35_backlog_batch"`. **Expected parent: the single head when this merges.** By wave order that is s15's `LINE_RESULT`/`APPLICATION_LEDGER` revision, or a later wave-5 revision. The merger re-points `down_revision` and checks that `alembic heads` returns one head.
- `upgrade`:
  - `create_table("backlog_batch", …)` with the columns above. `audit` uses `JsonDoc`; the PK is identity.
  - `UQ_BACKLOG_BATCH_NAME`, `IX_BACKLOG_BATCH_STATUS`, and the self-FK `FK_BACKLOG_BATCH_PROMOTED`.
  - On `work_item`, `create_foreign_key("FK_WORK_ITEM_BATCH_ID", "work_item", "backlog_batch", ["batch_id"], ["id"])` and `create_index("IX_WORK_ITEM_BATCH_STATE", "work_item", ["batch_id", "state"])`.
  - Existing `BATCH_ID` values are all NULL (nothing wrote them before), so the FK validates.
- `downgrade`: drop the index, the FK, then the table.
- DEV ATP only.

## TEST PLAN (written and run in step 5 only)

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `api/tests/integration/backlog/test_migration_backlog.py::test_upgrade_creates_backlog_batch_and_fk` (sqlite + `-m atp`) | exact column set, types and nullability; UQ on NAME; IX on STATUS; `FK_WORK_ITEM_BATCH_ID` and `IX_WORK_ITEM_BATCH_STATE` exist |
| 1 | `…::test_downgrade_drops_fk_index_and_table` | |
| 1 | `…::test_alembic_single_head_after_s35` | `ScriptDirectory` has one head |
| 1 | `…::test_work_item_batch_fk_rejects_unknown_batch` (`-m atp`) | |
| 2 | `api/tests/unit/services/backlog/test_import.py::test_import_batch_uses_ingest_with_backlog_kind_batch_and_priority` | items have `SOURCE_KIND=BACKLOG`, `BATCH_ID`, `PRIORITY=10`; outbox rows priority 10; `ingest` spied |
| 2 | `…::test_import_sets_total_imported_at_and_running` | |
| 2 | `…::test_duplicate_artifact_not_added_to_batch` | artifact already ingested live → no new item; `total` excludes it |
| 2 | `…::test_failed_artifact_marked_failed_and_import_continues` | |
| 2 | `…::test_import_error_recorded_and_resume_reimports_remaining` | |
| 2 | `…::test_cancel_during_import_stops_reading` | |
| 2 | `…::test_mailbox_folder_variant_with_fake_mailbox_source` | `FakeMailboxSource(folder="Backlog/2025")`; `SOURCE_KIND=MAILBOX_FOLDER` |
| 2 | `…::test_duplicate_batch_name_raises_name_taken` | |
| 2 | `api/tests/unit/tools/test_backlog_cli.py::test_import_folder_command_parses_and_calls_service` | `CliRunner`: `import --folder P --name B-0007 --dry-run --rate 20` |
| 2 | `…::test_import_mailbox_folder_without_adapter_exits_2` | |
| 2 | `…::test_promote_and_status_commands` | |
| 2 | `api/tests/unit/services/backlog/test_sources.py::test_resolve_backlog_folder_rejects_traversal_absolute_and_outside_root` | parametrized over `..`, `/etc`, a symlink escaping the root, and a missing dir |
| 3 | `api/tests/integration/backlog/test_dry_run.py::test_dry_run_apply_makes_no_fusion_write_call` | `WriteForbiddenFusionClient`; item reaches DONE |
| 3 | `…::test_dry_run_records_ledger_dry_run_and_line_result_amounts` | ledger `STATUS=DRY_RUN`, key prefixed `dry-run:`, `LINE_RESULT=allocation-dry-run`, amounts equal to the capped plan |
| 3 | `…::test_dry_run_works_with_fusion_write_disabled` | |
| 3 | `…::test_dry_run_releases_reservation_not_consume` | |
| 3 | `…::test_dry_run_write_back_skipped_with_decision_history` | no `set_receipt_comment` / `attach_to_receipt`; DECISION row |
| 3 | `…::test_dry_run_finishes_done_with_derived_payment_status` | `roll_up(dry_run=True)` → success grade |
| 3 | `…::test_fast_path_write_back_skipped_for_dry_run` | s16 path through the `write_back` service |
| 3 | `…::test_live_item_unaffected_by_dry_run_guard` | `batch_id` None → normal apply path called |
| 3 | `api/tests/unit/services/backlog/test_promote.py::test_promote_repoints_settled_items_and_emits_events` | stage `RESOLVE_CUSTOMER`, priority 10, HUMAN_ACTION history, outbox rows |
| 3 | `…::test_promote_requires_done_dry_run_batch` | |
| 3 | `…::test_promote_skips_locked_and_archived_items` | |
| 3 | `…::test_promoted_item_replans_without_idempotency_key_clash` | |
| 4 | `api/tests/unit/services/backlog/test_throttle.py::test_token_bucket_paces_rate_per_minute` | FrozenClock, 10 simulated minutes: every 60-s window ≤ rate+1, sustained total = 10×rate ±1 |
| 4 | `…::test_backlog_rows_limited_per_batch_independently` | two batches, separate buckets |
| 4 | `…::test_default_rate_from_config_when_batch_rate_null` | `make_config_snapshot({"backlog.rate_limit_per_minute": 6})` |
| 4 | `…::test_paused_batch_admits_nothing` | |
| 4 | `…::test_backlog_refused_while_live_rows_waiting` | |
| 4 | `…::test_live_row_always_admitted_without_db_access` | uow_factory spy never called; paused batch and empty bucket |
| 4 | `…::test_cancelled_and_done_batch_rows_drain` | |
| 4 | `…::test_non_batch_low_priority_row_admitted` | |
| 4 | `api/tests/integration/backlog/test_relay_throttle.py::test_live_never_delayed_by_backlog` | real `OutboxRelay.run_once` + `InMemoryEventBus`: 200 backlog rows plus 1 live row inserted later → the live row is published on the next `run_once`; backlog published ≤ bucket |
| 4 | `…::test_pause_moves_rows_out_of_claim_window_and_resume_restores` | `NOT_BEFORE` sentinel, `claim_batch` excludes them, resume → now |
| 4 | `…::test_container_resolves_backlog_throttle_for_relay` | s30 `make_worker_container` → `RELAY_ROLE.build` uses `BacklogThrottle` |
| 5 | `api/tests/api/test_backlog_api.py::test_post_batches_returns_202_and_starts_import` | `BackgroundTasks` runs; fake object store |
| 5 | `…::test_post_requires_backlog_run_permission` | 403 single error shape |
| 5 | `…::test_post_invalid_folder_422_and_duplicate_name_409` | |
| 5 | `…::test_get_batches_fields_and_derived_counts` | items seeded in DONE success / DONE failed / ESCALATED / AWAITING / PENDING → exact counts; field set ⊇ AC5 list |
| 5 | `…::test_get_batch_by_id_and_404` | |
| 5 | `…::test_pause_resume_cancel_transitions_and_409_on_terminal` | |
| 5 | `…::test_cancel_archives_pending_items_with_history` | |
| 5 | `…::test_eta_minutes_rules` (unit, `tests/unit/domain/test_backlog.py`) | paused None, done 0, observed vs rate estimate |
| 5 | `…::test_money_and_no_orm_leak_in_schema` | OpenAPI `BacklogBatchOut` has no ORM-only fields (`source_ref`, `audit`) |
| 6 | `api/tests/api/test_backlog_api.py::test_status_running_filter_contract_for_flow_monitor` | `GET /backlog/batches?status=RUNNING` returns only RUNNING, with `{id, name, processed, total, eta_minutes, status}` |
| 6 | `api/tests/unit/services/backlog/test_hook.py::test_hook_marks_running_batch_done_when_settled` | AWAITING counts as settled |
| 6 | `…::test_hook_leaves_batch_running_with_pending_items` | |
| 6 | `…::test_hook_sweeps_cancelled_batch_stragglers` | |
| 6 | `…::test_hook_registered_once_in_cycle_hooks` | |
| all | `api/tests/unit/services/backlog/test_backlog_pii.py::test_no_artifact_content_in_logs` | sentinel text absent from caplog across import, failure and cancel |

Coder gates: `uv run ruff check . && uv run ruff format --check .` and `uv run pyright` only.

## Assumptions and deviations

- **s15 and s17 plans were not written when this plan was made.** The edits to them are coded against their story ACs: `ApplicationLedgerRepository.mark/planned_for`, `LineResultRepository.upsert`, `HeaderResult`, `WriteBackResult`, `write_back(uow, item, receipt_id, *, mode)`. The coder adapts names to the merged code; the three insertion points don't change. The merge order in wave 5 must be s13 → s15 → s17 → s35.
- **Promote** (`POST …/promote`, CLI `promote`) is added beyond the ACs. A dry run's artifacts are deduped and moved to `processed/`, so a real run after a dry run can't re-import them; without promote, "dry run first" would be a dead end. Promote reuses the adjudicated extraction, so the LLM cost is not paid twice.
- **Additive columns** beyond AC1: `CREATED_BY_NAME`, `STARTED_AT`, `IMPORTED_AT`, `UPDATED_AT`, `IMPORT_ERROR`, `PROMOTED_FROM_ID`, `AUDIT`. These are needed for the job-status rule, ETA, resume and the record of who did what.
- **The audit trail for batch-level actions lives in `BACKLOG_BATCH.AUDIT`** (JSON list) and not in a new table. Per-item effects of cancel and promote are written to each item's history with `actor_fields(principal)`.
- **`RATE_LIMIT_PER_MIN` is nullable.** NULL means "follow `backlog.rate_limit_per_minute`" at runtime (AC4's default). It counts **outbox rows** (stage hops), as AC4 states, not items.
- **The token bucket has capacity 1.** "At most N per minute" holds to within one starting token in any window. The test asserts `≤ rate + 1`.
- **The throttle's buckets are in-process.** Running more than one relay instance would multiply the effective rate. s30 runs one `relay` role per environment; recorded for s44.
- **API imports run in the API process** (`BackgroundTasks`). An API restart mid-import leaves the batch `IMPORTING` with progress kept, and `resume` (API or CLI) continues it. Large backlogs should be imported through the CLI.
- **The API takes a folder relative to `<intake.drop_folder>/backlog/`.** No new setting is added. Absolute paths are CLI-only.
- **The mailbox-folder variant is CLI-only** and depends on the real mailbox adapter (s33 follow-up), loaded by import path. Until that exists, the CLI exits 2 with a clear message. Tests use s06's `FakeMailboxSource`.
- The outbox queries scoped to a batch (`defer_outbox`, `release_outbox`, `live_outbox_waiting`) live in `BacklogBatchRepository` rather than s02's `OutboxRepository`, which keeps the story file-disjoint. Both are repositories, so the "no query outside a repository" rule holds. The rows are matched with `MSG_KEY` (= `str(work_item_id)`, s03) IN the batch's item ids.
- GET permission is `items:read`, so s19's viewers see progress. Mutations need `backlog:run`.
- The CLI acts as a `cli:<os user>` principal with the ADMIN role, because it runs on the worker box with DB credentials and has no OIDC token.

## Risks

- **Dry-run reservations.** Between MATCH_RECEIPT and APPLY, a dry-run item holds an ACTIVE `RECEIPT_RESERVATION` (s13). A live item matching the same receipt in that window gets `RECEIPT_RESERVED`. The window is short (the apply step releases it), and historical receipts are rarely candidates for live mail, but it can happen. A follow-up could make s13 skip reserving for dry-run items; that is not done here, to avoid editing s13.
- **Dry-run escalations show up in the workbench (s20) and in notifications (s42).** People could waste effort on them. s20 should filter or tag items whose batch is `DRY_RUN`, using `BacklogBatchRepository` / `is_dry_run`. This is flagged for the s20 and s42 mergers.
- **LLM cost.** A dry run over tens of thousands of artifacts still runs Opus and Cohere extraction. That is visible in s36's ledger and is bounded by the rate limit. Promote avoids paying a second time.
- **Edits to other wave-5 files** (s15's apply runner, s17's write-back) are a merge-conflict risk. They are three and two tiny insertions; the merger replays them on the merged code.
- **FolderSource** moves files into `processed/` and `failed/` inside the backlog folder. This is the intended resume mechanism, but operators should know the folder is changed.
- The `PAUSED_NOT_BEFORE` sentinel on `OUTBOX.NOT_BEFORE` bends s03's "NOT_BEFORE is always now" rule for paused rows. The relay's semantics are unchanged (rows past `now` are just not claimed yet).
- The `live_outbox_waiting` EXISTS probe runs at most once per second, against the `IX_OUTBOX_PENDING` index. It is cheap on ATP but untested at volume; **VERIFY** in the `-m atp` relay test.
