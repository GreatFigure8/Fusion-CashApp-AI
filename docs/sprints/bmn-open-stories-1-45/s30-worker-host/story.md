# s30-worker-host: Worker host for stations, pollers and the outbox relay

- Issue: #30
- Wave: 2 (owns `cashapp/workers/`)
- breaking: false

## Story

As an operator, I want one entry point that starts any mix of station consumers, the two pollers and the outbox relay as long-running async processes that stop cleanly and report health, so that the line runs without a scheduler.

## Context

CLAUDE.md non-negotiables 4 and 5. Roles are discovered, never hand-listed, so each station story stays file-disjoint: any module `cashapp.stations.<name>`, `cashapp.pollers.<name>` or `cashapp.pipeline` exposing `ROLE: RoleSpec` (or `ROLES: list[RoleSpec]`) is a role.

## Acceptance criteria

1. [unit] `cashapp/workers/roles.py`: `RoleSpec{name: str, kind: Literal["consumer","poller","relay"], build: Callable[[Container], Runnable]}`, `Runnable` Protocol `{async run(stop: asyncio.Event) -> None; state() -> RoleState{name, status: starting|running|degraded|stopping|stopped, last_activity_at, detail}}`; `discover_roles() -> dict[str, RoleSpec]` scans those packages; a test asserts exactly two roles have kind `poller` once both pollers exist (guard against a third).
2. [unit] `cashapp/workers/container.py`: `Container` (lazy, one per process) providing `settings`, `uow_factory`, `config: RuntimeConfig`, `bus: EventBus`, `fusion: FusionClient`, `llm: LlmClients`, `object_store: ObjectStore`, `clock`, `metrics`, `failure_handler: FailureHandler`, `apply_gate: ReceiptApplyGate`; each built from its owner's factory by import path (`cashapp.integrations.fusion.factory:build_fusion_client`, `cashapp.integrations.llm.factory:build_llm_clients`, `cashapp.integrations.storage.factory:build_object_store`, `cashapp.services.autofix.engine:build_failure_handler` falling back to `EscalateAllHandler` when absent).
3. [unit] CLI `uv run python -m cashapp.workers run --roles classify,extract,relay|all [--health-port N]` (typer); unknown role → exit code 2 listing valid roles.
4. [integration] Graceful shutdown on SIGTERM/SIGINT: the stop event is set, consumers stop fetching, in-flight items finish within `worker.shutdown_grace_seconds` (default 30) or their claim is released (`STATE` back to PENDING, `CLAIM_EXPIRES_AT` null) in its own transaction; no half-written outcome (test with a slow fake stage).
5. [integration] At startup the host recovers expired claims: items `IN_PROGRESS` with `CLAIM_EXPIRES_AT < now` go back to PENDING with a history row and a re-emitted `StageEvent` (crash recovery, runs once per start, not a loop).
6. [api] A small health server (Starlette) on `settings.worker.health_port`: `GET /livez` 200 while the loop runs; `GET /readyz` 200 only when every role is `running`, else 503 with `{roles:[RoleState...]}`.
7. [unit] Per-stage concurrency is `config.concurrency().per_stage[stage]` (`"*"` fallback) enforced with a semaphore per consumer and re-read each event; `ReceiptApplyGate.slot(receipt_id)` async context manager caps concurrent Fusion applies per receipt at `concurrency.apply_per_receipt` (in-process; cross-process safety comes from s13's DB reservation).
8. [unit] After each processed event and on a 30 s health tick the host pushes `collect_queue_stats` and `BusHealth.snapshot()` to `Metrics` (internal housekeeping only; it reads no external system).

## Out of scope

Container images and deploy (s44); individual roles.

## Deps

- s03-pipeline-runtime — `StageRunner`, `EventBus`, `OutboxRelay`, `RetryForwarder`, `BusHealth`, `FailureHandler`, `EscalateAllHandler`. plannable.
- s29-observability — `configure_logging`, `Metrics`, `collect_queue_stats`. plannable.
- s28-runtime-config-service — `RuntimeConfig.concurrency()`. plannable.
- s27-settings-secrets-wiring — `Settings.worker{health_port, shutdown_grace_seconds}` (add `shutdown_grace_seconds`). plannable.
- s05-fusion-client — `cashapp.integrations.fusion.factory:build_fusion_client(settings) -> FusionClient`. plannable (same wave).
- s08-extraction-fan-out — `cashapp.integrations.llm.factory:build_llm_clients(settings, config) -> LlmClients` and the `LlmClients` type from `cashapp/integrations/llm/base.py`. plannable (same wave).
- s06-intake-poller — `cashapp.integrations.storage.factory:build_object_store(settings) -> ObjectStore` and `ObjectStore` from `cashapp/integrations/storage/base.py`. plannable (same wave).

Not a dep (later wave plugs in by import path, with a fallback until it merges): s18 provides `cashapp.services.autofix.engine:build_failure_handler(container) -> FailureHandler` (fallback `EscalateAllHandler`).

## Assumptions

- The 30 s health tick reads only the local DB and bus metadata; it is housekeeping, not a poller of an external source.
