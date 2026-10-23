# Plan: s40-item-locking

Issue #40. Wave 2 (per waves.json, wave index 1, parallel with s03). Paths: `cashapp/` = `api/src/cashapp/`.
No migration: the lock columns already exist on `WORK_ITEM` (s02).

## Standards followed

- CLAUDE.md *Self-healing*: when a person dequeues an item, it is locked so automation never acts behind them. Requeue goes through the same runner (s18 calls `release`). *Authentication*: services receive `Principal` as a plain argument, every human action goes on the item's history, and authorization is enforced in the API through `require_permission`.
- Layering: the router imports no SQLAlchemy; the service touches no `Request`; the repository has no rules and never commits; the service owns the transaction scope it is given (the caller's `uow`). The router commits.
- s01: one error shape (`ApiError`) and router auto-discovery (no `main.py` edit). s02: `BaseRepository`, `UnitOfWork`, `record_history` (the only history writer), `Clock`. s04: `Principal`, `Permission.ITEMS_WORK/ITEMS_READ`, `require_permission`, `UowFactoryDep`. s28: `RuntimeConfigDep`, `ConfigSnapshot.locks().lease_minutes`.
- `python-web-app:building-python-web-apps`: logic in services, `Annotated` deps, mutations through POST/DELETE only, no state-changing GET.
- DRY (non-negotiable 7): `LockInfoOut`, the lock error mapping and the liveness rule each exist once here. s18, s19 and s20 import them and don't redefine them.
- Lazy expiry: `LOCK_EXPIRES_AT <= now` means free, everywhere. There is no sweeper and no third poller.

## Files to touch (all new, all owned by this story)

| Path | Content |
|---|---|
| `cashapp/services/locking.py` | `LockInfo`, the `LockError` hierarchy, `is_locked_for_automation`, `lock_info_for`, `LockService` |
| `cashapp/services/actor.py` | `ActorFields`, `actor_fields(principal)` (Principal → `HistoryEntry` actor kwargs). See Assumptions. |
| `cashapp/data/repositories/locks.py` | `ItemLockRepository(BaseRepository[WorkItem])`: the **only** code that assigns `lock_*` attributes |
| `cashapp/api/schemas/locks.py` | `LockInfoOut`, `ForceTakeIn`, `lock_error_to_api` |
| `cashapp/api/routers/locks.py` | `router` with the 5 endpoints; `get_lock_service` dependency |
| `api/tests/support/locks.py` | `make_lock_service(...)`, `lock_item(...)` test helpers |
| tests in the TEST PLAN | written in step 5 only |

Not touched: `main.py`, `models/work_item.py`, `repositories/work_items.py`, `api/deps.py`, the lockfiles, any Alembic revision.

## Design

### Liveness rules (pinned; used by s03, s18, s19, s20)

- **Live lock:** `lock_owner is not None and lock_expires_at is not None and lock_expires_at > now`.
- **Live claim:** `state == IN_PROGRESS and claim_expires_at is not None and claim_expires_at > now`. An `IN_PROGRESS` item whose claim has expired (a crashed worker) can be locked.
- On release, all four lock columns are set to NULL. Lazy expiry leaves them in place. The stale `lock_owner` is what lets the same owner "renew after expiry" (AC3).
- Every lock write sets `updated_at = clock.now()` explicitly. The ORM `onupdate` would also fire, but the explicit value keeps tests deterministic. `version` bumps through s02's `version_id_col`.

### Concurrency

- Every mutating method loads the row with `ItemLockRepository.get_for_lock(item_id)`, which is `SELECT … FOR UPDATE` (waiting, *not* SKIP LOCKED). It serializes against s03's short claim transaction and against a second person clicking Dequeue at the same moment: the loser waits, then sees the winner's live lock and gets `LockConflict`.
- `version_id_col` gives a second safety net: a stale write raises `StaleDataError`, which the router maps to 409 `lock_conflict` after re-reading the row.

### Behaviour table

| Call | Precondition → outcome | History row (ACTION=LOCK) |
|---|---|---|
| `acquire` | Item missing → `ItemNotFound`. Live claim → `ItemBusy`. Live lock by another → `LockConflict(owner_name, acquired_at)`. Live lock by self → renew (new `expires_at`, `acquired_at` kept). Otherwise → set owner, name, `acquired_at=now`, `expires_at=now+lease`. | Yes, `event="acquire"`, except for the live-self renew (no row) |
| `renew` | Item missing → `ItemNotFound`. `lock_owner != principal.subject` (including NULL) → `LockNotHeld`. Live and own → extend `expires_at`. Expired and own: a live claim → `ItemBusy`; otherwise re-acquire (`acquired_at=now`). | Only when the lock had expired: `event="renew_after_expiry"` |
| `release` | Item missing → `ItemNotFound`. `lock_owner is None` → no-op (idempotent, no row). `lock_owner != subject` → `LockNotHeld`. Own (live or expired) → clear the columns. | Yes, `event="release"` (not for the no-op) |
| `force_take` | `principal` lacks `ITEMS_WORK` → `LockForbidden`. `reason.strip()` empty → `LockReasonRequired`. Item missing → `ItemNotFound`. Live claim → `ItemBusy`. Otherwise → take the lock (works whether or not a lock exists). | Yes, `event="force_take"`, `reasoning=reason`, payload holds the previous owner, name and expiry |

- The history payload is always `{"event", "expires_at" (ISO or null), ...}`. The actor comes from `actor_fields(principal)`, so `actor_kind=USER`.
- `acquire` also requires `ITEMS_WORK` (`LockForbidden`), which is defence in depth beyond the router guard. The `SYSTEM_PRINCIPAL` is refused with `LockForbidden`: automation never takes a human lock.
- Locking is allowed in any state, terminal included, because s38 reverses applications on DONE items while they are locked.
- The service only flushes. The router (or s18's requeue) commits.

## Interfaces provided (pinned)

```python
# cashapp/services/locking.py
@dataclass(frozen=True, slots=True)
class LockInfo:
    item_id: int
    owner: str            # Principal.subject
    owner_name: str       # Principal.display_name at acquire time
    acquired_at: datetime # tz-aware UTC
    expires_at: datetime

class LockError(Exception):
    item_id: int
class ItemNotFound(LockError): ...
class LockConflict(LockError):
    owner_name: str; acquired_at: datetime
class ItemBusy(LockError): ...
class LockNotHeld(LockError): ...
class LockForbidden(LockError): ...         # missing ITEMS_WORK, or a system principal
class LockReasonRequired(LockError): ...    # force_take with a blank reason

def is_lock_live(item: WorkItem, now: datetime) -> bool
def is_locked_for_automation(item: WorkItem, now: datetime) -> bool   # == is_lock_live; the name automation code uses
def lock_info_for(item: WorkItem, now: datetime | None = None) -> LockInfo | None   # live locks only; now=None -> SystemClock().now()

class LockService:
    def __init__(self, config: RuntimeConfig | ConfigSnapshot, clock: Clock | None = None) -> None
        # lease = (await config.locks()).lease_minutes if RuntimeConfig, else config.locks().lease_minutes
    async def acquire(self, uow: UnitOfWork, item_id: int, principal: Principal) -> LockInfo
    async def renew(self, uow: UnitOfWork, item_id: int, principal: Principal) -> LockInfo
    async def release(self, uow: UnitOfWork, item_id: int, principal: Principal, *, redrive: bool = True) -> None
        # redrive: when the item is PENDING, emit StageEvent(stage=item.stage) via s03 emit (same tx); s18 requeue passes False
    async def force_take(self, uow: UnitOfWork, item_id: int, principal: Principal, reason: str) -> LockInfo
    async def get(self, uow: UnitOfWork, item_id: int) -> LockInfo | None       # ItemNotFound if the item is missing
    is_locked_for_automation = staticmethod(is_locked_for_automation)
    lock_info_for = staticmethod(lock_info_for)
    @staticmethod
    def assert_held_by(item: WorkItem, principal: Principal, now: datetime) -> None   # LockNotHeld unless a live lock owned by principal.subject

LOCK_HISTORY_EVENTS: Final = ("acquire", "renew_after_expiry", "release", "force_take")
```

Consumer rules:
- **s18** handlers: `if is_locked_for_automation(ctx.item, ctx.clock.now()): return <no-op>`. The requeue path calls `LockService.assert_held_by(item, principal, now)` first, then `await lock_service.release(uow, item_id, principal, redrive=False)` in the same transaction (requeue emits its own event).
- **s19** item and flow APIs: `lock: LockInfoOut | None = LockInfoOut.from_info(lock_info_for(item, now))`.
- **s03** doesn't import this module. Its claim uses s02's `WorkItemRepository.claim`, which already encodes the same rule in SQL. A unit test here asserts that the two agree (see AC5).

```python
# cashapp/services/actor.py
class ActorFields(TypedDict):
    actor_kind: ActorKind; actor_id: str; actor_name: str
def actor_fields(principal: Principal) -> ActorFields
    # system principal -> (SYSTEM, SYSTEM_ACTOR_ID, SYSTEM_ACTOR_NAME); else (USER, subject, display_name)
# usage: HistoryEntry(action=..., **actor_fields(principal), ...)
```

```python
# cashapp/data/repositories/locks.py
class ItemLockRepository(BaseRepository[WorkItem]):
    model = WorkItem
    async def get_for_lock(self, item_id: int) -> WorkItem | None      # SELECT ... FOR UPDATE (wait)
    async def write_lock(self, item: WorkItem, *, owner: str, owner_name: str,
                         acquired_at: datetime, expires_at: datetime, now: datetime) -> WorkItem   # sets 4 cols + updated_at; flush
    async def clear_lock(self, item: WorkItem, *, now: datetime) -> WorkItem   # NULLs 4 cols + updated_at; flush
    async def live_locks_by_owner(self, owner: str, *, now: datetime) -> list[WorkItem]   # for s20 "Locked by me"
```

```python
# cashapp/api/schemas/locks.py
class LockInfoOut(BaseModel):
    item_id: int; owner: str; owner_name: str; acquired_at: datetime; expires_at: datetime
    @classmethod
    def from_info(cls, info: LockInfo | None) -> "LockInfoOut | None"
class ForceTakeIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
def lock_error_to_api(exc: LockError) -> ApiError
    # ItemNotFound -> 404 item_not_found
    # LockConflict -> 409 lock_conflict, details=[{"owner_name": ..., "acquired_at": iso}]
    # ItemBusy -> 409 item_busy ; LockNotHeld -> 409 lock_not_held
    # LockForbidden -> 403 forbidden (details [{"permission": "items:work"}]) ; LockReasonRequired -> 422 lock_reason_required
```

### HTTP contract (s20 and s31 consume it)

Every error uses s01's shape `{"error": {code, message, request_id, details}}`.

| Method and path | Permission | Success | Errors |
|---|---|---|---|
| `GET /items/{id}/lock` | items:read | 200 `LockInfoOut \| null` | 404 `item_not_found` |
| `POST /items/{id}/lock` | items:work | 200 `LockInfoOut` | 404, 409 `lock_conflict` (details `[{owner_name, acquired_at}]`), 409 `item_busy` |
| `POST /items/{id}/lock/renew` | items:work | 200 `LockInfoOut` | 404, 409 `lock_not_held`, 409 `item_busy` |
| `DELETE /items/{id}/lock` | items:work | 204 | 404, 409 `lock_not_held` |
| `POST /items/{id}/lock/force` body `ForceTakeIn` | items:work | 200 `LockInfoOut` | 404, 409 `item_busy`, 422 (blank reason: framework `validation_error`) |

- The router opens `async with uow_factory() as uow`, calls the service, commits, and maps `LockError` with `lock_error_to_api`.
- `get_lock_service(runtime: RuntimeConfigDep) -> LockService` is a module-level dependency that tests override.

## Migrations

None. The columns `LOCK_OWNER`, `LOCK_OWNER_NAME`, `LOCK_ACQUIRED_AT` and `LOCK_EXPIRES_AT` and the index `IX_WORK_ITEM_LOCK_OWNER` come from s02's `0001_base`. Expected Alembic head: unchanged.

## TEST PLAN (written and run in step 5 only)

Unit tests run on aiosqlite (s02 fixtures `uow`, `uow_factory`), with `FrozenClock`, s04 `make_principal` and s28 `make_runtime_config({"locks.lease_minutes": 30})`.

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/unit/services/test_locking.py::test_acquire_returns_lock_info_with_lease_from_config` (lease 30 → `expires_at = now+30m`; override 5 → +5m) |
| 1 | `…::test_renew_extends_expiry_keeps_acquired_at` |
| 1 | `…::test_release_clears_all_lock_columns` |
| 1 | `…::test_force_take_returns_new_owner_info` |
| 1 | `…::test_is_locked_for_automation_live_vs_expired_vs_none` (boundary `expires_at == now` → free) |
| 1 | `…::test_assert_held_by_owner_passes_other_or_expired_raises` |
| 2 | `…::test_acquire_conflict_when_other_holds_live_lock` (`LockConflict.owner_name/acquired_at`) |
| 2 | `…::test_acquire_item_busy_when_in_progress_with_live_claim` |
| 2 | `…::test_acquire_allowed_when_in_progress_claim_expired` |
| 2 | `…::test_acquire_after_others_lock_expired_succeeds` |
| 2 | `…::test_acquire_own_live_lock_renews` (same `acquired_at`, later `expires_at`, no history row) |
| 2 | `…::test_renew_by_non_owner_raises_lock_not_held` |
| 2 | `…::test_release_by_non_owner_raises_lock_not_held` |
| 2 | `…::test_release_without_lock_is_noop` |
| 2 | `…::test_release_redrives_pending_item_once` (one outbox row with `redrive=True`, none with `redrive=False`, none when not PENDING) |
| 2 | `…::test_acquire_refuses_system_principal_and_missing_permission` |
| 2 | `…::test_missing_item_raises_item_not_found` |
| 3 | `…::test_every_lock_write_bumps_updated_at` (parametrized acquire, renew, release, force_take) |
| 3 | `…::test_history_rows_for_acquire_renew_after_expiry_release_force_take` (ACTION=LOCK, actor USER/subject/name, payload `event`) |
| 3 | `…::test_plain_renew_writes_no_history` |
| 3 | `…::test_force_take_records_previous_owner_and_reason` |
| 3 | `…::test_force_take_blank_reason_raises` |
| 3 | `…::test_force_take_requires_items_work` (VIEWER principal → `LockForbidden`) |
| 3 | `…::test_service_never_commits` (a second UoW doesn't see the lock) |
| 3 | `api/tests/unit/test_layering.py::test_only_lock_repository_assigns_lock_columns` (ast over `cashapp/`: no `lock_owner`/`lock_owner_name`/`lock_acquired_at`/`lock_expires_at` assignment outside `data/repositories/locks.py`) |
| 3 | `api/tests/unit/services/test_actor.py::test_actor_fields_user_and_system` |
| 4 | `api/tests/api/test_locks_router.py::test_post_lock_200_returns_lock_info` |
| 4 | `…::test_post_lock_409_lock_conflict_shape` (exact `code` and `details[0]` keys) |
| 4 | `…::test_post_lock_409_item_busy` |
| 4 | `…::test_post_lock_requires_items_work_403` |
| 4 | `…::test_renew_200_and_409_lock_not_held` |
| 4 | `…::test_delete_lock_204_and_409_for_non_owner` |
| 4 | `…::test_force_200_and_422_blank_reason` |
| 4 | `…::test_get_lock_returns_null_when_free_and_info_when_live` (items:read VIEWER allowed) |
| 4 | `…::test_unknown_item_404_item_not_found` |
| 4 | `…::test_lock_routes_in_openapi` (5 operations, `LockInfoOut` and `ForceTakeIn` schemas present) |
| 5 | `api/tests/integration/test_locks_pipeline.py::test_runner_skips_locked_item_then_processes_after_expiry` (a test `StageRunner` at CLASSIFY; lock via service; `run_stage_once` → no state change and no history row besides LOCK; `FrozenClock.advance(minutes=31)`; same event → processed, stage advanced) |
| 5 | `…::test_runner_processes_after_release` |
| 5 | `api/tests/unit/services/test_locking.py::test_python_rule_matches_claim_sql` (parametrized live, expired, none: `is_locked_for_automation` equals the inverse of `WorkItemRepository.claim` returning a row) |
| 6 | `…::test_lock_info_for_live_only` (none → None; expired → None; live → LockInfo) |
| 6 | `api/tests/unit/api/test_lock_schemas.py::test_lock_info_out_from_info_none_and_value` |
| 6 | `…::test_lock_error_to_api_mapping` (parametrized over every `LockError` subclass) |

s18 asserts its own lock-respecting behaviour (story AC5).

Gates for the coder: `uv run ruff check . && uv run ruff format --check .` and `uv run pyright` only.

## Assumptions and deviations

- **`actor_fields` lives here.** s02's plan says "s04 adds a helper that turns a Principal into actor fields", but s04's pinned interfaces don't contain one. This story adds `cashapp/services/actor.py` so s18, s20 and s38 reuse it. If s04 merges an equivalent first, the merger deletes this file and re-points the import (one copy only).
- `acquire` on your own live lock renews silently (no history row), which avoids timeline noise from the UI's renew cadence. Plain `renew` writes no row either. Only renew-after-expiry does (AC3).
- `release` without any lock is an idempotent no-op returning 204. Release by a non-owner is 409 `lock_not_held` (AC2).
- An owner may release their own *expired* lock; it just clears the columns.
- Every route requires `items:work`, force-take included (AC3 names that permission). There's no separate supervisor permission, so any operator can force-take with a reason. Recorded for Jonathan.
- `LockService` accepts either `RuntimeConfig` (API) or `ConfigSnapshot` (workers), so neither path needs an adapter.
- The UoW dependency is s04's `UowFactoryDep` from `cashapp/api/deps.py`. If the merger consolidates it with s28's `config_deps`, only the import changes.
- Locking is allowed in every state, terminal ones included (needed by s38). The UI decides when to offer it.
- Blank `reason` is rejected by Pydantic (422 `validation_error`) at the API, and by `LockReasonRequired` in the service for non-HTTP callers.

## Risks

- **A lock taken while the item is PENDING with its event already in flight:** the runner's claim skips it and commits the offset, so the event is gone. After release or expiry, nothing re-drives the item.
  - On requeue, s18 emits a fresh `StageEvent` itself.
  - On a plain *release*, `release(..., redrive=True)` (the default) emits a `StageEvent` for the item's current stage through s03's `emit`, in the same transaction, when `state == PENDING`. That adds a dependency on `cashapp.pipeline.events.emit` (s03, same wave). s18's requeue passes `redrive=False` so the event isn't emitted twice. Test: `test_locking.py::test_release_redrives_pending_item_once`.
  - On *expiry* with no human action, s03's startup crash-recovery sweep is the only re-driver. **Flagged for Jonathan**: a periodic re-drive would be a third poller.
- `SELECT … FOR UPDATE` without a wait timeout: a long-held runner row lock would block the HTTP request. s03's claim transaction is short (claim, then commit before `process`), so the risk is low. **VERIFY** on ATP if s03 keeps the row locked during `process`.
- aiosqlite ignores `FOR UPDATE`, so the concurrent-dequeue race is only covered by the `version_id_col` path in unit tests. An `atp`-marked race test is optional, when DEV credentials exist.
- `lock` is an Oracle reserved word, but no column uses it (columns are `LOCK_*`, and `HistoryAction.LOCK` is a value), so there's no quoting issue.
