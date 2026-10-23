# s45-data-retention-purge: plan

Issue #45, wave 4, `breaking: false`. Purges raw artifacts, extraction payloads and history payloads of
terminal work items once the configured retention period has passed, and keeps the decision trail
(tombstones, provenance, confidence, summary columns, actors, reasoning). Triggered on demand
(`POST /admin/retention/purge`) or by the intake poller's cycle hook; no scheduler.

## Standards followed

- **CLAUDE.md:** no scheduler and no third poller (the purge piggybacks on the intake poller's s06 cycle
  hook, rate-limited to once an hour); layered architecture (router → `RetentionService` → repositories;
  the router never imports SQLAlchemy; only `cashapp/data/` touches the ORM); repositories never commit,
  the service owns every transaction; every automated decision auditable from the item's history (the
  tombstone row); `CONTENT_HASH` untouched so intake dedupe keeps working; customer PII never logged
  (logs carry item ids, counts and key *counts* only); periods are configuration (`retention.*` from s02's
  registry, read through s28's `RetentionConfig`), default null = keep.
- **python-web-app:building-python-web-apps:** logic in a service, router thin, `Annotated` deps, one
  error shape (s01 `ApiError`), mutation by POST only.
- **python-library-quality:guarding-destructive-operations:** the destructive path refuses instead of
  warning; the terminal-state and age guards are re-checked under a row lock (`get_for_update`) ahead of
  the first mutation; object keys go through s06 `validate_key` before `delete`; dry-run uses the exact
  same selection code as the real run; a shared object key is never deleted while another non-purged item
  still references it; `dry_run` is a **required** body field (no default), so an empty POST cannot purge.
- **research.md:** exactly two `ObjectStore` implementations (s06's); tests use `LocalFolderObjectStore`.
  Wave-4 story, one Alembic revision on the current head.

## Files to touch (all new except the one-line append, file-disjoint from other stories)

| Path | Contents |
|---|---|
| `api/src/cashapp/domain/retention.py` | `PurgeKind`, `PurgeStatus` StrEnums, `PurgeReport` (frozen dataclass), `TOMBSTONE_REASONING` constants, `RETENTION_AUDIT_KEY = "retention.purge"`. Pure. |
| `api/src/cashapp/data/models/retention.py` | ORM `RetentionPurge` (table `retention_purge`), auto-loaded by s02 `load_all_models()`. |
| `api/src/cashapp/data/repositories/retention.py` | `RetentionRepository`: candidate selection, adjudication/history bulk nulling, pending-purge rows, shared-key check. The only place s45 queries are written. |
| `api/src/cashapp/services/retention/__init__.py` | re-exports `RetentionService`, `RetentionCycleHook`, `PurgeReport`. Does **not** self-register the hook (see hook wiring). |
| `api/src/cashapp/services/retention/service.py` | `RetentionService` (the purge algorithm). |
| `api/src/cashapp/services/retention/hook.py` | `RetentionCycleHook` (once-per-hour gate, in-memory per process). |
| `api/src/cashapp/api/routers/retention.py` | `router` (prefix `/admin/retention`), `PurgeRequest`, `PurgeReportResponse`; auto-discovered by s01. |
| `api/src/cashapp/api/storage_deps.py` | `get_object_store()` (cached `build_object_store(get_settings())`), `ObjectStoreDep`. New; if another story already shipped an equivalent API dependency by merge time, use it and drop this file (non-negotiable 7). |
| `api/src/cashapp/pollers/intake/hooks.py` | **append only** (owned by s06), at the bottom: `from cashapp.services.retention.hook import RetentionCycleHook` and `register_hook(RetentionCycleHook())` — or `CYCLE_HOOKS.append(RetentionCycleHook())` if s06 has no helper. Guarded so a re-import never appends twice (`if not any(isinstance(h, RetentionCycleHook) for h in CYCLE_HOOKS)`). |
| `api/alembic/versions/s45_retention_purge.py` | the one revision (see Migrations). |
| `api/tests/support/retention.py` | `seed_terminal_item(uow, store, *, state, updated_at, parts=2, readings=2, adjudication=True, history_payloads=2) -> SeededItem` builder (synthetic data only: payer "Example Payer Co", `INV-10001…`). |
| tests listed in the TEST PLAN | written and run in step 5 only. |

Not touched: s06 models/repositories (uses `ArtifactPartRepository.for_items/mark_purged`), s08
repositories (uses `ExtractionReadingRepository.purge_outputs`), s09 files (adjudication updates live in
`RetentionRepository`), s28 (uses `ConfigAudit.record`, `RetentionConfig`), `main.py` (router discovery).

### Why the hook is registered in `hooks.py`

s06's plan expected s45 to append from its own package `__init__`, "imported by s30's discovery". s30's
discovery only imports `cashapp.stations`, `cashapp.pollers` and `cashapp.pipeline`, so a module under
`cashapp/services/retention/` would never be imported in the worker and the hook would silently never run.
The story's ownership line already allows "appends one hook to `cashapp/pollers/intake/hooks.py`", so the
registration is a two-line append at the bottom of that file. No import cycle: `retention.hook` satisfies
`CycleHook` structurally and does not import `hooks.py`. Logged as an assumption; s41 should do the same.

## Design

### Eligibility (one rule, used by every category)

An item is eligible for category *c* when `WORK_ITEM.STATE in TERMINAL_STATES` (s02: DONE, ARCHIVED) **and**
`WORK_ITEM.UPDATED_AT < now - timedelta(days=period_c)` **and** it still has unpurged data of that
category. `period_c is None` → the category is skipped entirely (no query, count 0). Periods `<= 0` are
already refused by s02's registry validator (int ≥ 1 or null); the service also treats `<= 0` as "skip" and
logs a warning (defence in depth, never "purge everything").

| Category | Period key | Unpurged data |
|---|---|---|
| artifacts | `raw_artifact_days` | no `RETENTION_PURGE(kind=ARTIFACT)` row for the item **and** (the item has an `ARTIFACT_PART` row with `PURGED_AT IS NULL` **or** `ARTIFACT_KEY IS NOT NULL`) |
| readings | `extraction_days` | `EXTRACTION_READING` with `PURGED_AT IS NULL` |
| adjudications | `extraction_days` | `ADJUDICATION` with `PURGED_AT IS NULL` |
| history payloads | `history_payload_days` | `WORK_ITEM_HISTORY` with `PAYLOAD IS NOT NULL AND PURGED_AT IS NULL` |

The purge never updates `WORK_ITEM` itself, so purging does not bump `UPDATED_AT` and the summary columns
(amount, currency, dates, customer, content hash, statuses) stay.

### `RetentionService.purge`

```
report = PurgeReport(dry_run, now, cutoffs…)
0. resume: for each RETENTION_PURGE row with STATUS=PENDING (oldest first, up to limit) → steps 3–4
   (crash recovery; counts go to report.resumed)
1. artifacts (if period set), in batches of min(batch_size, remaining limit), until no candidates or limit:
   tx1 (own UoW):
     ids = repo.artifact_candidates(cutoff, limit=batch)           # ordered by id, no lock
     for id in ids: item = work_items.get_for_update(id, skip_locked=True)
         re-check terminal + UPDATED_AT < cutoff; else skip (counted in report.skipped)
     parts = artifact_parts.for_items(locked_ids)
     keys  = item.artifact_key (if set) + each part.object_key + text_key_for(object_key) when
             text_preview_chars is not None   → validate_key each
     deletable = keys minus repo.keys_still_referenced(keys, excluding_item_ids=locked_ids)
     if dry_run: count, rollback, continue
     per item: insert RETENTION_PURGE(work_item_id, kind=ARTIFACT, status=PENDING,
               object_keys=deletable keys for this item, created_at=now)
               record_history(DECISION, reasoning=TOMBSTONE_ARTIFACT.format(hash, n_parts, total_bytes),
               payload={"kind": "retention.artifact_purged", "content_hash", "parts": [{part_no, kind,
               size_bytes}], "total_bytes", "object_keys_deleted": n, "object_keys_kept_shared": m,
               "policy_days": d}, actor = principal)
     commit                                         # tombstone + pending marker durable BEFORE any delete
   deletes: for key in pending.object_keys: await object_store.delete(key)   # idempotent
   tx2: artifact_parts.mark_purged(parts, at=now); repo.confirm(pending rows, at=now); commit
2. readings + adjudications (if extraction_days set), batches:
   one tx per batch: ids = repo.extraction_candidates(cutoff, limit)
     readings = ExtractionReadingRepository.purge_outputs(ids, at=now)       # s08
     adjudications = repo.purge_adjudications(ids, at=now)                   # FINAL, DISAGREEMENTS = NULL
     commit (dry_run: count via repo.count_* and roll back)
3. history payloads (if history_payload_days set), batches:
   one tx per batch: ids = repo.history_candidates(cutoff, limit) (history row ids)
     n = repo.purge_history_payloads(ids, at=now)                             # PAYLOAD = NULL, PURGED_AT = now
     commit
return report
```

- **Crash safety (AC5).** The only external side effect is the Object Storage delete, and it always runs
  after a committed tombstone + `RETENTION_PURGE(PENDING)` row. A crash before tx1 commits leaves nothing
  changed; a crash between tx1 and tx2 leaves a PENDING row whose deletes are re-run (idempotent) and
  confirmed by step 0 of the next purge. `ARTIFACT_PART.PURGED_AT` is set only after deletes succeed. So
  no DB row ever points at a deleted object without a tombstone, and nothing is left un-purgeable. A failed
  delete (non-404 error) leaves the row PENDING, is logged (item id, exception type) and the run continues.
- **Shared keys.** The original artifact of an email is shared by the envelope item and its child items
  (s06: same `ARTIFACT_KEY`). `keys_still_referenced` returns the keys still referenced (via
  `WORK_ITEM.ARTIFACT_KEY` or `ARTIFACT_PART.OBJECT_KEY`) by an item outside this batch that has no
  `RETENTION_PURGE(ARTIFACT)` row. Those keys are kept and listed in the tombstone count; the last item
  to be purged deletes them.
- **Concurrency.** `UQ_RETENTION_PURGE_ITEM_KIND (WORK_ITEM_ID, KIND)` makes a second concurrent purge of
  the same item fail with a unique violation (s06's `is_unique_violation`) → that batch rolls back and the
  item is skipped. Readings/adjudication/history nulling is idempotent (`… AND PURGED_AT IS NULL`), so no
  row locks are needed there. Candidate selection uses `FETCH FIRST n` without `FOR UPDATE` (Oracle refuses
  `FETCH FIRST` with `FOR UPDATE`); locking is per item through `get_for_update`.
- **Bounded batches.** `limit` caps rows touched per category per run (items for artifacts, items for
  extraction, history rows for history payloads); each batch is `min(batch_size=50, remaining)` and its own
  transaction.
- **Actor.** `principal` defaults to s04 `SYSTEM_PRINCIPAL`; tombstones use s04's Principal→actor helper
  (HUMAN actor with subject/display name for a person, SYSTEM otherwise).

### `RetentionCycleHook`

```python
class RetentionCycleHook:          # satisfies s06 CycleHook
    def __init__(self, *, min_interval: timedelta = timedelta(hours=1), limit: int = 100) -> None
    async def on_cycle(self, container: Container, now: datetime) -> None
```

In-memory `_last_run: datetime | None` per process (no `CONFIG_SETTING` marker: config writes are
versioned and audited, a marker would spam `CONFIG_CHANGE`). If `_last_run` is set and `now - _last_run <
min_interval` → return. Otherwise set `_last_run = now` **before** running (a failing purge does not retry
every cycle), read `(await container.config.snapshot()).retention()`, return early when all three periods
are null, else `RetentionService(cfg).purge(container.uow_factory, container.resolve(ObjectStore), now,
limit=100)` and log the report counts. Exceptions propagate to s06's `run_cycle_hooks`, which logs and
swallows them. With several intake processes each may run once an hour; that is safe (unique key + idempotent
nulling).

### Router

`POST /admin/retention/purge`, `require_permission(Permission.CONFIG_WRITE)`, body `PurgeRequest{dry_run:
bool}` (required, `extra="forbid"`). Calls `RetentionService(await runtime.retention()).purge(uow_factory,
object_store, clock.now(), dry_run=..., limit=500, principal=principal)`, then in its own UoW
`ConfigAudit.record(uow, "retention.purge", None, report.to_json(), principal, reason=f"retention purge
(dry_run={dry_run})")` and commits. The audit write lives in the service (`RetentionService.record_run`) so
the router stays free of persistence. Returns `200 PurgeReportResponse`. 403 is s04's `forbidden`.

## Interfaces provided (pinned)

```python
# cashapp/domain/retention.py
class PurgeKind(StrEnum): ARTIFACT = "ARTIFACT"
class PurgeStatus(StrEnum): PENDING = "PENDING"; CONFIRMED = "CONFIRMED"
RETENTION_AUDIT_KEY: Final = "retention.purge"
TOMBSTONE_ARTIFACT: Final = "artifact purged under retention policy (content_hash={hash}, parts={parts}, bytes={bytes})"

@dataclass(frozen=True, slots=True)
class PurgeReport:
    dry_run: bool
    ran_at: datetime
    artifacts: int            # items whose raw artifact was purged (or would be)
    parts: int                # ARTIFACT_PART rows purged
    readings: int             # EXTRACTION_READING rows nulled
    adjudications: int        # ADJUDICATION rows nulled
    history_payloads: int     # WORK_ITEM_HISTORY payloads nulled
    objects_deleted: int = 0
    objects_kept_shared: int = 0
    resumed: int = 0          # PENDING purges completed from an earlier crash
    skipped: int = 0          # candidates no longer eligible under lock / concurrent purge
    def to_json(self) -> dict[str, JsonValue]: ...

# cashapp/services/retention/service.py
class RetentionService:
    def __init__(self, config: RetentionConfig, *, batch_size: int = 50) -> None
    async def purge(self, uow_factory: UowFactory, object_store: ObjectStore, now: datetime, *,
                    dry_run: bool = False, limit: int = 500,
                    principal: Principal = SYSTEM_PRINCIPAL) -> PurgeReport
    @staticmethod
    async def record_run(uow_factory: UowFactory, report: PurgeReport, principal: Principal) -> None
        # ConfigAudit.record(RETENTION_AUDIT_KEY, None, report.to_json(), principal, reason) + commit

# cashapp/services/retention/hook.py
class RetentionCycleHook:   # CycleHook
    def __init__(self, *, min_interval: timedelta = timedelta(hours=1), limit: int = 100) -> None
    async def on_cycle(self, container: Container, now: datetime) -> None

# cashapp/data/models/retention.py   (table retention_purge -> RETENTION_PURGE)
class RetentionPurge(Base):
    id: int (identity PK, PK_RETENTION_PURGE); work_item_id: int (FK work_item.id, FK_RETENTION_PURGE_ITEM)
    kind: PurgeKind (StrEnumType VARCHAR2(40)); status: PurgeStatus (StrEnumType VARCHAR2(20))
    object_keys: list[str] (JsonDoc, not null)   # keys this purge deletes
    created_at: datetime (UtcDateTime); confirmed_at: datetime | None
    # UQ_RETENTION_PURGE_ITEM_KIND (work_item_id, kind); IX_RETENTION_PURGE_STATUS (status, created_at)

# cashapp/data/repositories/retention.py
class RetentionRepository(BaseRepository[RetentionPurge]):
    async def artifact_candidates(self, cutoff: datetime, *, limit: int) -> list[int]
    async def extraction_candidates(self, cutoff: datetime, *, limit: int) -> list[int]
    async def history_candidates(self, cutoff: datetime, *, limit: int) -> list[int]      # history row ids
    async def keys_still_referenced(self, keys: Collection[str], *, excluding_item_ids: Collection[int]) -> set[str]
    async def pending(self, *, limit: int) -> list[RetentionPurge]
    async def confirm(self, rows: Sequence[RetentionPurge], *, at: datetime) -> None
    async def purge_adjudications(self, item_ids: Sequence[int], *, at: datetime) -> int
    async def purge_history_payloads(self, history_ids: Sequence[int], *, at: datetime) -> int
    async def count_readings(self, item_ids: Sequence[int]) -> int        # dry-run counts
    async def count_adjudications(self, item_ids: Sequence[int]) -> int

# cashapp/api/storage_deps.py
def get_object_store() -> ObjectStore          # lru_cache; build_object_store(get_settings())
ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]

# cashapp/api/routers/retention.py
class PurgeRequest(BaseModel): model_config = ConfigDict(extra="forbid"); dry_run: bool
class PurgeReportResponse(BaseModel): dry_run, ran_at, artifacts, parts, readings, adjudications,
    history_payloads, objects_deleted, objects_kept_shared, resumed, skipped
router: APIRouter   # POST /admin/retention/purge -> 200 PurgeReportResponse (config:write)
```

### Consumed (from other stories)

- s02: `WorkItem`, `WorkItemHistory` (`payload`, `purged_at`), `TERMINAL_STATES`, `HistoryAction.DECISION`,
  `record_history`, `HistoryEntry`, `UnitOfWork`, `UowFactory`, `WorkItemRepository.get_for_update`, `Clock`.
- s04: `Permission.CONFIG_WRITE`, `require_permission`, `Principal`, `SYSTEM_PRINCIPAL`, the Principal→actor helper, `UowFactoryDep`.
- s06: `ObjectStore.delete`, `validate_key`, `text_key_for`, `ArtifactPart.purged_at`,
  `ArtifactPartRepository.for_items/mark_purged`, `is_unique_violation`, `CycleHook`, `CYCLE_HOOKS`,
  `build_object_store`.
- s08: `ExtractionReading`, `ExtractionReadingRepository.purge_outputs`.
- s09 (plan not yet written; coded against the story): ORM `Adjudication` (table `ADJUDICATION`) with
  nullable `final` and `disagreements` (JsonDoc), `provenance`, `confidence`, `purged_at` (nullable
  UtcDateTime), `work_item_id`. **Requirement on s09:** `FINAL` and `DISAGREEMENTS` must be nullable and
  `PURGED_AT` must exist; if s09 ships a `purge_payloads` repository method, use it instead of
  `RetentionRepository.purge_adjudications` (DRY).
- s28: `RetentionConfig`, `RuntimeConfigDep`, `ConfigSnapshot.retention()`, `ConfigAudit.record`.
- s30: `Container.uow_factory`, `.config`, `.resolve(ObjectStore)`.

## Migrations

- One revision `api/alembic/versions/s45_retention_purge.py`, `revision = "s45_retention_purge"`,
  hand-written. **Expected parent: the head at merge time** (at least after s09's `ADJUDICATION` revision);
  the merger re-points `down_revision` and checks `alembic heads` returns exactly one head. DEV ATP only.
- `upgrade()`: `create_table("RETENTION_PURGE")`: `ID` identity PK (`PK_RETENTION_PURGE`); `WORK_ITEM_ID
  NUMBER NOT NULL` FK → `WORK_ITEM.ID` (`FK_RETENTION_PURGE_ITEM`); `KIND VARCHAR2(40) NOT NULL`; `STATUS
  VARCHAR2(20) NOT NULL`; `OBJECT_KEYS JSON NOT NULL`; `CREATED_AT TIMESTAMP WITH TIME ZONE NOT NULL`;
  `CONFIRMED_AT TIMESTAMP WITH TIME ZONE NULL`; `UQ_RETENTION_PURGE_ITEM_KIND (WORK_ITEM_ID, KIND)` (also
  serves the FK); `IX_RETENTION_PURGE_STATUS (STATUS, CREATED_AT)`. No CHECK constraints (s02 enum rule).
- `downgrade()` drops the table.
- No column added to other stories' tables: `ARTIFACT_PART.PURGED_AT` (s06), `EXTRACTION_READING.PURGED_AT`
  (s08), `ADJUDICATION.PURGED_AT` (s09), `WORK_ITEM_HISTORY.PURGED_AT` (s02) already exist.

## TEST PLAN (written and run in step 5 only)

Fixtures: s02 `uow_factory` (sqlite) / `atp_uow_factory` (`-m atp`), `FrozenClock`; s06
`LocalFolderObjectStore(tmp_path)`; s28 `make_config_snapshot`/`make_runtime_config`; s04 `make_principal`,
`override_principal`; s30 `make_worker_container`; `tests/support/retention.py::seed_terminal_item`.

| AC | Test | Asserts |
|---|---|---|
| 1 | `api/tests/unit/services/retention/test_purge_eligibility.py::test_only_terminal_items_older_than_period_are_purged` | DONE and ARCHIVED items older than the period are purged; PENDING, IN_PROGRESS, AWAITING_RECEIPT, ESCALATED items of any age untouched; a DONE item younger than the period untouched. |
| 1 | `…::test_null_period_skips_category` | each category with a null period: zero counts, no rows changed, no `ObjectStore.delete` call (spy store), no query for that category. |
| 1 | `…::test_report_counts_per_category` | `PurgeReport` fields equal the rows touched per category. |
| 1 | `…::test_dry_run_counts_without_writing` | dry run returns the same counts as the real run would, no DB change, no object deleted, no `RETENTION_PURGE` row. |
| 2 | `api/tests/integration/retention/test_artifact_purge.py::test_deletes_original_and_parts_and_marks_purged` | `artifacts/{hash}/original`, parts and `.txt` objects gone from the local store; `ARTIFACT_PART.PURGED_AT == now`; `WORK_ITEM.CONTENT_HASH` unchanged and `by_content_hash` still finds the item; `UPDATED_AT` unchanged. |
| 2 | `…::test_tombstone_history_row` | one DECISION row, reasoning starts "artifact purged under retention policy" and names the hash; payload has content_hash, per-part sizes, total_bytes. |
| 2 | `…::test_shared_original_kept_until_last_item_purged` | envelope + two children share the original; only one child eligible → original kept, counted in `objects_kept_shared`; all eligible → original deleted. |
| 2 | `…::test_duplicate_intake_after_purge_still_dedupes` | `ingest` of the same bytes after purge lands in the duplicate branch. |
| 3 | `api/tests/integration/retention/test_extraction_purge.py::test_readings_and_adjudication_payloads_nulled` | `EXTRACTION_READING.OUTPUT` null + `PURGED_AT` set; `ADJUDICATION.FINAL/DISAGREEMENTS` null + `PURGED_AT` set; `PROVENANCE`, confidence, model/prompt/schema versions intact; item amount, currency, payment date, customer account unchanged. |
| 4 | `api/tests/integration/retention/test_history_purge.py::test_history_payloads_nulled_trail_kept` | `PAYLOAD` null + `PURGED_AT` set; action, actor, stages, states, error_code, reasoning unchanged; rows of non-eligible items untouched. |
| 4 | `…::test_tombstone_facts_survive_history_purge` | after a history purge the tombstone reasoning still carries hash, parts and bytes. |
| 5 | `api/tests/unit/services/retention/test_purge_batches.py::test_batches_commit_separately_and_respect_limit` | limit 7, batch 3 → 3 commits (spy UoW), at most 7 items per category. |
| 5 | `…::test_crash_after_pending_commit_is_resumed` | store whose `delete` raises after tx1 → `RETENTION_PURGE` PENDING and tombstone exist, `ARTIFACT_PART.PURGED_AT` null; next `purge` deletes, confirms, sets `PURGED_AT`, `report.resumed == 1`. |
| 5 | `…::test_crash_before_commit_changes_nothing` | failure inside tx1 → no tombstone, no pending row, no object deleted. |
| 5 | `…::test_no_object_deleted_before_tombstone_committed` | ordering spy: every `delete` call happens after the commit that wrote the tombstone. |
| 5 | `…::test_item_reopened_under_lock_is_skipped` | candidate whose state flips to PENDING before the lock → skipped, counted, untouched. |
| 5 | `…::test_concurrent_purge_unique_violation_skips_item` | pre-existing `RETENTION_PURGE(ARTIFACT)` row for the item → no second tombstone, no error. |
| 5 | `api/tests/integration/retention/test_retention_purge_atp.py::test_purge_on_atp` (`-m atp`) | the same purge against DEV ATP: SQL valid on Oracle (no `FETCH FIRST … FOR UPDATE`), JSON nulling works. |
| 5 | `api/tests/integration/retention/test_migration_retention_purge.py::test_upgrade_downgrade` (sqlite + `-m atp`) | table, PK, FK, unique key and index as listed; downgrade drops it; `alembic heads` returns one head. |
| 6 | `api/tests/api/test_retention_router.py::test_purge_requires_config_write` | viewer/operator → 403 `forbidden` in the one error shape; no purge. |
| 6 | `…::test_purge_returns_report_and_audits_principal` | admin, `{"dry_run": false}` → 200 with all report fields; one `CONFIG_CHANGE` row, key `retention.purge`, actor = principal; tombstones carry the principal as actor. |
| 6 | `…::test_dry_run_body_required` | `{}` → 422; `{"dry_run": true, "x": 1}` → 422. |
| 6 | `…::test_dry_run_audited_without_purge` | dry run → 200, audit row written with `dry_run: true`, nothing purged. |
| 6 | `api/tests/unit/test_layering_retention.py::test_router_does_not_import_sqlalchemy` | the router module's imports contain no `sqlalchemy`. |
| 7 | `api/tests/unit/services/retention/test_hook.py::test_hook_registered_once_in_cycle_hooks` | importing `cashapp.pollers.intake.hooks` (twice / reload) leaves exactly one `RetentionCycleHook` in `CYCLE_HOOKS`. |
| 7 | `…::test_runs_at_most_once_per_hour` | `on_cycle` at t, t+10 min, t+59 min → one purge; t+60 min → second purge (spy service). |
| 7 | `…::test_uses_limit_100_and_container_services` | purge called with `limit=100`, the container's `uow_factory` and `resolve(ObjectStore)`. |
| 7 | `…::test_all_periods_null_does_nothing` | no purge call, no DB query. |
| 7 | `…::test_failure_does_not_rerun_every_cycle` | purge raises → exception propagates to `run_cycle_hooks` (logged, swallowed); the next cycle inside the hour does not run it. |

## Assumptions / deviations

- **Hook registration lives in `hooks.py`** (two-line append), not in `cashapp/services/retention/__init__.py`
  as s06's plan suggested, because s30's discovery never imports `cashapp.services`. The story's ownership
  line allows this append.
- **`RETENTION_PURGE` table added** (not in the ACs) to make AC5's "recorded as pending, then confirmed"
  real: `ARTIFACT_PART.PURGED_AT` alone cannot express "pending", and setting it before the delete would
  leave un-purgeable leaked objects after a crash.
- **`RetentionService` takes `RetentionConfig` in its constructor**, so `purge(uow_factory, object_store,
  now, *, dry_run, limit)` matches AC1 exactly; `principal` is an added keyword with a system default.
- **`PurgeReport` has extra fields** (`objects_deleted`, `objects_kept_shared`, `resumed`, `skipped`,
  `ran_at`, `dry_run`) beyond AC1's five counts. Additive.
- **Hourly marker is in-memory per process** (the story allows either); a restart may run one extra purge, which is harmless.
- **Readings and adjudications share `extraction_days`** (one period for "extraction payloads", per AC3).
- **Dry runs are audited too** (`retention.purge`, `dry_run: true`) so "who looked" is also traceable.
- **`dry_run` is required in the body**, so an empty POST is a 422 and never a destructive purge.
- **Shared original artifacts** are deleted only when the last referencing item is purged (s06 shares
  `ARTIFACT_KEY` between an envelope and its children).
- `WORK_ITEM.ARTIFACT_KEY` is left in place after a purge; the tombstone and `ARTIFACT_PART.PURGED_AT` say
  the object is gone. The s19 artifact viewer should show "purged under retention policy" when
  `ArtifactPurged` / `ObjectNotFound` is raised.

## Risks

- **s09 not yet planned:** the `ADJUDICATION` column names (`FINAL`, `DISAGREEMENTS`, `PROVENANCE`,
  `PURGED_AT`) are taken from the story. If s09 names them differently or makes `FINAL` not null, the coder
  adapts `purge_adjudications` and flags it at merge.
- **`storage_deps.py` duplication:** another story (s19/s20 artifact viewer) may add an API `ObjectStore`
  dependency. The merger keeps one.
- **Oracle SQL:** bulk `UPDATE … WHERE ID IN (…)` with up to 50 ids is fine; candidate queries join
  `WORK_ITEM` on `(STATE, UPDATED_AT)`. There is no index on `UPDATED_AT`; a full scan of `WORK_ITEM` once
  an hour is acceptable at expected volumes. If volumes grow, add `IX_WORK_ITEM_STATE_UPDATED`
  (a follow-up, not in this story).
- **Request duration:** `limit=500` per category through the API, including Object Storage deletes, can take
  tens of seconds. Acceptable for an admin action; the API applies no extra timeout. Repeat calls continue
  where the previous one stopped.
- **Multiple intake processes** may each run the hourly purge; correctness relies on the unique key and
  idempotent nulling, which are tested.
- **Irreversible:** deleted objects cannot be recovered. Mitigations: null periods by default (keep),
  terminal-only, re-check under lock, required `dry_run` field, `config:write` only, every run audited.
