# s03-pipeline-runtime: Pipeline runtime (StageRunner, EventBus on OCI Streaming, outbox relay, retry and DLQ)

- Issue: #3
- Wave: 2 (owns `cashapp/pipeline/`)
- breaking: false

## Story

As every station, I want one shared runtime where an event arrives, the item is claimed and processed, and the state change and next event are committed together, so that each station implements only its own step and redelivery is harmless.

## Context

CLAUDE.md *Business layer* and *The assembly line*; reference doc §7 (persist before publish, commit offsets after persisting, DLQ from day one). research.md: aiokafka on the OCI Streaming Kafka endpoint (SASL_SSL/PLAIN); hand-rolled outbox relay with SKIP LOCKED; an in-memory bus for tests and local runs. The database is the system of record; the bus carries only "item X is ready for stage Y".

## Acceptance criteria

1. [unit] `cashapp/pipeline/events.py`: `StageEvent` (Pydantic, `schema_version=1`): `{event_id: UUID, work_item_id: int, stage: Stage, attempt: int, not_before: datetime | None, trace_id: str, emitted_at: datetime}`; `topic_for(stage, kind: "main"|"retry"|"dlq") -> str` = `{settings.streaming.topic_prefix}.{env}.{stage}[.retry|.dlq]`. `emit(uow, event, priority: int = 100)` writes an `OUTBOX` row in the caller's transaction (the only way any code emits).
2. [unit] `cashapp/pipeline/bus.py`: `EventBus` Protocol — `publish(topic, key, payload: bytes, headers) -> None`, `subscribe(topics, group) -> AsyncIterator[Delivery]`, `Delivery.commit()`; `consumer_lag(topic) -> int`, `dlq_depth(stage) -> int`. Two implementations only: `KafkaEventBus` (aiokafka, SASL_SSL PLAIN, `enable_auto_commit=False`, consumer group `settings.streaming.consumer_group` used unchanged) and `InMemoryEventBus` (tests/local).
3. [unit] `cashapp/pipeline/runner.py`: abstract `StageRunner` with `stage: ClassVar[Stage]` and one abstract method `async def process(self, ctx: StageContext) -> StageOutcome`. `StageContext{uow, item: WorkItem, principal (SYSTEM_PRINCIPAL), config: ConfigSnapshot, clock, log}`. `StageOutcome` = `Advance(next_stage, note, payload=None)` | `Park(state=AWAITING_RECEIPT, note)` | `Finish(payment_status, note)` | `Archive(reason)`. Failures are raised as `StageError(code: ErrorCode, detail: dict, message: str)`.
4. [integration] `StageRunner.handle(delivery)` does, in order: parse event (malformed → DLQ topic + commit offset); claim the item in one transaction with `SELECT … FOR UPDATE SKIP LOCKED` only if `STAGE == event.stage`, `STATE == PENDING`, and no live lock (`LOCK_OWNER IS NULL OR LOCK_EXPIRES_AT <= now`), setting `STATE=IN_PROGRESS`, `CLAIM_EXPIRES_AT=now+claim_ttl`; otherwise log "skipped" and commit the offset (idempotency guard); call `process`; then in ONE transaction write the outcome (stage/state/payment status), a history row (`record_history`), and the next `StageEvent` via `emit`; then commit the offset. A redelivered event for an item already past that stage is a no-op (test).
5. [integration] On `StageError` the runner calls the injected `FailureHandler` Protocol `async def handle(uow, item, error: StageError, ctx) -> FailureDecision` where `FailureDecision` = `Retry(after: timedelta)` | `ParkAwaitingReceipt()` | `Escalate(summary: str | None)` | `Reroute(stage)` | `Resolved(outcome: StageOutcome)` (s18 implements it; the default `EscalateAllHandler` escalates). The runner applies the decision, increments `ATTEMPTS`, records `LAST_ERROR_CODE/DETAIL`, writes history, and for `Retry` emits to the stage's retry topic with `not_before`. Unexpected exceptions become `StageError(SYSTEM_DEAD_LETTER)` after `retries.max_attempts` and the event goes to the DLQ.
6. [integration] Retry consumer: `RetryForwarder` reads `<stage>.retry`, waits until `not_before` (bounded sleep, no polling of external systems), re-publishes to the main topic, commits.
7. [integration] `cashapp/pipeline/relay.py`: `OutboxRelay.run(stop)` claims unpublished rows `ORDER BY PRIORITY DESC, ID` with SKIP LOCKED in batches, publishes, marks `PUBLISHED_AT`; publish failure increments `ATTEMPTS` and keeps the row. It is woken by an in-process notify after each commit and otherwise idles on a bounded wait (crash recovery, not a third poller). A `PublishThrottle` Protocol `async def admit(row: OutboxRow) -> bool` hook (default allow-all) lets s35 rate-limit backlog rows.
8. [unit] `consumer_lag` and `dlq_depth` are exposed through `cashapp/pipeline/health.py: BusHealth.snapshot() -> dict[Stage, {lag, dlq_depth}]` for s29 metrics.
9. [unit] `cashapp/pipeline/roles.py` (owned here so stations never depend on the host): `RoleSpec{name: str, kind: Literal["consumer","poller","relay"], build: Callable[[Container], Runnable]}`, `Runnable` Protocol `{async run(stop: asyncio.Event) -> None; state() -> RoleState}`, `RoleState{name, status: starting|running|degraded|stopping|stopped, last_activity_at, detail}`, and the `Container` Protocol `{settings, uow_factory, config: RuntimeConfig, bus: EventBus, clock: Clock, failure_handler: FailureHandler, resolve(key: type[T]) -> T}` (service lookup for integration types such as `FusionClient`, `LlmClients`, `ObjectStore`, `ReceiptApplyGate`, so this module imports none of them). `cashapp/pipeline/__init__.py` exposes `ROLES` for the relay and retry forwarder; a `StageRunner` subclass becomes a role via `consumer_role(RunnerCls) -> RoleSpec`.

## Out of scope

Concrete stations; auto-fix handlers (s18); worker process host (s30); metrics export (s29).

## Deps

- s02-data-layer-foundation — `WORK_ITEM`/`OUTBOX`/`WORK_ITEM_HISTORY` columns, `Stage`, `ItemState`, `ErrorCode`, `record_history`, `UnitOfWork`, `select_for_update_skip_locked`. plannable.
- s27-settings-secrets-wiring — `Settings.streaming`. plannable.
- s28-runtime-config-service — `RuntimeConfig.snapshot() -> ConfigSnapshot`, `retries()`. plannable.
- s04-sign-in-authorization — `SYSTEM_PRINCIPAL`. plannable.
- s29-observability — `get_logger(__name__)`, `bind_item_context(work_item_id, stage, attempt, trace_id)`, `span(name, **attrs)`. plannable (same wave).

## Test-support files owned

`api/tests/support/pipeline.py`: `run_stage_once(runner, item_id, *, bus=InMemoryEventBus()) -> StageOutcome | FailureDecision` and `drain_outbox(uow) -> list[StageEvent]`.

## Assumptions

- Retry delay uses a retry topic with `not_before`, consumed by a forwarder (event-driven); no scheduler.
- Claim TTL default 10 minutes; expired claims are reset to PENDING by s30 at worker startup.
