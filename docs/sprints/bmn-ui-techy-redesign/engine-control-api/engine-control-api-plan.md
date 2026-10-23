# Plan: engine-control-api

Story: [story.md](story.md). Deps: chat-agent-tool-registry (same wave, pinned interface only). Skills applied: python-web-app:building-python-web-apps (routes -> services -> repositories, logic in services, no state-changing GET), python-llm-features:building-llm-backed-features (tool descriptions are prompt surface: one constants module; previews never over-claim), nextjs.md for the one web edit (rules TS-1, TS-5, TS-10, TS-12, TS-19, SSE pass-through per non-negotiable 12, TEST-* for the tester).

## 1 Approach

research.md a10, extending a1 (shell page over existing SSE) and a3 (audited write path: permission, reason, `expected_version`, Principal, history):
- **One station catalogue** `domain/engine.py` derived from `Stage` (`domain/stages.py`) + reader slots + the await-receipt consumer, each station mapped to the consumer it gates (story AC4).
- **Visibility on request only:** `EngineService.status()` reads `BusHealth.snapshot()` (lag, through a read-only API-side `EventBus`), DB counts (in-flight = IN_PROGRESS claims, unreplayed dead letters), flow throughput (`flow_query._throughput_and_dwell`, last 5 min), poller heartbeats and config versions. A 5 s single-flight cache per process (pattern of `FlowSummaryCache`), never a background task (AC9).
- **Pause/drain** = DB runtime config keys read through `RuntimeConfig` by a `PauseGate` that `StageConsumer.run`, `ReceiptArrivedConsumer.run` and the intake poller's cycle consult before taking the next delivery/cycle; deliveries stay uncommitted on the bus (mirrors `services/backlog/service.py` pause).
- **Throttle** = `ConfigWriter.set` on `concurrency.per_stage` / `concurrency.apply_per_receipt` (already read live by `StageLimiter`, `StageConsumer`, `ReceiptApplyGate`).
- **DLQ replay** = DB-backed: dead letters are the outbox rows on `*.dlq` topics (the runner emits them through the outbox, `pipeline/runner.py:484`); replay reuses `LockService` + `RequeueService` and emits the main-topic event through the outbox. Deviations recorded under Assumptions.

## 2 Files

API (`api/src/cashapp/`):
| File | Change | Purpose |
|---|---|---|
| `domain/principal.py` | change (append-only) | `Permission.ENGINE_CONTROL = "engine:control"`; ADMIN gets it via `frozenset(Permission)`; remove it from `SYSTEM_PRINCIPAL` (pipeline never controls the engine) |
| `domain/engine.py` | new | `Station` StrEnum (12 values), `STATIONS` tuple (ordered), `StationSpec{station, consumer: ConsumerRef, reader_slot: ReaderSlot|None}`, `StationState` StrEnum (RUNNING, PAUSED, DRAINING, DRAINED), `EngineAction` StrEnum (PAUSE, RESUME, DRAIN, THROTTLE, REPLAY), `ENGINE_CONFIG_KEYS`, `PAUSE_RECHECK_SECONDS = 1.0` |
| `domain/config_keys.py` | change (append-only `engine.*` block + register in `_ALL_KEYS`) | `engine.paused_stations: list[Station]` default `[]`; `engine.draining_stations: list[Station]` default `[]`; `engine.status_cache_seconds: int` default 5 (>0); `engine.stream_tick_seconds: int` default 2 (>0); `engine.audit_page_size: int` default 50. Pause keys admin_only_write. |
| `services/config.py` | change (small) | `ConfigWriter.set(..., permission: Permission = Permission.CONFIG_WRITE)` keyword so engine writes require ENGINE_CONTROL instead of CONFIG_WRITE; add `concurrency_bounds` validation hook is NOT here (bounds checked in EngineService) |
| `data/models/engine.py` | new | `EngineAudit` (`ENGINE_AUDIT`), `EngineDlqReplay` (`ENGINE_DLQ_REPLAY`) |
| `data/repositories/engine.py` | new | `EngineAuditRepository(BaseRepository[EngineAudit])`: `page(offset, limit)`; `DeadLetterRepository(BaseRepository[OutboxMessage])`: `unreplayed(stage_topics, offset, limit) -> Page[DeadLetterRow]`, `counts_by_topic(dlq_topics) -> dict[str,int]`, `by_event_ids(ids) -> list[OutboxMessage]` (JSON `payload.event_id` lookup); `EngineDlqReplayRepository`: `replayed_ids(ids)`, `add`; `InFlightRepository`: `in_progress_by_stage() -> dict[Stage,int]`, `extract_pending_by_slot() -> dict[ReaderSlot,int]`, `awaiting_count() -> int` |
| `services/engine/__init__.py` | new | exports |
| `services/engine/service.py` | new | `EngineService` (signatures in §7), `EngineConflict`, `EngineReasonRequired`, `EngineForbidden`, `ThrottleOutOfBounds`, `UnknownStation`; `StatusCache` single-flight TTL cache |
| `services/engine/pause_gate.py` | new | `PauseGate(config: RuntimeConfig)`: `is_paused(consumer: ConsumerRef) -> bool`, `wait_while_paused(consumer, stop: asyncio.Event) -> None` (re-reads the cached RuntimeConfig every `PAUSE_RECHECK_SECONDS`; returns early on stop) |
| `services/engine/text.py` | new | load-bearing strings shared by router docs, tool descriptions and previews ("in-flight work finishes; new deliveries stay uncommitted on the bus, nothing is lost"), skip reasons |
| `pipeline/runner.py` | change | `StageConsumer.run`: `await gate.wait_while_paused(ConsumerRef.stage(runner.stage), stop)` before `next_or_stop`; gate from `RunnerDeps` (new optional field `pause_gate`, built from container config in `from_container`) |
| `stations/receipt_arrived/consumer.py` | change | same gate check before `next_or_stop` (station `await_receipt`) |
| `pollers/intake/poller.py` | change | at cycle start: if station `intake` paused, skip the fetch for this cycle (heartbeat hooks still run, status "paused"); no new loop |
| `api/bus_deps.py` | new | `get_event_bus()` lazy process singleton via `build_event_bus(settings)` (API only reads lag/depth; never publishes), `get_bus_health()`, `EventBusDep`, `BusHealthDep` |
| `api/engine_deps.py` | new | `get_engine_service()` -> `EngineServiceDep`; `engine_api_error(exc) -> ApiError` (409 conflict, 422 reason/bounds, 403, 404 unknown station) |
| `api/schemas/engine.py` | new | Pydantic v2 contracts in §7 |
| `api/routers/engine.py` | new (auto-discovered) | 9 routes in §7; SSE via `sse_starlette.EventSourceResponse(ping=15)` with `X-Accel-Buffering: no` |
| `services/chat/tools/engine.py` | new (discovered by registry) | `TOOLS: list[ToolSpec]` = engine.status, engine.pause, engine.resume, engine.drain, engine.set_throttle, engine.replay_dead_letters |
| `alembic/versions/ui48_engine_control.py` | new | one revision (§4) |

Web (generated / one-line):
| File | Change | Purpose |
|---|---|---|
| `web/lib/api/openapi.json`, `web/lib/api/schema.d.ts` | regenerated (`npm run api:sync`) | permission mirror (`engine:control` in `MeResponse.permissions` enum) + engine schemas |
| `web/lib/api/stream-paths.ts` | change | add `"/engine/stream"` to `STREAM_PATHS` so the existing `app/api/stream/[...path]` proxy forwards it (shell footer + Engine screen consume it) |

17 API files + 3 web files = 20 files.

## 3 Test plan (written and run only in step 5)

All API tests under `api/tests/`, pytest + pytest-asyncio, in-memory bus and SQLite-or-ATP support from `tests/support/` (`atp` marker only where noted).

| AC | Test (path::name) | Type |
|---|---|---|
| 1 | `tests/test_engine_permissions.py::test_engine_control_value` | unit |
| 1 | `tests/test_engine_permissions.py::test_admin_has_engine_control_operator_and_viewer_do_not` | unit |
| 1 | `tests/test_engine_permissions.py::test_system_principal_lacks_engine_control` | unit |
| 1 | `tests/test_engine_permissions.py::test_openapi_me_permissions_lists_engine_control` (reads `web/lib/api/openapi.json`; fails when not regenerated) | unit |
| 2 | `tests/test_engine_service.py::test_status_lists_every_station_with_lag_dlq_inflight_limit` | unit |
| 2 | `tests/test_engine_service.py::test_status_totals_pollers_region_group_version` | unit |
| 2 | `tests/test_engine_service.py::test_status_unknown_lag_marks_bus_unhealthy` (lag -1 -> bus_healthy false, lag null) | unit |
| 2 | `tests/test_engine_service.py::test_throughput_is_last_five_minutes_per_station` | unit |
| 2 | `tests/test_engine_service.py::test_drain_reports_draining_then_drained_when_inflight_zero` | unit |
| 2 | `tests/test_engine_service.py::test_resume_clears_pause_and_drain` | unit |
| 2 | `tests/test_engine_service.py::test_set_throttle_writes_both_keys_through_config_writer` | unit |
| 2 | `tests/test_engine_service.py::test_set_throttle_rejects_out_of_bounds` (0, 33; 0, 9) | unit |
| 2 | `tests/test_engine_service.py::test_list_dead_letters_filters_by_station_and_pages` | unit |
| 2 | `tests/test_engine_service.py::test_replay_enqueues_main_topic_event_and_ledger_in_one_transaction` | unit |
| 2 | `tests/test_engine_service.py::test_replay_rolls_back_ledger_when_enqueue_fails` | unit |
| 2 | `tests/test_engine_service.py::test_audit_pages_newest_first` | unit |
| 3 | `tests/test_engine_pause_gate.py::test_paused_runner_consumes_nothing_and_commits_no_offset` | unit |
| 3 | `tests/test_engine_pause_gate.py::test_resume_continues_from_uncommitted_offset` | unit |
| 3 | `tests/test_engine_pause_gate.py::test_inflight_work_finishes_after_pause` | unit |
| 3 | `tests/test_engine_pause_gate.py::test_paused_await_receipt_leaves_receipt_events_uncommitted` | unit |
| 3 | `tests/test_engine_pause_gate.py::test_paused_intake_cycle_fetches_nothing_but_beats` | unit |
| 3 | `tests/test_engine_pause_gate.py::test_reader_pause_holds_extract_consumer` | unit |
| 4 | `tests/test_engine_stations.py::test_twelve_stations_in_design_order` | unit |
| 4 | `tests/test_engine_stations.py::test_every_consumed_stage_maps_to_a_station` (no `CONSUMED_STAGES` member left ungated, FAST_PATH included) | unit |
| 4 | `tests/test_engine_stations.py::test_status_station_names_come_from_catalogue` | unit |
| 5 | `tests/test_engine_audit.py::test_every_action_writes_one_audit_row_with_actor_before_after_reason_version` (parametrised pause/resume/drain/throttle/replay) | unit |
| 5 | `tests/test_engine_audit.py::test_audit_and_state_change_roll_back_together` | unit |
| 5 | `tests/test_engine_audit.py::test_stale_expected_version_conflicts_and_writes_nothing` | unit |
| 5 | `tests/test_engine_audit.py::test_blank_reason_refused` | unit |
| 5 | `tests/test_engine_audit.py::test_concurrency_change_via_config_api_bumps_engine_version` | unit |
| 5 | `tests/test_engine_migration.py::test_engine_tables_round_trip` | unit (`atp` marker) |
| 6 | `tests/test_engine_router.py::test_get_status_shape_matches_shell_contract` | api |
| 6 | `tests/test_engine_router.py::test_reads_need_reports_read` (viewer 200, no-perm 403 in the one error shape) | api |
| 6 | `tests/test_engine_router.py::test_mutations_need_engine_control` (operator 403 on all five) | api |
| 6 | `tests/test_engine_router.py::test_pause_resume_drain_routes` | api |
| 6 | `tests/test_engine_router.py::test_pause_conflict_returns_409_error_shape` | api |
| 6 | `tests/test_engine_router.py::test_unknown_station_404` | api |
| 6 | `tests/test_engine_router.py::test_put_throttle_bounds_422` | api |
| 6 | `tests/test_engine_router.py::test_dead_letters_list_and_replay_result_shape` | api |
| 6 | `tests/test_engine_router.py::test_audit_route_pages` | api |
| 6 | `tests/test_engine_router.py::test_stream_emits_status_then_on_change_and_heartbeat` (fake clock; 15 s ping; `X-Accel-Buffering: no`) | api |
| 6 | `tests/test_engine_router.py::test_openapi_has_engine_routes` | api |
| 7 | `tests/test_engine_replay.py::test_replay_skips_item_locked_by_person` | unit |
| 7 | `tests/test_engine_replay.py::test_replay_skips_done_item` | unit |
| 7 | `tests/test_engine_replay.py::test_replay_twice_skips_already_replayed` | unit |
| 7 | `tests/test_engine_replay.py::test_replay_skips_item_moved_past_dead_stage` | unit |
| 7 | `tests/test_engine_replay.py::test_replayed_item_reprocessed_once_by_runner` | unit |
| 7 | `tests/test_engine_replay.py::test_replay_writes_item_history_with_actor` | unit |
| 8 | `tests/test_engine_tools.py::test_engine_tools_registered_in_group_engine` | unit |
| 8 | `tests/test_engine_tools.py::test_mutating_tools_confirm_required_and_engine_control` | unit |
| 8 | `tests/test_engine_tools.py::test_previews_show_before_after_and_inflight` | unit |
| 8 | `tests/test_engine_tools.py::test_tool_and_router_produce_identical_engine_audit` | unit |
| 8 | `tests/test_engine_tools.py::test_operator_offered_only_engine_status` | unit |
| 9 | `tests/test_engine_no_poller.py::test_api_startup_starts_no_background_task` (task set before/after lifespan) | unit |
| 9 | `tests/test_engine_no_poller.py::test_worker_host_roles_unchanged_by_engine` (role names equal the pre-story set; no new RoleSpec) | unit |
| 9 | `tests/test_engine_no_poller.py::test_status_cache_single_flight_no_timer` | unit |

Browser: none owned (no design screen). The Engine and Shell boards' Playwright tests belong to engine-control-panel-ui and glass-theme-shell; their mock API uses the §7 shapes.

57 tests.

## 4 Data

Models (`data/models/engine.py`, auto-imported by `alembic/env.py`):
- `ENGINE_AUDIT`: `ID` identity PK; `AT` UtcDateTime not null; `ACTOR_ID` VARCHAR2(255) not null; `ACTOR_NAME` VARCHAR2(255) not null; `ACTOR_ROLE` VARCHAR2(64) not null (highest role, e.g. "ADMIN"); `ACTION` VARCHAR2(20) not null (`EngineAction`); `STATIONS` JSON not null (list); `BEFORE_STATE` JSON; `AFTER_STATE` JSON; `REASON` VARCHAR2(1000) not null; `CONFIG_VERSION` NUMBER not null (engine version after the action); `SOURCE` VARCHAR2(10) not null ("api"|"chat"). Index `IX_ENGINE_AUDIT_AT` (AT).
- `ENGINE_DLQ_REPLAY`: `ID` identity PK; `EVENT_ID` VARCHAR2(36) not null, unique `UQ_ENGINE_DLQ_REPLAY_EVENT`; `OUTBOX_ID` NUMBER not null; `WORK_ITEM_ID` NUMBER; `STAGE` VARCHAR2(32) not null; `REPLAYED_AT` UtcDateTime not null; `AUDIT_ID` NUMBER not null (FK ENGINE_AUDIT.ID). Ledger that makes replay idempotent and that removes an event from the visible DLQ.
- Index on outbox for DLQ listing: `IX_OUTBOX_TOPIC_CREATED` (`TOPIC`, `CREATED_AT`), declared in `data/models/engine.py` (like `poller_heartbeat.py` does for others' tables) so `outbox.py` stays untouched.

Migration: ONE revision `api/alembic/versions/ui48_engine_control.py`, `revision = "ui48_engine_control"`. Written with `down_revision = "s45_retention_purge"` (current head); per split.md "Migrations" the merger re-points it in merge order: after chat-agent-tool-registry and db-stored-settings revisions, before html-progress-reports and matching-lab-replay-api. Creates the two tables and two indexes; downgrade drops them. Never run by the coder; db-sync applies to DEV ATP only.

## 5 Config

Env: none new. Reuses `CASHAPP_STREAMING__*` (consumer group, topic prefix/env) and the ObjectStorage region setting (`us-ashburn-1`) for `region`.

DB-stored settings keys (owned here, append-only `engine.*` block): `engine.paused_stations`, `engine.draining_stations`, `engine.status_cache_seconds`, `engine.stream_tick_seconds`, `engine.audit_page_size`. Written (not owned): `concurrency.per_stage` (engine bound 1..32 per entry), `concurrency.apply_per_receipt` (engine bound 1..8). Read: `intake.poll_interval_seconds`, `receipt_watcher.poll_interval_seconds` (poller health = last beat within 2 x interval).

## 6 Risks and coder gates

- **Kafka max.poll.interval while paused:** a consumer that stops fetching for > `max_poll_interval_ms` (aiokafka default 300 s) leaves the group; on resume it rejoins and receives the uncommitted offsets again. No loss (commits only after persist; runners idempotent), but expect a rebalance log line; the group is never renamed or reset. Recorded; not mitigated with `consumer.pause()` to keep `EventBus` unchanged.
- **Lag query cost:** `KafkaEventBus.consumer_lag` opens a consumer + admin client per topic; 12 topics per status read. Mitigated by the per-process 5 s single-flight cache shared by every SSE connection and GET.
- **API-side in-memory bus (env local):** the API process's in-memory bus is not the worker's; local lag reads 0. Acceptable for local.
- **Config version arithmetic:** engine `config_version` = sum of the versions of `engine.paused_stations`, `engine.draining_stations`, `concurrency.per_stage`, `concurrency.apply_per_receipt`; read under `get_for_update` of those rows so the check and the write are atomic. A `/config` write to a concurrency key also bumps it (correct 409).
- **Shared-file collisions:** `domain/principal.py`, `domain/config_keys.py` append-only blocks (split.md); `services/config.py` `ConfigWriter.set` gains one keyword (db-stored-settings may touch the same file: merger keeps both); `pipeline/runner.py` small insertion.
- **Malformed DLQ messages** (published directly, no item) are counted by the bus but not listable/replayable (no item to requeue); bus-side depth stays in the metrics exporter.
- Gates (coder, lint + type-check only): api `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`; web `cd web && npx eslint . && npx next typegen && npx tsc --noEmit` (after `npm ci` and `npm run api:sync`).

## 7 Interfaces provided (pinned; consumers build against these in the same wave)

Routes (router `api/routers/engine.py`, tag `engine`, `ERROR_RESPONSES`):
- `GET /engine/status` (REPORTS_READ) -> `EngineStatusOut`
- `GET /engine/stream` (REPORTS_READ) SSE: event `status` data `EngineStatusOut` JSON, sent on connect and whenever the serialized status (minus `generated_at`) changes, checked every `engine.stream_tick_seconds`; `: ping` comment every 15 s; header `X-Accel-Buffering: no`. Web path via existing proxy: `/api/stream/engine/stream`.
- `POST /engine/stations/{station}/pause|resume|drain` (ENGINE_CONTROL) body `EngineActionIn` -> `EngineActionOut`
- `PUT /engine/throttle` (ENGINE_CONTROL) body `ThrottleIn` -> `EngineActionOut`
- `GET /engine/dead-letters?station=&offset=0&limit=50` (REPORTS_READ) -> `DeadLetterPage`
- `POST /engine/dead-letters/replay` (ENGINE_CONTROL) body `ReplayIn` -> `ReplayOut`
- `GET /engine/audit?offset=0&limit=50` (REPORTS_READ) -> `EngineAuditPage`
Errors: one shape; 409 `conflict` details `[{expected_version, current_version}]`; 422 `validation_error` (blank reason, bounds); 403 `forbidden`; 404 `not_found` (unknown station).

Schemas (`api/schemas/engine.py`):
```python
StationName = Literal["intake","classify","extract.reader_a","extract.reader_b","adjudicate","validate",
                      "resolve_customer","match_receipt","await_receipt","match_lines","apply","write_back"]
class StationOut(BaseModel):
    name: StationName; state: Literal["RUNNING","PAUSED","DRAINING","DRAINED"]
    lag: int | None            # None = unknown
    throughput_per_min: float  # mean of the last 5 minutes
    dlq_depth: int; in_flight: int; limit: int; saturated: bool   # in_flight >= limit
    waiting: int | None        # await_receipt only: AWAITING_RECEIPT items
class PollerOut(BaseModel):
    name: Literal["intake-poller","receipt-watcher"]; interval_seconds: int
    last_beat_at: AwareDatetime | None; healthy: bool
class ThrottleOut(BaseModel):
    per_stage: dict[str, int]; apply_per_receipt: int
class EngineStatusOut(BaseModel):
    bus_healthy: bool; total_lag: int; dlq_total: int; pollers: list[PollerOut]
    region: str; consumer_group: str                      # shell footer subset (glass-theme-shell)
    stations: list[StationOut]; throttle: ThrottleOut; config_version: int
    counts: dict[Literal["running","paused","draining","drained"], int]; generated_at: AwareDatetime
class EngineActionIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000); expected_version: int = Field(ge=0)
class ThrottleIn(EngineActionIn):
    per_stage: int = Field(ge=1, le=32)        # written as concurrency.per_stage {"*": n}, other entries clamped to 1..32
    apply_per_receipt: int = Field(ge=1, le=8)
class EngineActionOut(BaseModel):
    status: EngineStatusOut; audit: EngineAuditOut
class DeadLetterOut(BaseModel):
    event_id: UUID; stage: StationName; item_id: int | None; error_code: str | None
    attempts: int; dead_since: AwareDatetime
class DeadLetterPage(BaseModel):
    items: list[DeadLetterOut]; total: int; offset: int; limit: int
class ReplayIn(BaseModel):
    event_ids: list[UUID] = Field(min_length=1, max_length=100); reason: str = Field(min_length=1, max_length=1000)
class ReplaySkipOut(BaseModel):
    event_id: UUID; why: Literal["locked","done","already_replayed","moved_on","not_found"]
class ReplayOut(BaseModel):
    replayed: int; skipped: list[ReplaySkipOut]; audit_id: int
class EngineAuditOut(BaseModel):
    id: int; at: AwareDatetime; actor_id: str; actor_name: str; actor_role: str
    action: Literal["PAUSE","RESUME","DRAIN","THROTTLE","REPLAY"]; stations: list[StationName]
    before: dict[str, Any] | None; after: dict[str, Any] | None; reason: str; config_version: int
    source: Literal["api","chat"]
class EngineAuditPage(BaseModel):
    items: list[EngineAuditOut]; total: int; offset: int; limit: int
```

Service (`services/engine/service.py`, plain arguments, no Request; each mutation opens one unit of work from `uow_factory` and commits it once, so the state change and its audit row share one transaction):
```python
class EngineService:
    def __init__(self, *, uow_factory: UowFactory, config: RuntimeConfig, bus_health: BusHealth,
                 settings: Settings, clock: Clock, lock_service: LockService, requeue: RequeueService) -> None
    async def status(self) -> EngineStatus                     # cached engine.status_cache_seconds
    async def pause(self, station: Station, reason: str, expected_version: int, principal: Principal, *, source="api") -> EngineActionResult
    async def resume(...same...) -> EngineActionResult
    async def drain(...same...) -> EngineActionResult
    async def set_throttle(self, per_stage: int, apply_per_receipt: int, reason: str, expected_version: int, principal: Principal, *, source="api") -> EngineActionResult
    async def list_dead_letters(self, station: Station | None, page: PageRequest) -> Page[DeadLetter]
    async def replay_dead_letters(self, event_ids: Sequence[UUID], reason: str, principal: Principal, *, source="api") -> ReplayResult
    async def audit(self, page: PageRequest) -> Page[EngineAuditEntry]
    async def preview(self, action: EngineAction, stations: Sequence[Station], **params) -> EnginePreview  # before/after/in_flight for chat
```
Each mutation: checks `principal.can(ENGINE_CONTROL)` (raises `EngineForbidden`), reason non-blank, row-locks the engine keys, compares `expected_version` (raises `EngineConflict(expected, current)`), writes through `ConfigWriter.set(..., permission=ENGINE_CONTROL)`, adds the `ENGINE_AUDIT` row, commits once, then `config.invalidate()`. Replay per event: skip-or-(lock via `LockService.acquire` -> `RequeueService.requeue(target_stage=dead stage, note=reason)` -> ledger row), one transaction, one audit row for the batch.

Pause gate (consumed by runners only, in this story): `PauseGate.wait_while_paused(consumer: ConsumerRef, stop: asyncio.Event) -> None`.

Chat tools (`services/chat/tools/engine.py`, `TOOLS: list[ToolSpec]`, group `ToolGroup.ENGINE`): `engine.status` (REPORTS_READ, read, output `EngineStatusOut`, result card `state_card`); `engine.pause|resume|drain` input `{station: StationName, reason: str}`; `engine.set_throttle` input `{per_stage: int, apply_per_receipt: int, reason: str}`; `engine.replay_dead_letters` input `{event_ids: list[UUID], reason: str}` (result card `replay_card`). Mutating ones: `mutating=True, confirm_required=True, permission=ENGINE_CONTROL`, `preview` returns registry `ConfirmPreview` filled from `EngineService.preview` (what, before, after, in-flight count, current `config_version` as expected version); handler calls the same `EngineService` method with `source="chat"`, using the version captured in the preview (stale -> 409 surfaced as tool error "engine.pause returned 409 … Nothing changed.").

Consumers:
- glass-theme-shell: `GET /engine/status` + SSE `status` event; uses only `bus_healthy, total_lag, dlq_total, pollers[{name, interval_seconds, last_beat_at, healthy}], region, consumer_group` (superset is compatible). Through `/api/stream/engine/stream`. plannable: true.
- engine-control-panel-ui: every route and schema above; `counts` for header pills, `saturated` for the warn meter, `config_version` for "expected version N", `EngineAuditOut` for who · when · why, `DeadLetterOut` for the DLQ table. plannable: true.
- assistant-chat-redesign: `GET /engine/status` (`bus_healthy`, `total_lag`, station `apply` row) for the live-context panel; tool names `engine.*` above for tool-activity rows. plannable: true.

## Assumptions

- **Replay emits through the outbox, not a direct `EventBus.publish`:** the repo rule is that nothing in business code publishes to the bus (`pipeline/events.py`); the main-topic event, the ledger row, item history and audit are one transaction and the relay publishes after commit. "Commit the DLQ offset only after publish" is realised as the `ENGINE_DLQ_REPLAY` ledger row committed atomically with the outbox row (nothing consumes the DLQ topic, so it has no consumer-group offset). The UI's DLQ list and `dlq_depth` are unreplayed DLQ outbox rows; raw bus depth remains in the metrics exporter.
- **Replay requeues the item** through `LockService.acquire` + `RequeueService.requeue` (dead-lettered items are ESCALATED, so a bare event would be skipped by the runner's claim); no separate path. Skip reasons: locked (another person's lock), done (terminal), already_replayed, moved_on (item no longer at the dead stage), not_found.
- **Second key `engine.draining_stations`** besides the story's `engine.paused_stations` set, so DRAINING/DRAINED survive restarts; draining stations are always also paused.
- **Station-to-consumer mapping:** extract.reader_a and extract.reader_b both gate the EXTRACT consumer (one runner runs both readers); pausing either holds EXTRACT and the other reader card shows RUNNING with in-flight from its own pending readings. FAST_PATH is gated with match_receipt. await_receipt gates the receipt-arrived consumer; intake gates the intake poller's cycle (the poller keeps beating).
- **In-flight** is the DB count of IN_PROGRESS claims per stage (cross-process), not the worker's in-memory `InFlightTrackingBus` registry, which the API cannot see; `limit` = `concurrency.for_stage`.
- **Throughput** uses the existing flow query (`services/flow_query.py`), not live-progress-dashboard's `MetricsService` (later wave; not a dep).
- `ThrottleIn.per_stage` is a single number written as the `"*"` fallback, matching the board's one slider; existing per-stage overrides are kept but clamped to 1..32.
- ENGINE_CONTROL is removed from `SYSTEM_PRINCIPAL`.
