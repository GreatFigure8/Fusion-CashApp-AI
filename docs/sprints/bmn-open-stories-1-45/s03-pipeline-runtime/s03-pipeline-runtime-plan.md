# Plan: s03-pipeline-runtime

Issue #3. Wave 2, owns `cashapp/pipeline/` (`cashapp/` = `api/src/cashapp/`). Python only; no web, no UI.

## Standards followed

- CLAUDE.md *Business layer* (one abstract `StageRunner` owning consume → claim → idempotency guard → process → persist + transition → outbox emit → failure classification), *The assembly line* (DB is the system of record; the bus carries only "item X is ready for stage Y"; transactional outbox; idempotent consumers; retry + DLQ path per stage; one consumer group per environment, never renamed; commit offsets only after persisting), non-negotiables 4/5 (no scheduler; the relay's bounded idle wait and the retry forwarder's bounded sleep are crash recovery / delivery mechanics, not pollers of an external system).
- Reference doc §7: persist before publish, commit offsets after persisting, real transactions, DLQ from day one, versioned event contract (`schema_version=1`), capture partition and offset (logged and kept on `Delivery`).
- research.md a3: aiokafka on the OCI Streaming Kafka endpoint (SASL_SSL/PLAIN), hand-rolled outbox relay with `SKIP LOCKED`, exactly two `EventBus` implementations (Kafka, in-memory).
- `python-web-app:building-python-web-apps`: services/runners never touch FastAPI `Request`; integrations isolated behind interfaces; injected `Clock`/config.
- Layering (s02 test): no `sqlalchemy` import outside `cashapp/data/`. The one SQLAlchemy-touching helper this story needs (after-commit hook) lives in a new `cashapp/data/hooks.py`. Repositories never commit; the runner owns transaction boundaries through `UnitOfWork`.
- pyright strict on `src/`; ruff. Coder gates: `uv run ruff check . && uv run ruff format --check .`, `uv run pyright`.

## Files to touch

New (owned by this story, file-disjoint from every other story):

| Path | Content |
|---|---|
| `cashapp/pipeline/events.py` | `StageEvent`, `TopicKind`, `TopicNamer`, `default_namer`, `set_default_namer`, `topic_for`, `emit`, `enqueue`, `EVENT_SCHEMA_VERSION` |
| `cashapp/pipeline/bus.py` | `EventBus` Protocol, `Delivery`, `InMemoryEventBus`, `build_event_bus` |
| `cashapp/pipeline/kafka.py` | `KafkaEventBus` (aiokafka), `_CommitTracker` (contiguous per-partition commit watermark) |
| `cashapp/pipeline/outcomes.py` | `Advance`, `Park`, `Finish`, `Archive`, `StageOutcome` |
| `cashapp/pipeline/errors.py` | `StageError`, `MalformedEvent` |
| `cashapp/pipeline/failures.py` | `FailureDecision` variants, `FailureHandler` Protocol, `EscalateAllHandler` |
| `cashapp/pipeline/runner.py` | `StageContext`, `RunnerDeps`, `HandleStatus`, `HandleResult`, `StageRunner`, `StageConsumer`, `consumer_role` |
| `cashapp/pipeline/retry.py` | `RetryForwarder`, `RETRY_ROLE` |
| `cashapp/pipeline/relay.py` | `OutboxRow`, `PublishThrottle`, `AllowAllThrottle`, `OutboxSignal`, `outbox_signal`, `OutboxRelay`, `RELAY_ROLE` |
| `cashapp/pipeline/health.py` | `StageBusHealth`, `BusHealth`, `CONSUMED_STAGES` |
| `cashapp/pipeline/roles.py` | `RoleSpec`, `RoleKind`, `Runnable`, `RoleState`, `RoleStatus`, `Container` |
| `cashapp/data/hooks.py` | `after_commit(uow, callback)` (the only SQLAlchemy event use; keeps the layering test green) |
| `api/tests/support/pipeline.py` | test support (below), registered as a pytest plugin |
| tests in the TEST PLAN | written and run in step 5 only |

Edited (append-only, small):

- `cashapp/pipeline/__init__.py` (s01 created it empty): `from .relay import RELAY_ROLE; from .retry import RETRY_ROLE; ROLES: list[RoleSpec] = [RELAY_ROLE, RETRY_ROLE]`. Nothing else is re-exported, so importing a station never drags in aiokafka.
- `api/tests/conftest.py`: append `"tests.support.pipeline"` to the `pytest_plugins` tuple (s02 rule: append only).

Not touched: s02's models/repositories/uow, `settings.py`, `main.py`, lockfiles (aiokafka, typer already pinned by s01).

## Migrations

**None.** Every column used exists in s02's `0001_base` (`WORK_ITEM.STAGE/STATE/ATTEMPTS/LAST_ERROR_CODE/LAST_ERROR_DETAIL/ESCALATION_SUMMARY/CLAIM_EXPIRES_AT/LOCK_OWNER/LOCK_EXPIRES_AT/PAYMENT_STATUS/AWAITING_SINCE/PRIORITY`, `OUTBOX.*`, `WORK_ITEM_HISTORY.*`). Message headers are derived from the payload at publish time, so `OUTBOX` needs no headers column. The Alembic head is unchanged by this story.

## Design

### Event contract and topics (`events.py`)

- `StageEvent` is a frozen Pydantic model, `extra="forbid"`, `schema_version: Literal[1] = 1`. Serialised with `model_dump_json()`; parsed with `StageEvent.model_validate_json(bytes)`. An unknown `schema_version` or any validation error is a `MalformedEvent`.
- Topic names: `{prefix}.{env}.{stage}` plus `.retry` / `.dlq`. `stage` is the enum **value** lower-cased (`cashapp.dev.match_receipt.retry`). `TopicNamer.named(name)` gives non-stage topics (`cashapp.dev.notify` for s18/s42).
- `emit` builds the topic (main, or the given kind), calls `enqueue`, and registers an after-commit callback that sets the in-process `OutboxSignal`, so the relay publishes the moment the caller commits. `emit` never commits and never publishes.
- `OUTBOX.NOT_BEFORE` is always `clock.now()` (publish immediately). The delay of a retry lives in `StageEvent.not_before`, enforced by `RetryForwarder`, not by the relay.
- Payload stored in `OUTBOX.PAYLOAD` is the event's JSON dict; `MSG_KEY` is `str(work_item_id)` (keeps one item on one partition, so its events stay ordered).

### Bus (`bus.py`, `kafka.py`)

- `Delivery` carries topic, partition, offset, key, value (bytes), headers, and `commit()`. `commit()` is idempotent.
- `KafkaEventBus`:
  - Producer: `AIOKafkaProducer(bootstrap_servers, security_protocol="SASL_SSL", sasl_mechanism="PLAIN", sasl_plain_username, sasl_plain_password=secret, ssl_context=ssl.create_default_context(), acks="all", enable_idempotence=False)`; started lazily, one per bus.
  - Consumer per `subscribe` call: same auth, `group_id=group` (callers pass `settings.streaming.consumer_group` unchanged; the bus never derives or suffixes a group), `enable_auto_commit=False`, `auto_offset_reset="earliest"` (only matters for a brand-new group; the group is never reset), `max_poll_records` small (10).
  - Commits: deliveries may finish out of order when the consumer runs several in flight, so a `_CommitTracker` per partition commits only the highest **contiguous** completed offset (`offset + 1`). A crash never skips an unfinished earlier event.
  - `consumer_lag(topic)`: sum over partitions of `end_offset − committed(group)` via the admin client `list_consumer_group_offsets` + consumer `end_offsets`. Returns `-1` when the endpoint doesn't support the call (VERIFY on OCI Streaming).
  - `dlq_depth(stage)`: `end_offset − beginning_offset` summed over the DLQ topic's partitions (messages still retained); `-1` when unknown.
  - Logs topic/partition/offset per delivery, never the value.
- `InMemoryEventBus`: per-topic append-only list; per `(group, topic)` committed offset; `subscribe` yields from the committed offset and waits on an `asyncio.Condition` for new messages; `consumer_lag` = length − committed for the default group; `dlq_depth` = DLQ topic length. Test helpers: `messages(topic) -> list[Delivery]`, `published_events(topic) -> list[StageEvent]`, `reset_group(group)` (simulates redelivery of uncommitted messages). Used for tests and `env == "local"` runs.
- `build_event_bus(settings) -> EventBus`: `env == "local"` → process-wide `InMemoryEventBus`; anything else → `KafkaEventBus(settings.streaming)`. s30's container calls this. No third implementation and no flag.

### Runner (`runner.py`)

`StageRunner.handle(delivery)` in order:

1. **Parse.** `MalformedEvent` → publish the raw bytes straight to `topic_for(self.stage, "dlq")` through the bus (no item to attach an outbox row to) with headers `error=malformed`, `source-topic`, `source-partition`, `source-offset`; commit offset; return `MALFORMED`. An event whose `stage != self.stage` is also skipped (log + commit).
2. **Claim** (own UoW, committed): `uow.work_items.claim(item_id, stage=self.stage, now=clock.now())` (s02: stage/state=PENDING/no live lock, `FOR UPDATE SKIP LOCKED`). `None` → log `skipped` with reason, commit offset, return `SKIPPED` (idempotency guard: redelivered or stale events are no-ops). Otherwise `state=IN_PROGRESS`, `claim_expires_at=now+claim_ttl`, commit. No history row for a claim (noise; the outcome row records it).
3. **Process** (second UoW, the *outcome transaction*): re-load the item with `get_for_update(skip_locked=False)`, take `config = await runtime_config.snapshot()` once, `bind_item_context(...)`, `span(f"station.{stage}")`, then `outcome = await self.process(ctx)`.
   - Stations may call `ctx.uow.commit()` mid-process to persist work as it happens (s08 readings, s15 per-line apply results). The transition is always the last commit, written by the runner.
4. **Write outcome** in that same UoW, then commit (one transaction: state change + history + next event):

   | Outcome | WORK_ITEM | History (`STAGE_TRANSITION`) | Event |
   |---|---|---|---|
   | `Advance(next, note, payload)` | `stage=next, state=PENDING, attempts=0`, clear `last_error_*`, `claim_expires_at=None` | from/to stage + state, reasoning=note, payload | `emit(StageEvent(next, attempt=0, trace_id carried), priority=item.priority)` |
   | `Park(note)` | `state=AWAITING_RECEIPT`, `awaiting_since` set if null, claim cleared | yes | none (s14 wakes it) |
   | `Finish(status, note)` | `stage=DONE, state=DONE, payment_status=status`, claim cleared | yes | none |
   | `Archive(reason)` | `state=ARCHIVED`, claim cleared | yes, reasoning=reason | none |

5. **Commit offset**, return `PROCESSED`.

Failures:

- **`StageError`**: roll back the outcome UoW (only uncommitted work is lost), open a fresh UoW, re-load the item for update, build a `StageContext` on it, call `failure_handler.handle(uow, item, error, ctx)`. Then the runner applies the decision in that UoW: `attempts += 1`, `last_error_code=error.code`, `last_error_detail=error.detail`, claim cleared, one `STAGE_TRANSITION` history row with `error_code` and `payload={"decision": <kind>, ...}` (s18 writes its own `AUTOFIX_ATTEMPT` row with reasoning; the runner's row records the state change only):

  | Decision | Effect |
  |---|---|
  | `Retry(after)` | `state=PENDING` (same stage); `emit(..., kind="retry")` with `not_before=now+after`, `attempt=item.attempts` |
  | `ParkAwaitingReceipt()` | `state=AWAITING_RECEIPT`, `awaiting_since` set if null |
  | `Escalate(summary)` | `state=ESCALATED`; `escalation_summary=summary` when not None (kept if s18 already set it) |
  | `Reroute(stage)` | `stage=<stage>, state=PENDING`; main-topic event for that stage |
  | `Resolved(outcome)` | applied exactly as the success table above (attempts still incremented first, then reset by `Advance`) |

  Commit, then commit the offset. Return `FAILED_HANDLED`.
- **Unexpected exception** (anything not `StageError`): logged with type only (no message body, PII-safe), `attempts += 1`. While `attempts < config.retries().max_attempts_for(SYSTEM_DEAD_LETTER)`: `Retry(after=backoff_for(attempts))` applied as above, `last_error_code=SYSTEM_DEAD_LETTER`, detail `{"exception": type name}`. At the limit: the error becomes `StageError(SYSTEM_DEAD_LETTER)` and is passed to the failure handler (default → `Escalate`), and the event goes to the stage's DLQ topic via `emit(..., kind="dlq")` in the same transaction. Return `DEAD_LETTERED`.
- **Failure handler raises**: treated like the limit case (escalate with `SYSTEM_DEAD_LETTER`, DLQ), so an item is never left `IN_PROGRESS` by a buggy handler.
- **Infrastructure failure in the runner's own transactions** (DB unreachable): no offset commit; `handle` raises `RunnerInfrastructureError`. `StageConsumer` marks itself `degraded`, waits a bounded backoff (1, 2, 4 … 30 s, interruptible by `stop`) and retries the **same** delivery. If the process dies instead, the claim expires and s30's startup recovery re-emits.
- Handlers may mutate `item.fix_hints`, `item.awaiting_since`, `item.escalation_summary` and write history on the given UoW. They must not commit.

`StageConsumer(runner, bus, group, *, max_in_flight=None)` is the `Runnable` for a runner: subscribes to the stage's main topic, runs up to `config.concurrency().for_stage(stage)` deliveries at once (re-read per delivery; semaphore resized lazily), stops fetching when `stop` is set and waits for in-flight deliveries. s30 adds the shutdown grace timeout and claim release around it; it does not need a second semaphore.

`consumer_role(RunnerCls, name=None)` → `RoleSpec(name or stage.value.lower().replace("_", "-"), "consumer", lambda c: StageConsumer(RunnerCls.build(c), c.bus, c.settings.streaming.consumer_group))`.

### Retry forwarder (`retry.py`)

One `Runnable` for all stages: subscribes to every `<stage>.retry` topic of `CONSUMED_STAGES` with the env's consumer group. Per delivery: parse (malformed → that stage's DLQ, commit); `await` until `not_before` with `asyncio.wait_for(stop.wait(), timeout=remaining)` in chunks of at most `max_sleep_seconds` (default 60), so shutdown is prompt; on stop, return without committing (redelivered on restart). Then publish the same bytes to the main topic **directly through the bus** (no DB state changes; at-least-once is safe because the runner's claim is idempotent) and commit. It reads nothing outside the bus.

### Outbox relay (`relay.py`)

`OutboxRelay.run(stop)` loop:

1. In a UoW: `rows = outbox.claim_batch(now=clock.now(), limit=batch_size)` (priority desc, id; SKIP LOCKED, so several relays can run).
2. For each row: `await throttle.admit(OutboxRow)`; refused rows are left untouched. Admitted rows: `bus.publish(topic, key, json bytes, headers)`; success → collected and `mark_published` together; failure → `mark_failed` (`attempts += 1`, `last_error` = exception type + truncated message, never the payload).
3. Commit.
4. Wait: if the batch was full and anything was published, loop immediately. Otherwise wait for `OutboxSignal` or `idle_seconds` (default 10), whichever comes first. If every admitted row failed, back off `min(2**n, 30)` s; if rows were only throttled, wait `throttle_wait_seconds` (default 1) or the signal.

Headers on every published message: `content-type: application/json`, `schema-version`, and `event-id` / `trace-id` / `work-item-id` when present in the payload.

### Roles (`roles.py`)

Owned here so stations depend on no host code. `Container` is a Protocol only; s30 implements it. `resolve(type)` looks up integration types (`FusionClient`, `LlmClients`, `ObjectStore`, `ReceiptApplyGate`, `Metrics`) without this module importing any of them.

## Interfaces provided (pinned)

```python
# cashapp/pipeline/events.py
EVENT_SCHEMA_VERSION: Final = 1
TopicKind = Literal["main", "retry", "dlq"]

class StageEvent(BaseModel):            # frozen=True, extra="forbid"
    schema_version: Literal[1] = 1
    event_id: UUID                       # default_factory=uuid4
    work_item_id: int
    stage: Stage
    attempt: int = 0                     # >= 0
    not_before: datetime | None = None   # tz-aware UTC; only meaningful on retry topics
    trace_id: str                        # default_factory: uuid4().hex
    emitted_at: datetime                 # tz-aware UTC
    @classmethod
    def new(cls, work_item_id: int, stage: Stage, *, clock: Clock, attempt: int = 0,
            trace_id: str | None = None, not_before: datetime | None = None) -> "StageEvent"

@dataclass(frozen=True, slots=True)
class TopicNamer:
    prefix: str; env: str
    @classmethod
    def from_settings(cls, streaming: StreamingSettings) -> "TopicNamer"   # prefix=topic_prefix, env=topic_env
    def for_stage(self, stage: Stage, kind: TopicKind = "main") -> str    # f"{prefix}.{env}.{stage.value.lower()}" + ".retry"/".dlq"
    def named(self, name: str) -> str                                     # f"{prefix}.{env}.{name}"
def default_namer() -> TopicNamer          # cached TopicNamer.from_settings(get_settings().streaming)
def set_default_namer(namer: TopicNamer | None) -> None   # tests/workers; None clears the cache
def topic_for(stage: Stage, kind: TopicKind = "main") -> str   # default_namer().for_stage(...)

async def emit(uow: UnitOfWork, event: StageEvent, priority: int = PRIORITY_LIVE, *,
               kind: TopicKind = "main", clock: Clock | None = None) -> OutboxMessage
    # THE way to emit a StageEvent. Adds one OUTBOX row (flush, no commit) and an after-commit wake-up of the relay.
async def enqueue(uow: UnitOfWork, *, topic: str, key: str, payload: BaseModel | Mapping[str, Any],
                  priority: int = PRIORITY_LIVE, clock: Clock | None = None) -> OutboxMessage
    # Lower-level outbox write for non-stage messages (s18/s42 NotifyEvent on default_namer().named("notify")).
    # Same transaction rules as emit. Nothing publishes to the bus from business code except through these two.
```

```python
# cashapp/pipeline/bus.py
@dataclass(slots=True)
class Delivery:
    topic: str; partition: int; offset: int; key: str | None; value: bytes
    headers: Mapping[str, str]
    async def commit(self) -> None          # idempotent; Kafka: contiguous-watermark commit

class EventBus(Protocol):
    async def publish(self, topic: str, key: str | None, payload: bytes,
                      headers: Mapping[str, str] | None = None) -> None: ...
    def subscribe(self, topics: Sequence[str], group: str) -> AsyncIterator[Delivery]: ...
        # async generator; closing it (aclose / break) leaves the group cleanly
    async def consumer_lag(self, topic: str) -> int: ...      # -1 = unknown
    async def dlq_depth(self, stage: Stage) -> int: ...       # -1 = unknown
    async def close(self) -> None: ...

class InMemoryEventBus:                     # implements EventBus
    def __init__(self, *, namer: TopicNamer | None = None, default_group: str = "test") -> None
    def messages(self, topic: str) -> list[Delivery]
    def published_events(self, topic: str) -> list[StageEvent]
    def reset_group(self, group: str) -> None        # replays uncommitted + committed (redelivery tests)

def build_event_bus(settings: Settings) -> EventBus  # local -> shared InMemoryEventBus; else KafkaEventBus

# cashapp/pipeline/kafka.py
class KafkaEventBus:                        # implements EventBus
    def __init__(self, streaming: StreamingSettings, *, namer: TopicNamer | None = None,
                 client_id: str = "cashapp") -> None
```

```python
# cashapp/pipeline/outcomes.py   (all @dataclass(frozen=True, slots=True))
class Advance:  next_stage: Stage; note: str = ""; payload: Mapping[str, Any] | None = None
class Park:     # kw_only=True
    state: Literal[ItemState.AWAITING_RECEIPT] = ItemState.AWAITING_RECEIPT; note: str = ""
class Finish:   payment_status: PaymentStatus; note: str = ""
class Archive:  reason: str
StageOutcome = Advance | Park | Finish | Archive

# cashapp/pipeline/errors.py
class StageError(Exception):
    code: ErrorCode; detail: dict[str, Any]; message: str
    def __init__(self, code: ErrorCode, detail: Mapping[str, Any] | None = None,
                 message: str | None = None) -> None   # message defaults to code.spec.description
    # detail must be JSON-serialisable and PII-free (ids, codes, amounts); it is stored in LAST_ERROR_DETAIL
class MalformedEvent(Exception): ...
class RunnerInfrastructureError(Exception): ...

# cashapp/pipeline/failures.py   (all @dataclass(frozen=True, slots=True))
class Retry:               after: timedelta
class ParkAwaitingReceipt: pass
class Escalate:            summary: str | None = None
class Reroute:             stage: Stage
class Resolved:            outcome: StageOutcome
FailureDecision = Retry | ParkAwaitingReceipt | Escalate | Reroute | Resolved
def decision_kind(d: FailureDecision) -> str   # "retry" | "park" | "escalate" | "reroute" | "resolved"

class FailureHandler(Protocol):
    async def handle(self, uow: UnitOfWork, item: WorkItem, error: StageError,
                     ctx: StageContext) -> FailureDecision: ...
class EscalateAllHandler:                       # default until s18; returns Escalate(None)
    async def handle(self, uow, item, error, ctx) -> FailureDecision
```

```python
# cashapp/pipeline/runner.py
@dataclass(frozen=True, slots=True)
class StageContext:
    uow: UnitOfWork
    item: WorkItem                 # loaded FOR UPDATE in ctx.uow
    principal: Principal           # SYSTEM_PRINCIPAL
    config: ConfigSnapshot         # one snapshot per event
    clock: Clock
    log: logging.LoggerAdapter[logging.Logger]   # get_logger(...) with item context bound
    event: StageEvent              # additive: the event being handled
    attempt: int                   # item.attempts at claim time

@dataclass(frozen=True, slots=True)
class RunnerDeps:
    uow_factory: UowFactory; config: RuntimeConfig; bus: EventBus; clock: Clock
    failure_handler: FailureHandler; namer: TopicNamer
    claim_ttl: timedelta = timedelta(minutes=10)
    @classmethod
    def from_container(cls, c: Container) -> "RunnerDeps"

class HandleStatus(StrEnum): PROCESSED SKIPPED FAILED_HANDLED DEAD_LETTERED MALFORMED
@dataclass(frozen=True, slots=True)
class HandleResult:
    status: HandleStatus
    outcome: StageOutcome | None = None
    decision: FailureDecision | None = None
    skip_reason: str | None = None     # "stage_mismatch" | "not_claimable"

class StageRunner(ABC):
    stage: ClassVar[Stage]
    def __init__(self, deps: RunnerDeps) -> None
    @classmethod
    def build(cls, container: Container) -> Self    # default cls(RunnerDeps.from_container(container));
                                                    # stations needing integrations override:
                                                    #   return cls(RunnerDeps.from_container(c), llm=c.resolve(LlmClients))
    @abstractmethod
    async def process(self, ctx: StageContext) -> StageOutcome: ...
    async def handle(self, delivery: Delivery) -> HandleResult      # final; stations never override

class StageConsumer:               # Runnable
    def __init__(self, runner: StageRunner, bus: EventBus, group: str, *, name: str | None = None) -> None
    async def run(self, stop: asyncio.Event) -> None
    def state(self) -> RoleState

def consumer_role(runner_cls: type[StageRunner], name: str | None = None) -> RoleSpec
```

```python
# cashapp/pipeline/retry.py
class RetryForwarder:              # Runnable
    def __init__(self, bus: EventBus, group: str, *, namer: TopicNamer, clock: Clock,
                 stages: Sequence[Stage] = CONSUMED_STAGES, max_sleep_seconds: float = 60.0) -> None
    async def run(self, stop: asyncio.Event) -> None
    def state(self) -> RoleState
RETRY_ROLE: RoleSpec               # RoleSpec("retry-forwarder", "consumer", build)

# cashapp/pipeline/relay.py
@dataclass(frozen=True, slots=True)
class OutboxRow:
    id: int; topic: str; key: str | None; priority: int; created_at: datetime
    attempts: int; work_item_id: int | None      # from payload["work_item_id"] when present
class PublishThrottle(Protocol):
    async def admit(self, row: OutboxRow) -> bool: ...
class AllowAllThrottle:            # default
    async def admit(self, row: OutboxRow) -> bool   # True
class OutboxSignal:
    def notify(self) -> None       # sync, safe from an after-commit hook
    async def wait(self, timeout: float) -> bool    # True when notified; clears on return
def outbox_signal() -> OutboxSignal                 # process-wide instance used by emit/enqueue
class OutboxRelay:                 # Runnable
    def __init__(self, uow_factory: UowFactory, bus: EventBus, clock: Clock, *,
                 throttle: PublishThrottle | None = None, signal: OutboxSignal | None = None,
                 batch_size: int = 100, idle_seconds: float = 10.0,
                 throttle_wait_seconds: float = 1.0) -> None
    async def run(self, stop: asyncio.Event) -> None
    async def run_once(self) -> int        # one claim/publish/commit cycle; returns rows published (tests, s35)
    def state(self) -> RoleState
RELAY_ROLE: RoleSpec               # RoleSpec("relay", "relay", build); build uses container.resolve(PublishThrottle)
                                   # when registered (s35 binds BacklogThrottle there), else AllowAllThrottle

# cashapp/pipeline/health.py
CONSUMED_STAGES: tuple[Stage, ...]          # PIPELINE_ORDER minus INTAKE and DONE
class StageBusHealth(TypedDict): lag: int; dlq_depth: int
class BusHealth:
    def __init__(self, bus: EventBus, namer: TopicNamer, stages: Sequence[Stage] = CONSUMED_STAGES) -> None
    async def snapshot(self) -> dict[Stage, StageBusHealth]   # lag of the main topic; -1 = unknown
```

```python
# cashapp/pipeline/roles.py
RoleKind = Literal["consumer", "poller", "relay"]
RoleStatus = Literal["starting", "running", "degraded", "stopping", "stopped"]
@dataclass(slots=True)
class RoleState:
    name: str; status: RoleStatus; last_activity_at: datetime | None = None; detail: str | None = None
class Runnable(Protocol):
    async def run(self, stop: asyncio.Event) -> None: ...
    def state(self) -> RoleState: ...
class Container(Protocol):
    @property
    def settings(self) -> Settings: ...
    @property
    def uow_factory(self) -> UowFactory: ...
    @property
    def config(self) -> RuntimeConfig: ...
    @property
    def bus(self) -> EventBus: ...
    @property
    def clock(self) -> Clock: ...
    @property
    def failure_handler(self) -> FailureHandler: ...
    def resolve(self, key: type[T]) -> T: ...      # KeyError when nothing is registered for key
@dataclass(frozen=True, slots=True)
class RoleSpec:                     # positional: RoleSpec("classify", "consumer", build)
    name: str; kind: RoleKind; build: Callable[[Container], Runnable]

# cashapp/pipeline/__init__.py
ROLES: list[RoleSpec]               # [RELAY_ROLE, RETRY_ROLE]

# cashapp/data/hooks.py
def after_commit(uow: UnitOfWork, callback: Callable[[], None]) -> None
    # sqlalchemy.event.listen(uow.session.sync_session, "after_commit", ..., once=True); fires only on a real commit
```

```python
# api/tests/support/pipeline.py   (pytest plugin)
TEST_NAMER = TopicNamer("cashapp", "test")
@pytest.fixture(autouse=True) def _pipeline_namer() -> Iterator[None]   # set_default_namer(TEST_NAMER) / clear
@pytest.fixture def memory_bus() -> InMemoryEventBus
def make_runner_deps(uow_factory: UowFactory, *, bus: EventBus | None = None, config: RuntimeConfig | None = None,
                     clock: Clock | None = None, failure_handler: FailureHandler | None = None) -> RunnerDeps
    # defaults: InMemoryEventBus(namer=TEST_NAMER), make_runtime_config() (s28, ttl 0), FrozenClock(), EscalateAllHandler()
class FakeContainer:                # implements Container; register(key, value) for resolve()
    def __init__(self, uow_factory: UowFactory, **overrides: Any) -> None
    def register(self, key: type[T], value: T) -> None
async def run_stage_once(runner: StageRunner, item_id: int, *, bus: InMemoryEventBus | None = None,
                         event: StageEvent | None = None) -> StageOutcome | FailureDecision | None
    # publishes a StageEvent for the item's current stage (or `event`) to the runner's main topic,
    # consumes exactly one delivery with runner.handle; returns outcome, decision, or None when skipped
async def drain_outbox(uow: UnitOfWork) -> list[StageEvent]
    # unpublished OUTBOX rows on stage main/retry/dlq topics, ordered by id, parsed to StageEvent,
    # marked published (flush only); non-stage rows are left alone
```

Story signature changes, recorded as assumptions: `run_stage_once(..., bus=None)` instead of a mutable default `InMemoryEventBus()`, and it returns `None` when the event is skipped (s40 asserts skips with it).

## TEST PLAN (written and run in step 5 only)

Unit tests on aiosqlite (s02 fixtures) and the in-memory bus; `-m atp` tests prove SKIP LOCKED on DEV ATP; `-m live` tests touch OCI Streaming only when credentials exist.

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/unit/pipeline/test_events.py::test_stage_event_fields_and_schema_version` |
| 1 | `…::test_stage_event_rejects_unknown_schema_version_and_extra_fields` |
| 1 | `…::test_stage_event_json_roundtrip_tz_aware` |
| 1 | `…::test_topic_for_main_retry_dlq_naming` (`cashapp.test.match_receipt[.retry/.dlq]`; prefix and env from `StreamingSettings`) |
| 1 | `…::test_topic_namer_named_for_notify` |
| 1 | `api/tests/integration/pipeline/test_emit.py::test_emit_writes_outbox_row_in_caller_transaction` (rollback → no row; commit → one row with topic, key, priority, payload) |
| 1 | `…::test_emit_does_not_publish_or_commit` |
| 1 | `…::test_emit_sets_signal_only_after_commit` |
| 1 | `…::test_enqueue_non_stage_payload` |
| 1 | `api/tests/unit/test_layering.py::test_only_outbox_publishes` (ast: `.publish(` called only inside `cashapp/pipeline/`) |
| 2 | `api/tests/unit/pipeline/test_bus_memory.py::test_publish_subscribe_commit_offsets` |
| 2 | `…::test_uncommitted_redelivered_after_reset_group` |
| 2 | `…::test_consumer_lag_and_dlq_depth` |
| 2 | `api/tests/unit/pipeline/test_bus_kafka.py::test_kafka_config_sasl_ssl_plain_no_autocommit` (aiokafka classes patched; asserts kwargs, group used unchanged) |
| 2 | `…::test_commit_tracker_commits_contiguous_watermark_only` |
| 2 | `…::test_consumer_lag_unknown_returns_minus_one` |
| 2 | `…::test_build_event_bus_local_memory_else_kafka` |
| 2 | `api/tests/live/test_kafka_streaming.py::test_roundtrip_on_oci_streaming` (`@pytest.mark.live`) |
| 3 | `api/tests/unit/pipeline/test_runner_types.py::test_stage_runner_requires_stage_and_process` |
| 3 | `…::test_outcome_and_decision_variants_frozen` |
| 3 | `…::test_stage_error_defaults_message_from_spec` |
| 3 | `…::test_context_uses_system_principal_and_snapshot` |
| 4 | `api/tests/integration/pipeline/test_runner_handle.py::test_advance_writes_state_history_and_event_in_one_transaction` |
| 4 | `…::test_malformed_event_goes_to_dlq_and_commits` |
| 4 | `…::test_stage_mismatch_skipped_and_committed` |
| 4 | `…::test_redelivered_event_after_advance_is_noop` (required by AC) |
| 4 | `…::test_live_lock_skips_expired_lock_processes` |
| 4 | `…::test_park_finish_archive_outcomes` (parametrized) |
| 4 | `…::test_offset_committed_only_after_outcome_commit` (fault-injected commit → offset not committed, `RunnerInfrastructureError`) |
| 4 | `…::test_mid_process_commit_survives_stage_error` |
| 4 | `api/tests/integration/pipeline/test_claim_atp.py::test_concurrent_claim_one_winner` (`@pytest.mark.atp`) |
| 5 | `api/tests/integration/pipeline/test_runner_failures.py::test_escalate_all_default` |
| 5 | `…::test_retry_decision_emits_retry_topic_with_not_before` |
| 5 | `…::test_park_reroute_resolved_decisions` (parametrized) |
| 5 | `…::test_failure_increments_attempts_and_records_last_error` |
| 5 | `…::test_unexpected_exception_retries_then_dead_letters` (max_attempts from config; DLQ row; `SYSTEM_DEAD_LETTER` escalated) |
| 5 | `…::test_failure_handler_exception_dead_letters` |
| 6 | `api/tests/integration/pipeline/test_retry_forwarder.py::test_waits_until_not_before_then_republishes_and_commits` (FrozenClock + bounded sleep patched) |
| 6 | `…::test_stop_during_wait_does_not_commit` |
| 6 | `…::test_malformed_retry_message_goes_to_dlq` |
| 7 | `api/tests/integration/pipeline/test_relay.py::test_publishes_by_priority_then_id_and_marks_published` |
| 7 | `…::test_publish_failure_increments_attempts_keeps_row` |
| 7 | `…::test_throttle_refusal_leaves_row_pending` |
| 7 | `…::test_signal_wakes_relay_before_idle_timeout` |
| 7 | `…::test_idle_wait_is_bounded_and_stop_exits` |
| 7 | `api/tests/integration/pipeline/test_relay_atp.py::test_two_relays_never_publish_same_row` (`@pytest.mark.atp`) |
| 8 | `api/tests/unit/pipeline/test_health.py::test_snapshot_lag_and_dlq_per_consumed_stage` |
| 9 | `api/tests/unit/pipeline/test_roles.py::test_rolespec_positional_and_kinds` |
| 9 | `…::test_pipeline_roles_exports_relay_and_retry_forwarder` |
| 9 | `…::test_consumer_role_builds_stage_consumer_from_container` (`FakeContainer`) |
| 9 | `…::test_stage_consumer_respects_concurrency_and_stops` |
| 9 | `…::test_roles_module_imports_no_integrations` (ast) |
| support | `api/tests/unit/pipeline/test_support.py::test_run_stage_once_and_drain_outbox` |

## Risks

- **aiosqlite drops `FOR UPDATE SKIP LOCKED`.** Unit tests prove the logic, not the locking. The `atp` tests cover it when DEV credentials exist.
- **OCI Streaming Kafka compatibility** (VERIFY with the `live` test): admin `list_consumer_group_offsets` (lag), idempotent producer (disabled here), topic auto-creation. Topics are expected to exist via s25; if they don't, the relay's publish fails, the row stays with `ATTEMPTS` growing, and nothing is lost. Streaming retention (24–168 h) is far above the longest retry backoff (600 s default).
- **Relay wake-up across processes.** The in-process signal only wakes a relay in the same process. Events emitted by the API (s18 requeue) wait up to `idle_seconds` (10 s). That bounded wait is crash recovery inside the worker, not a third poller. If it is ever turned into a periodic job it needs Jonathan's ruling.
- **Head-of-line blocking on retry topics.** One partition is forwarded in order, so a long `not_before` delays shorter ones behind it, by at most `max(backoff_seconds)`.
- **Same-wave deps.** s29 (`get_logger`, `bind_item_context`, `span`) and s28's `make_runtime_config` are coded against their pinned interfaces. If s29 has not merged when the coder starts, the merger reconciles imports; no local stand-ins are created (non-negotiable 7).
- **`version_id_col` on `WORK_ITEM`.** Claim and outcome happen in separate transactions, so the outcome UoW re-loads the item. A concurrent s40 lock between the two is a `StaleDataError` only if the lock path writes the same row while it is `IN_PROGRESS`; s40 is expected to refuse locking `IN_PROGRESS` items, or the runner treats `StaleDataError` as an infrastructure retry.

## Assumptions and deviations

- `emit` gains keyword-only `kind` and `clock`; `enqueue` is added for non-stage messages (`NotifyEvent`, s18/s42). Both write only to the outbox, so "the only way any code emits" still holds.
- Retry delay lives in `StageEvent.not_before` on the retry topic; `OUTBOX.NOT_BEFORE` is always "now" (s02 made it NOT NULL).
- `BusHealth.snapshot()` is `async` (Kafka calls). `consumer_lag`/`dlq_depth` return `-1` when unknown.
- `StageContext` gains `event` and `attempt`; `HandleResult` is added so tests and s30 metrics can see what happened.
- `StageConsumer` enforces per-stage concurrency (`config.concurrency().for_stage`), so s30 doesn't need a second semaphore. s30 owns the shutdown grace timeout and claim release.
- Stage topics use the lower-cased enum value. The runner writes `STAGE_TRANSITION` history for every state change; s18 writes its own `AUTOFIX_ATTEMPT` rows with reasoning.
- The DLQ is for visibility only. Re-drive is DB-based (requeue through the runner), so nothing consumes DLQ topics.
- Malformed events go to the DLQ straight through the bus, because there is no item to attach an outbox row to. This is the only place the runtime publishes outside the relay; the retry forwarder republishes the same way.
