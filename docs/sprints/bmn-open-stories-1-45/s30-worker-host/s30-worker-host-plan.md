# Plan: s30-worker-host

Issue #30. Wave 2 (owns `cashapp/workers/`). Python only; no web files, no migration.
One process entry point that discovers roles, builds one lazy container, runs the selected roles
as long-running async tasks, recovers expired claims once at start, serves `/livez` and `/readyz`,
pushes housekeeping metrics, and shuts down cleanly. No scheduler: the only timed loops here are
the 30 s health tick (local DB + bus metadata only, per the story's assumption) and the role
runnables themselves (the two pollers own their own intervals).

## Standards followed

- CLAUDE.md non-negotiables 4/5/6/7: no cron/batch; exactly two pollers (guarded by a test);
  layering (workers → services → data; no `sqlalchemy` import in `cashapp/workers/`, enforced by
  s02's AST test; the claim SQL lives in a repository); one `StageRunner`, one `EventBus`
  Protocol, one container.
- s04 AC6: nothing in `cashapp/workers` imports `cashapp.auth.tokens`; workers act as
  `SYSTEM_PRINCIPAL`.
- `python-web-app:building-python-web-apps`: same image, different command (`python -m
  cashapp.workers run …`, s44); health endpoint proves the loop is alive and roles are running;
  external SDK construction isolated behind owners' factories.
- `python-web-app:wiring-application-config`: settings read strictly (`settings.worker.health_port`,
  `settings.worker.shutdown_grace_seconds`, both already pinned by s27, so no s27 edit);
  business-tunable values (per-stage concurrency, apply-per-receipt) re-read from `RuntimeConfig`
  each use, no `or`-defaults (a configured `0` is rejected by s28's validator, not masked here).
- Fail fast: discovery and container import errors propagate; a role that crashes stops the
  process with exit code 1 so the platform restarts it (no silent half-alive worker).
- PII: host logs carry only ids, stage names, role names and counts (s29 redaction applies).
- pyright strict, ruff.

## Files to touch (all new; file-disjoint)

| Path | Purpose |
|---|---|
| `api/src/cashapp/workers/__main__.py` | `from cashapp.workers.cli import app; app()` |
| `api/src/cashapp/workers/cli.py` | typer `app`: `run`, `roles` (list) |
| `api/src/cashapp/workers/discovery.py` | `discover_roles`, `select_roles`, `RoleDiscoveryError`, `UnknownRoleError`, `ROLE_PACKAGES` |
| `api/src/cashapp/workers/container.py` | `WorkerContainer`, `UnknownServiceError`, `load_factory` |
| `api/src/cashapp/workers/host.py` | `WorkerHost` (start, recovery, signals, shutdown, crash policy) |
| `api/src/cashapp/workers/inflight.py` | `InFlightTrackingBus` (EventBus decorator), `StageLimiter`, `InFlight` |
| `api/src/cashapp/workers/health.py` | `build_health_app`, `HealthServer` (uvicorn without signal capture) |
| `api/src/cashapp/workers/telemetry.py` | `HostTelemetry` (event-coalesced push + 30 s health tick + hooks) |
| `api/src/cashapp/workers/hooks.py` | `HealthTickHook` Protocol, `HEALTH_TICK_HOOKS` |
| `api/src/cashapp/workers/apply_gate.py` | `ReceiptApplyGate` (no host imports, so s15 can import it cheaply) |
| `api/src/cashapp/data/repositories/claims.py` | `ClaimRepository(BaseRepository[WorkItem])`: `expired_claims`, `in_progress_for_update` |
| `api/src/cashapp/services/claims.py` | `ClaimService`: `recover_expired`, `release` (history + re-emit, one transaction each) |
| `api/tests/support/workers.py` | `make_worker_container`, `SlowStageRunner`, `fake_role`, `run_host_until` |
| `api/tests/workers/__init__.py` + test files below | tests (written/run at step 5 only) |

Not touched: `cashapp/workers/__init__.py` (s01, stays empty), `pyproject.toml`/`uv.lock` (typer,
uvicorn, starlette via fastapi, httpx already pinned by s01; no `[project.scripts]` entry is
needed because `python -m cashapp.workers` is the command s44 uses), `settings.py` (s27 already
has `WorkerSettings.shutdown_grace_seconds = 30`), `main.py`, any `pipeline/` file.

## Design

### Discovery (`discovery.py`)

- `ROLE_PACKAGES = ("cashapp.stations", "cashapp.pollers")` plus the module `cashapp.pipeline`.
- For each package: `pkgutil.iter_modules(pkg.__path__)` over **direct children** (module or
  sub-package), `importlib.import_module`, read `ROLE` (a `RoleSpec`) and/or `ROLES`
  (`list[RoleSpec]`). `cashapp.pipeline` itself is read for `ROLES` (relay + retry forwarder).
- Non-`RoleSpec` value → `RoleDiscoveryError`; duplicate name → `RoleDiscoveryError` naming both
  modules. Import errors propagate. Result sorted by name.
- `select_roles(available, spec: str) -> list[RoleSpec]`: `"all"` → every role; else
  comma-split, trimmed, deduped (order kept); unknown names → `UnknownRoleError(unknown, valid)`.

### Container (`container.py`)

Lazy, one per process (`functools.cached_property` per member; `resolve` caches per type).

| Member | Built from |
|---|---|
| `settings` | constructor arg (CLI passes `get_settings()`) |
| `uow_factory` | `make_uow_factory(create_engine(atp.url().render_as_string(hide_password=False), **kw))` where `kw = atp.engine_kwargs()` minus `pool_pre_ping` (s01's `create_engine` already sets it; passing it twice is a `TypeError`) |
| `config` | `build_runtime_config(self.uow_factory)` |
| `clock` | `SystemClock()` |
| `bus` | `InFlightTrackingBus(inner, limiter, on_processed)`; `inner` = s03 `InMemoryEventBus` when `settings.env == "local"`, else `KafkaEventBus` from `settings.streaming` (coder uses s03's pinned constructor) |
| `failure_handler` | `load_factory("cashapp.services.autofix.engine:build_failure_handler")(self)`; if **that module** is missing (`ModuleNotFoundError` with `.name` equal to it) → s03 `EscalateAllHandler()` + one warning. Any other import error propagates. |
| `resolve(FusionClient)` | `cashapp.integrations.fusion.factory:build_fusion_client(settings)` |
| `resolve(LlmClients)` | `cashapp.integrations.llm.factory:build_llm_clients(settings, config)` |
| `resolve(ObjectStore)` | `cashapp.integrations.storage.factory:build_object_store(settings)` |
| `resolve(Metrics)` | `cashapp.observability.metrics:build_metrics(settings)` (see assumptions) |
| `resolve(ReceiptApplyGate)` | `ReceiptApplyGate(self.config)` |
| `resolve(BusHealth)` | `BusHealth(self.bus)` (s03 constructor; coder adapts) |

Keys are matched by identity with the types imported **lazily inside `resolve`** via the same
import-path table (`_SERVICES: dict[str, str]` of `"module:Type" -> "module:factory"`), so
importing the container never imports an integration SDK. Unknown type → `UnknownServiceError`
listing registered keys. `overrides: Mapping[type, object]` in the constructor (tests, local)
take precedence over factories. `aclose()` disposes the engine and closes resolved services that
expose `aclose()`.

### In-flight tracking and per-stage concurrency (`inflight.py`)

The host cannot see inside s03's consumer loop, so it decorates the bus it hands to roles:

- `InFlightTrackingBus.subscribe(topics, group)` wraps the inner iterator. For each delivery on a
  **main** topic (not `.retry`/`.dlq`): parse the payload with `StageEvent.model_validate_json`;
  `await limiter.acquire(event.stage)` **before yielding** (so fetching blocks when the stage is at
  its cap); register `InFlight(work_item_id, stage, started_at)`; yield a wrapped `Delivery` whose
  `commit()` delegates, then releases the slot, unregisters, and calls `on_processed(stage)`.
  Unparseable payloads and retry/DLQ topics pass through untracked (s03 DLQs them; the forwarder's
  `not_before` sleep must never hold a stage slot).
- `publish`, `consumer_lag`, `dlq_depth` delegate unchanged. It is a decorator around one of s03's
  two implementations, not a third bus.
- `StageLimiter(config: RuntimeConfig)`: one counter + `asyncio.Condition` per stage; each
  `acquire(stage)` re-reads `(await config.concurrency()).for_stage(stage)` (s28: `per_stage`,
  `"*"` fallback) and waits while `in_use >= limit`, so a lowered limit takes effect on the next
  event and a raised one wakes waiters on the next release/notify.
- `inflight() -> list[InFlight]` snapshot for shutdown.

### Claim recovery and release (`services/claims.py`, `data/repositories/claims.py`)

```python
class ClaimRepository(BaseRepository[WorkItem]):
    async def expired_claims(self, *, now: datetime, limit: int) -> list[WorkItem]
        # STATE='IN_PROGRESS' AND CLAIM_EXPIRES_AT < :now ORDER BY ID ; FOR UPDATE SKIP LOCKED
    async def in_progress_for_update(self, item_id: int, *, stage: Stage) -> WorkItem | None
        # ID=:id AND STAGE=:stage AND STATE='IN_PROGRESS' ; FOR UPDATE (waits)

class ClaimService:
    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None
    async def recover_expired(self, *, batch_size: int = 100) -> int
        # loops batches until empty; per batch ONE transaction: state=PENDING, claim_expires_at=None,
        # record_history(STAGE_TRANSITION, IN_PROGRESS->PENDING, same stage,
        #   reasoning="claim expired; recovered at worker start"), emit(uow, StageEvent(new event_id,
        #   work_item_id, stage, attempt=item.attempts, not_before=None, new trace_id, emitted_at=now),
        #   priority=item.priority); commit. Returns the count. Runs once per start; not a loop over time.
    async def release(self, item_id: int, stage: Stage, *, reason: str) -> bool
        # own transaction; no-op (False) unless the row is still IN_PROGRESS at that stage;
        # same writes as recovery with reasoning=reason ("shutdown grace exceeded"); commit.
```

`emit` is s03's (`cashapp.pipeline.events.emit`); `record_history`/`HistoryEntry` are s02's.
Attempts are not incremented (no stage ran to completion).

### Host (`host.py`)

```
WorkerHost.run() -> int (exit code)
 1. configure: install stop handlers (SIGTERM, SIGINT)
 2. ClaimService.recover_expired()                       (AC5, once)
 3. start HealthServer (unless port 0) and HostTelemetry
 4. build each role: spec.build(container) -> Runnable; one task per role: runnable.run(stop)
 5. wait for: stop event | any role task finishing
      role task raised or returned while not stopping -> log error (role name, exception type),
      exit_code = 1, set stop
 6. shutdown: status "stopping"; await role tasks up to settings.worker.shutdown_grace_seconds
 7. cancel remaining tasks; await them (bounded 5 s)
 8. for each bus.inflight(): ClaimService.release(item, stage, reason="shutdown grace exceeded")
 9. stop telemetry, health server; container.aclose(); return exit_code
```

- Signals: `loop.add_signal_handler` on POSIX; on Windows (local dev) `signal.signal` +
  `loop.call_soon_threadsafe(stop.set)`. A second signal during shutdown skips the remaining grace
  (cancels immediately) but still runs step 8.
- "No half-written outcome": s03 writes the outcome, history and next event in one transaction, so a
  cancelled `handle` rolls back in its UoW; step 8 only touches rows still `IN_PROGRESS` at the
  event's stage, so a committed outcome is never overwritten.
- `role_states() -> list[RoleState]`: a role not yet built reports `starting`; afterwards its
  `Runnable.state()`; a dead task reports `stopped`.

### Health server (`health.py`)

`build_health_app(host: HealthSource) -> Starlette` where `HealthSource` Protocol
`{alive: bool; role_states() -> list[RoleState]}`:
- `GET /livez` → 200 `{"status":"ok"}` while `alive` (set when the loop starts, cleared after
  shutdown step 9); else 503 `{"status":"down"}`.
- `GET /readyz` → 200 `{"status":"ready","roles":[...]}` iff every role status is `running`; else
  503 `{"status":"not_ready","roles":[...]}`. Each role is RoleState serialised to JSON
  (`name, status, last_activity_at (ISO), detail`).
- `HealthServer(app, port)`: `uvicorn.Server` subclass whose `capture_signals` is a no-op context
  manager (and `install_signal_handlers` no-op for older uvicorn), so the host owns signals;
  `host="0.0.0.0"`, `log_config=None`, `access_log=False`; stopped via `should_exit = True`.

### Telemetry (`telemetry.py`) and hooks (`hooks.py`)

- `HostTelemetry(container, *, tick_seconds=30.0, min_push_interval=1.0)`.
  `notify_processed(stage)` (called from the bus wrapper's commit) sets a dirty flag; one task
  pushes `collect_queue_stats(uow)` → `Metrics.queue_depth(...)` per row and
  `BusHealth.snapshot()` → `Metrics.bus_health(...)` per stage, at most once per
  `min_push_interval` (coalesced, so a burst of events is one DB query, not one per event).
- Every `tick_seconds` (bounded `asyncio.wait_for(stop.wait(), tick)`): same push, then each hook
  in `HEALTH_TICK_HOOKS` with `await hook.on_tick(container, clock.now())`, each under its own
  `try` (logged, never fatal) and a 10 s timeout.
- `hooks.py`:
  ```python
  class HealthTickHook(Protocol):
      async def on_tick(self, container: Container, now: datetime) -> None: ...
  HEALTH_TICK_HOOKS: list[HealthTickHook] = []
  ```
  s42 adds its hook by appending an entry to this list literal (one-line edit in a later wave);
  hook modules must not import `cashapp.workers.host`.

### Apply gate (`apply_gate.py`)

`ReceiptApplyGate(config: RuntimeConfig)`; `slot(receipt_id: int) -> AbstractAsyncContextManager[None]`.
Per receipt: counter + `asyncio.Condition`; limit re-read from
`(await config.concurrency()).apply_per_receipt` on each acquire; the entry is deleted when its
counter returns to 0 with no waiters (no leak across thousands of receipts). Released on exception
and cancellation. In-process only; cross-process exclusivity is s13's DB reservation.

### CLI (`cli.py`)

```
uv run python -m cashapp.workers run --roles classify,extract,relay|all [--health-port N]
uv run python -m cashapp.workers roles          # prints "<name>\t<kind>" per discovered role
```
`run`: `settings = get_settings()`; `configure_logging(settings)`; `discover_roles()`;
`select_roles(...)` — on `UnknownRoleError` print `Unknown role(s): x. Valid roles: a, b, …` to
stderr and `raise typer.Exit(2)`; `--health-port` overrides `settings.worker.health_port` (0
disables the server); `asyncio.run(WorkerHost(...).run())`; exit with its code. Settings load
before discovery, so a config error fails with s27's message first.

## Interfaces provided (pinned)

```python
# cashapp/workers/discovery.py
ROLE_PACKAGES: Final[tuple[str, ...]] = ("cashapp.stations", "cashapp.pollers")
PIPELINE_MODULE: Final = "cashapp.pipeline"
class RoleDiscoveryError(Exception): ...
class UnknownRoleError(Exception): unknown: tuple[str, ...]; valid: tuple[str, ...]
def discover_roles(packages: Sequence[str] = ROLE_PACKAGES, *, include_pipeline: bool = True) -> dict[str, RoleSpec]
def select_roles(available: Mapping[str, RoleSpec], spec: str) -> list[RoleSpec]

# cashapp/workers/container.py   (satisfies s03's Container Protocol)
class UnknownServiceError(LookupError): ...
def load_factory(path: str) -> Callable[..., Any]          # "pkg.mod:attr"
class WorkerContainer:
    def __init__(self, settings: Settings, *, overrides: Mapping[type[Any], object] | None = None,
                 bus: EventBus | None = None, uow_factory: UowFactory | None = None,
                 config: RuntimeConfig | None = None, clock: Clock | None = None) -> None
    settings: Settings
    uow_factory: UowFactory          # cached_property
    config: RuntimeConfig            # cached_property
    bus: InFlightTrackingBus         # cached_property (EventBus)
    clock: Clock                     # cached_property
    failure_handler: FailureHandler  # cached_property
    def resolve(self, key: type[T]) -> T
    async def aclose(self) -> None

# cashapp/workers/inflight.py
@dataclass(frozen=True, slots=True)
class InFlight: work_item_id: int; stage: Stage; started_at: datetime
class StageLimiter:
    def __init__(self, config: RuntimeConfig) -> None
    async def acquire(self, stage: Stage) -> None
    def release(self, stage: Stage) -> None
    def in_use(self, stage: Stage) -> int
class InFlightTrackingBus:          # implements s03 EventBus
    def __init__(self, inner: EventBus, limiter: StageLimiter,
                 on_processed: Callable[[Stage], None] | None = None) -> None
    def inflight(self) -> list[InFlight]
    # publish / subscribe / consumer_lag / dlq_depth per s03's Protocol

# cashapp/workers/host.py
class WorkerHost:
    def __init__(self, container: WorkerContainer, roles: Sequence[RoleSpec], *,
                 health_port: int | None, install_signals: bool = True) -> None
    alive: bool
    def role_states(self) -> list[RoleState]
    def request_stop(self) -> None             # what the signal handlers call
    async def run(self) -> int                 # 0 clean stop, 1 role crashed

# cashapp/workers/health.py
class HealthSource(Protocol):
    @property
    def alive(self) -> bool: ...
    def role_states(self) -> list[RoleState]: ...
def build_health_app(source: HealthSource) -> Starlette
class HealthServer:
    def __init__(self, app: Starlette, port: int) -> None
    async def start(self) -> None ; async def stop(self) -> None
# HTTP: GET /livez -> 200 {"status":"ok"} | 503 {"status":"down"}
#       GET /readyz -> 200 {"status":"ready","roles":[RoleStateJson]} | 503 {"status":"not_ready","roles":[...]}
#       RoleStateJson = {"name": str, "status": "starting|running|degraded|stopping|stopped",
#                        "last_activity_at": str | null, "detail": str | null}

# cashapp/workers/hooks.py
class HealthTickHook(Protocol):
    async def on_tick(self, container: Container, now: datetime) -> None: ...
HEALTH_TICK_HOOKS: list[HealthTickHook]

# cashapp/workers/telemetry.py
HEALTH_TICK_SECONDS: Final = 30.0
class HostTelemetry:
    def __init__(self, container: WorkerContainer, *, tick_seconds: float = HEALTH_TICK_SECONDS,
                 min_push_interval: float = 1.0) -> None
    def notify_processed(self, stage: Stage) -> None
    async def push_once(self) -> None
    async def tick_once(self) -> None          # push_once + hooks
    async def run(self, stop: asyncio.Event) -> None

# cashapp/workers/apply_gate.py   (consumed by s15 via container.resolve(ReceiptApplyGate))
class ReceiptApplyGate:
    def __init__(self, config: RuntimeConfig) -> None
    def slot(self, receipt_id: int) -> AbstractAsyncContextManager[None]
    def active(self, receipt_id: int) -> int

# cashapp/services/claims.py ; cashapp/data/repositories/claims.py — signatures in Design above.
```

```python
# api/tests/support/workers.py
def make_worker_container(uow_factory: UowFactory, *, config_overrides: Mapping[str, Any] | None = None,
                          clock: Clock | None = None, bus: EventBus | None = None,
                          overrides: Mapping[type[Any], object] | None = None) -> WorkerContainer
    # make_settings() + InMemoryEventBus + make_runtime_config(config_overrides) + InMemoryMetrics
class SlowStageRunner(StageRunner):          # stage = Stage.CLASSIFY; process sleeps `delay` then Advance(VALIDATE)
    delay: float
def fake_role(name: str, kind: Literal["consumer","poller","relay"], *, status: str = "running",
              fail_after: float | None = None) -> RoleSpec
async def run_host_until(host: WorkerHost, predicate: Callable[[], bool], timeout: float = 5.0) -> None
```

## Migrations

None. `WORK_ITEM.STATE` / `CLAIM_EXPIRES_AT` exist from s02's `0001_base`. Expected head unchanged.

## TEST PLAN (written and run at step 5 only)

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `api/tests/workers/test_discovery.py::test_discovers_role_and_roles_from_packages` | tmp packages (via `sys.path` + monkeypatched `ROLE_PACKAGES`) exposing `ROLE` and `ROLES` → dict keyed by name; sub-packages and modules both scanned; non-role modules ignored |
| 1 | `…::test_duplicate_role_name_raises` | `RoleDiscoveryError` names both modules |
| 1 | `…::test_non_rolespec_value_raises` | `ROLE = "x"` → `RoleDiscoveryError` |
| 1 | `…::test_pipeline_roles_included` | `cashapp.pipeline.ROLES` (relay, retry forwarder) appear |
| 1 | `…::test_at_most_two_pollers_and_exactly_two_when_both_exist` | real `discover_roles()`: pollers ⊆ {`intake-poller`, `receipt-watcher`}, count ≤ 2; when both modules are importable, == 2 (guard against a third poller) |
| 1 | `…::test_select_roles_all_and_list` | `"all"` → all; `"classify, extract,classify"` → deduped in order |
| 2 | `api/tests/workers/test_container.py::test_members_are_lazy_and_cached` | no factory called at construction; second access returns the same object |
| 2 | `…::test_resolve_uses_owner_factories_by_import_path` | monkeypatched factory modules for fusion/llm/storage/metrics called once with `(settings)` / `(settings, config)`; `resolve` returns the cached instance |
| 2 | `…::test_resolve_receipt_apply_gate_and_unknown_type` | `ReceiptApplyGate` built from `config`; unregistered type → `UnknownServiceError` |
| 2 | `…::test_failure_handler_falls_back_when_autofix_absent` | autofix module missing → `EscalateAllHandler` + one warning; present → `build_failure_handler(container)` result |
| 2 | `…::test_failure_handler_import_error_inside_module_propagates` | autofix module raising `ImportError` of another name is not swallowed |
| 2 | `…::test_satisfies_container_protocol_and_overrides_win` | structural check against s03 `Container`; `overrides` beat factories |
| 2 | `…::test_engine_kwargs_do_not_duplicate_pool_pre_ping` | `create_engine` patched: called without `pool_pre_ping` in opts |
| 3 | `api/tests/workers/test_cli.py::test_unknown_role_exits_2_listing_valid_roles` | `CliRunner` with patched discovery → exit 2, stderr names the unknown and every valid role |
| 3 | `…::test_run_all_and_health_port_override` | patched `WorkerHost`: receives every role for `all`, `health_port` from flag, else `settings.worker.health_port` |
| 3 | `…::test_roles_command_lists_name_and_kind` | |
| 3 | `…::test_module_entrypoint` | `python -m cashapp.workers --help` subprocess exits 0 |
| 4 | `api/tests/workers/test_shutdown.py::test_stop_lets_inflight_item_finish_within_grace` (integration, sqlite + InMemoryEventBus) | `SlowStageRunner(delay=0.2)`, grace 2 s: after `request_stop`, item reaches VALIDATE/PENDING with one transition row; no release row; offset committed |
| 4 | `…::test_grace_exceeded_releases_claim_without_outcome` | `delay=10`, grace 0.2: item `STATE=PENDING`, `CLAIM_EXPIRES_AT is None`, stage still CLASSIFY, no Advance history, one release history row ("shutdown grace exceeded"), one re-emitted OUTBOX row; host returns 0 |
| 4 | `…::test_release_never_overwrites_committed_outcome` | `ClaimService.release` on an item already advanced → False, row unchanged |
| 4 | `…::test_consumers_stop_fetching_after_stop` | events published after `request_stop` are not claimed |
| 4 | `…::test_sigterm_sets_stop_event` (skip on win32) | `os.kill(os.getpid(), SIGTERM)` → host stops with code 0 |
| 4 | `…::test_signal_handler_fallback_on_windows_path` | patched `add_signal_handler` raising `NotImplementedError` → `signal.signal` path sets stop |
| 4 | `…::test_crashed_role_stops_host_with_exit_1` | `fake_role(fail_after=0.05)` → other roles stopped, `run()` returns 1 |
| 5 | `api/tests/workers/test_recovery.py::test_expired_claims_recovered_at_start` (integration) | two expired + one live claim: expired → PENDING, `CLAIM_EXPIRES_AT None`, history row each, StageEvent in OUTBOX with item stage and priority; live untouched; returns 2 |
| 5 | `…::test_recovery_runs_once_per_start` | host start calls `recover_expired` exactly once; an item expiring later is not touched while running |
| 5 | `…::test_recovery_batches_until_empty` | 250 items, `batch_size=100` → 3 transactions, all recovered |
| 5 | `…::test_recovery_skip_locked_on_atp` (`-m atp`) | concurrent recoveries on DEV ATP never double-recover an item |
| 6 | `api/tests/workers/test_health.py::test_livez_200_while_alive_503_after` | httpx `ASGITransport` |
| 6 | `…::test_readyz_200_only_when_all_running` | all running → 200 + roles; one `starting`/`degraded` → 503 `{status:"not_ready", roles:[...]}` with JSON-shaped RoleState |
| 6 | `…::test_health_server_binds_port_and_does_not_capture_signals` | real `HealthServer` on a free port: GET `/livez` 200; `signal.getsignal(SIGINT)` unchanged after start/stop |
| 7 | `api/tests/workers/test_concurrency.py::test_stage_limiter_caps_per_stage_with_star_fallback` | `per_stage={"CLASSIFY":2,"*":1}`: 3rd CLASSIFY acquire waits; EXTRACT capped at 1 |
| 7 | `…::test_limit_reread_each_event` | config changed 2→1 between events (ttl 0) → next acquire honours 1 |
| 7 | `…::test_tracking_bus_gates_main_topics_only` | retry/DLQ and malformed deliveries pass untracked; main delivery tracked until `commit()` |
| 7 | `api/tests/workers/test_apply_gate.py::test_slot_caps_concurrent_applies_per_receipt` | `apply_per_receipt=2`: 3 tasks on receipt 1 → max 2 concurrent; receipt 2 independent |
| 7 | `…::test_slot_released_on_exception_and_cancel_and_entry_cleaned` | counters back to 0; internal map empty |
| 8 | `api/tests/workers/test_telemetry.py::test_push_after_processed_events_is_coalesced` | 20 commits within 1 s → `InMemoryMetrics` gets queue_depth/bus_health from ≤ 2 pushes |
| 8 | `…::test_tick_pushes_stats_and_runs_hooks` | `tick_once` → `queue_depth` per `collect_queue_stats` row, `bus_health` per stage; each hook called with `(container, now)` |
| 8 | `…::test_failing_or_slow_hook_is_isolated` | raising hook logged; next hook still runs; tick returns |
| 8 | `…::test_tick_reads_no_external_system` | container with fusion/llm/storage factories that raise → tick succeeds (only DB + bus metadata touched) |
| all | `api/tests/workers/test_layering.py::test_workers_import_no_sqlalchemy_or_auth_tokens` | AST scan of `cashapp/workers/` (complements s02/s04 tests) |

## Risks

- **Role runnables' internal concurrency (s03).** The limiter caps in-flight deliveries; real
  parallelism needs s03's consumer to dispatch `handle` as tasks. If s03 processes serially the cap
  is still honoured (effective 1). Flagged to s03's coder.
- **`Delivery` shape.** The tracking bus needs `topic` and `payload` on s03's `Delivery`. Assumed;
  adapt the wrapper if s03 names them differently.
- **Releasing another process's claim** is impossible in step 8 only if this process claimed it; a
  redelivered event handled by another worker in the same instant could match `IN_PROGRESS` at that
  stage. Window is tiny (offset not committed ⇒ redelivery only after rebalance). A per-claim owner
  column would close it; out of scope, noted for s03.
- **uvicorn signal capture** differs across versions (`capture_signals` vs
  `install_signal_handlers`); both overridden, covered by a test.
- **Windows** has no `loop.add_signal_handler`; fallback path tested; production is Linux.
- **Lock expiry re-drive** (s40 risk): items released by expiry are only re-driven by this startup
  recovery when they were `IN_PROGRESS`; a periodic re-drive would be a third poller and is not added.

## Assumptions / deviations

- s29 exposes `build_metrics(settings) -> Metrics` in `cashapp/observability/metrics.py` (story
  names only `Metrics`); if s29 pins another constructor, only the `_SERVICES` entry changes.
- s03 exposes `InMemoryEventBus`, `KafkaEventBus`, `EscalateAllHandler`, `BusHealth(bus)`,
  `StageEvent`, `emit` and a `ROLES` list on `cashapp.pipeline` whose relay role is named `relay`.
- AC7's `config.concurrency().per_stage[stage]` is read as s28's
  `(await config.concurrency()).for_stage(stage)` (same `"*"` fallback).
- AC8 "after each processed event" is coalesced to at most one push per second, so a burst does not
  run one grouped query per event.
- Claim release at shutdown also re-emits a `StageEvent` (harmless under idempotent consumers), so an
  in-memory or rebalanced bus cannot strand a released item.
- `--health-port 0` disables the health server (local multi-process runs); production always sets a
  port.
- A crashed role ends the process with exit code 1 (platform restarts it) rather than restarting the
  role in-process.
- Claim SQL lives in a new repository `ClaimRepository` and the release/recovery rules in
  `services/claims.py`, keeping `cashapp/workers/` free of ORM code.
