# engine-control-api: Pause, drain, throttle and dead-letter replay for the processing engine

- Issue: #48 (addition: "control panel for the processing engine", scope item 1)
- breaking: false
- Design screen owned: none (API; the Engine screen is owned by engine-control-panel-ui)

## Story

As an admin, I want to see consumer lag, throughput, in-flight work and dead letters per station and to pause, resume, drain, throttle and replay through an audited API, so that I can control the flow of data through the engine without touching Kafka or restarting anything.

## Context

research.md a10, grounded in: `EventBus.consumer_lag(topic)` / `dlq_depth(stage)` (`pipeline/bus.py:54,58`, Kafka `pipeline/kafka.py`), `BusHealth.snapshot()` (`pipeline/health.py`), `InFlightTrackingBus`/`StageLimiter` (`workers/inflight.py`), topic kinds main/retry/dlq (`pipeline/events.py`), throttle keys `concurrency.per_stage`, `concurrency.apply_per_receipt` (`domain/config_keys.py:196,201`, read by `StageLimiter`, `ReceiptApplyGate`), batch pause pattern (`services/backlog/service.py`), `RequeueService` (`services/autofix/requeue.py`), poller heartbeats (`services/poller_heartbeat.py`). No scheduler, no third poller (non-negotiables 4, 5); never rename or reset a consumer group.

## Acceptance criteria

1. [unit] `Permission.ENGINE_CONTROL = "engine:control"` added (ADMIN only by default; ADMIN already gets every permission); web permission mirror regenerated.
2. [unit] `cashapp/services/engine/service.py` `EngineService`: `status() -> EngineStatus` (per station: name, state RUNNING|PAUSED|DRAINING|DRAINED, lag, throughput_per_min, dlq_depth, in_flight, limit; plus bus_healthy, total_lag, dlq_total, pollers, region, consumer_group, config_version); `pause(station, reason, expected_version, principal)`, `resume(...)`, `drain(...)` (pause then report DRAINED when in-flight reaches zero), `set_throttle(per_stage, apply_per_receipt, reason, expected_version, principal)` (through ConfigService, bounds 1..32 and 1..8), `list_dead_letters(station?, page)`, `replay_dead_letters(event_ids, reason, principal)` (re-publishes each chosen DLQ event to its stage's main topic through `EventBus.publish`, then commits the DLQ offset only after publish), `audit(page)`.
3. [unit] Pause state is runtime config in the DB (key `engine.paused_stations`, JSON set of station names, owned here), checked by the `StageRunner` (or `StageLimiter`) before it takes the next delivery; a paused station leaves deliveries uncommitted on the bus so nothing is lost, and in-flight work finishes. Test: a paused runner consumes nothing and commits no offset; resume continues from the uncommitted offset.
4. [unit] The 12 stations of design.md §3.3 (intake, classify, extract.reader_a, extract.reader_b, adjudicate, validate, resolve_customer, match_receipt, await_receipt, match_lines, apply, write_back) are listed from one source (`domain/stages.py` plus the reader roles), not a hard-coded UI list.
5. [unit] Every control action writes an engine audit record (new table `ENGINE_AUDIT`: at, actor id/name/role, action, station(s), before, after, reason, config_version) in the same transaction as the state change; optimistic `expected_version` check returns 409 on conflict; reason is required.
6. [api] New auto-discovered router `engine.py`: `GET /engine/status` (REPORTS_READ) -> `EngineStatusOut` (shape pinned in split.md, consumed by glass-theme-shell's footer); `GET /engine/stream` SSE (REPORTS_READ) emitting `status` on change and a 15 s heartbeat; `POST /engine/stations/{station}/pause|resume|drain {reason, expected_version}` (ENGINE_CONTROL); `PUT /engine/throttle {per_stage, apply_per_receipt, reason, expected_version}` (ENGINE_CONTROL); `GET /engine/dead-letters?station=&offset=&limit=` (REPORTS_READ) -> `[{event_id, stage, item_id, error_code, attempts, dead_since}]`; `POST /engine/dead-letters/replay {event_ids, reason}` (ENGINE_CONTROL) -> `{replayed, skipped: [{event_id, why}]}`; `GET /engine/audit` (REPORTS_READ). One error shape. OpenAPI regenerated.
7. [unit] Replay is idempotent (consumers already check stage and status); replaying an event whose item is locked by a person or already DONE is skipped with a reason, never re-run.
8. [unit] Chat tools in `cashapp/services/chat/tools/engine.py` (group ENGINE): `engine.status` (read), `engine.pause`, `engine.resume`, `engine.drain`, `engine.set_throttle`, `engine.replay_dead_letters` (mutating, confirm_required, ENGINE_CONTROL, previews showing before/after state and in-flight counts), all calling `EngineService`.
9. [unit] No new polling loop: status and lag are read on request and on the SSE connection; a test asserts no new background task is started at worker or API startup.

## Out of scope

- The Engine screen (engine-control-panel-ui). Topic/consumer-group admin (create, rename, reset): never.

## Deps

- chat-agent-tool-registry: `ToolSpec`, `ConfirmPreview`, `TOOLS` discovery, `ToolContext`. plannable: true.

## Assumptions

- "Drain" is per station: pause plus wait for in-flight zero; the state becomes DRAINED and stays paused until resumed.
- Engine reads use REPORTS_READ so operators get the read-only view the board shows; only ENGINE_CONTROL mutates.
- Throughput per station comes from the flow query/history over the last 5 minutes on each status read.
