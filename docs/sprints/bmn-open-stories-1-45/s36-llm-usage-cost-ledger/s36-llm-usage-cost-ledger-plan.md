# s36-llm-usage-cost-ledger: plan

Issue #36. Wave index 2 (with s07, s09, s18 in parallel). Python only: no web files, no UI (s19 renders the Cohere tile, s41 does reports). Paths: `cashapp/` = `api/src/cashapp/`.

## Standards followed

- **CLAUDE.md**
  - Layering. `data/` is the only code that touches SQLAlchemy. The router validates, authorizes and shapes JSON, and nothing more. Services never see `Request`. The integration layer (`MeteredLlmClient`) imports neither FastAPI nor SQLAlchemy.
  - DRY. There is one metering decorator, used for all four roles, and one `compute_cost` (s24 reuses it). The `NotifyEvent` comes from s18's module and is not redefined here.
  - Money and decimals. USD cost is a `Decimal` quantized to 6 dp with `ROUND_HALF_UP` and serialized as a string, never a float. The budget compares `Decimal` to `Decimal`.
  - PII. A usage row holds ids, model, versions, token counts, latency, cost and outcome. It never holds prompt, artifact or output text. The budget notification carries totals only.
  - Auditability. Every LLM call is a row keyed to its work item and station.
- **claude-api skill (checked 2026-10-23, model table cached 2026-10-06).** First-party per-MTok prices: `claude-opus-5-5` costs $4.00 input and $20.00 output. `claude-haiku-5-5` costs $0.10 input and $0.50 output for prompts up to 100K tokens, and $0.50 / $2.50 beyond that. Output tokens include thinking tokens, which are billed as output, so `usage.output_tokens` is the right input. Fable models are never priced or allowed (zero retention).
- **python-llm-features:building-llm-backed-features.**
  - The pricing table is one typed module.
  - An unknown model gives `cost_usd = None` plus a warning, never a made-up zero.
  - Reports show `unpriced_calls`, so a partial total isn't presented as complete.
  - No live model calls in tests: the inner client is s08's `ReplayLlmClient`.
- **python-web-app:building-python-web-apps.**
  - Routes call services, and services use repositories through the UoW.
  - Pydantic v2 response schemas are kept separate from the ORM.
  - Dependencies are `Annotated` aliases (s04 `UowFactoryDep`, `require_permission`).
  - One error shape: s01 `ApiError`.
- **research.md.**
  - Every external system has exactly two implementations behind its interface.
    - Recorders: `DbUsageRecorder` (real) and `InMemoryUsageRecorder` (fake).
    - Cluster metrics: `OciClusterMetrics` (real) and `FakeClusterMetrics`.
  - The OCI Monitoring metric name and namespace are marked **UNVERIFIED against live**.
  - The router is auto-discovered, so `main.py` isn't edited. The migration is exactly one revision on the current head.

## Files to touch

New files are owned by this story. Edits to other stories' files are minimal and additive, and each is listed.

| Path | Kind | Content |
|---|---|---|
| `cashapp/domain/llm_usage.py` | new | `LlmRole`, `UsageOutcome`, `UsageGroupBy`, `UsageEntry`, `UsdStr`, `to_usd`, `station_of(purpose)` |
| `cashapp/integrations/llm/metered.py` | new | `UsageRecorder` Protocol, `StreamUsageReporter` Protocol, `MeteredLlmClient` |
| `cashapp/integrations/llm/cluster_metrics.py` | new | `ClusterUtilisation`, `ClusterMetrics` Protocol, `OciClusterMetrics` (+ `MonitoringQueryClient` seam), `FakeClusterMetrics`, `build_cluster_metrics(settings)` |
| `cashapp/services/llm_usage/__init__.py` | new | re-exports the public names below |
| `cashapp/services/llm_usage/pricing.py` | new | `ModelPrice`, `PRICES`, `PRICES_AS_OF`, `PRICES_SOURCE`, `compute_cost` |
| `cashapp/services/llm_usage/recorder.py` | new | `DbUsageRecorder`, `InMemoryUsageRecorder`, `build_usage_recorder`, `default_uow_factory` |
| `cashapp/services/llm_usage/budget.py` | new | `BUDGET_NOTIFY_KIND`, `check_budget` |
| `cashapp/services/llm_usage/reporting.py` | new | `DailyUsage`, `UsageCall`, `CohereUtilisation`, `daily_usage`, `item_usage`, `cohere_utilisation` |
| `cashapp/data/models/llm_usage.py` | new | ORM `LlmUsage`, `LlmBudgetAlert` (picked up by s02 `load_all_models()`; nothing else edited) |
| `cashapp/data/repositories/llm_usage.py` | new | `LlmUsageRepository`, `LlmBudgetAlertRepository`, `DailyUsageRow` |
| `cashapp/api/schemas/llm_usage.py` | new | `DailyUsageOut`, `UsageCallOut`, `CohereUtilisationOut`, `ClusterUtilisationOut` |
| `cashapp/api/routers/llm_usage.py` | new | `router` (prefix `/llm-usage`, tag `llm-usage`), auto-discovered |
| `api/alembic/versions/<rev>_s36_llm_usage.py` | new | the one revision (see Migrations) |
| `cashapp/integrations/llm/factory.py` (s08) | **edit** | `build_llm_clients` gains keyword-only `recorder=None, uow_factory=None` and wraps all four roles in `MeteredLlmClient` |
| `cashapp/integrations/llm/anthropic_client.py` (s08) | **edit, additive** | adds `stream_text_metered(request, on_usage)`. `stream_text` delegates to it with a no-op callback, so the stream's final `usage` is reported. `stream_text` behaviour is unchanged |
| `cashapp/workers/container.py` (s30) | **edit, one line** | the `LlmClients` factory call passes `uow_factory=self.uow_factory` and `config=self.config` (RuntimeConfig), so workers reuse the container engine |
| `cashapp/config/settings.py` (s27, the `OciGenAiSettings` group; exact path as s27 built it) | **edit, append** | `dedicated_cluster_ocid: str \| None = None`, `cluster_metric_namespace: str = "oci_generativeai"`, `cluster_metric_query: str \| None = None` (UNVERIFIED) |
| `api/tests/support/llm_usage.py` | new | `make_usage_entry(**kw)`, `metered(inner, role, recorder=None)` helpers |
| test files in the TEST PLAN | new | written in step 5 only |

Not touched:
- `cashapp/integrations/llm/base.py`. s08 already added `prompt_version` and `schema_version` to `LlmRequest`, so AC4 needs no edit to it.
- `main.py`, the lockfiles (`oci` is already pinned), `config_keys.py` (`budget.daily_usd` already exists in s02), and s18's `notifications.py` (consumed only).

## Design

### Domain (`cashapp/domain/llm_usage.py`)

- `LlmRole(StrEnum)` has four values: `READER_A="reader_a"`, `READER_B="reader_b"`, `ADJUDICATOR="adjudicator"` and `WORKHORSE="workhorse"`.
- `UsageOutcome(StrEnum)` has four values: `OK="ok"`, `REFUSED="refused"`, `ERROR="error"` and `TIMEOUT="timeout"`.
- `UsageGroupBy(StrEnum)` has two values: `STATION="station"` and `MODEL="model"`.
- `station_of(purpose)` returns the text before the first `.`, lower-cased, at most 40 chars. `"extract.reader_a"` gives `"extract"`; a purpose with no dot gives the whole purpose.
- `to_usd(d)` quantizes to `Decimal("0.000001")` with `ROUND_HALF_UP`. A float raises `TypeError`.
- `UsdStr` is the s02 `MoneyStr` pattern at 6 dp: a Decimal that is a string in JSON and OpenAPI (`^-?\d+\.\d{6}$`).

### Metering decorator (`MeteredLlmClient`)

- `MeteredLlmClient(inner, role, recorder, *, clock=None)` implements s08's `LlmClient`. `provider` and `model_id` forward to `inner`. `with_model(m)` returns `MeteredLlmClient(inner.with_model(m), role, recorder, clock=clock)`, so `LlmClients.with_models` keeps every role metered.
- **`parse`**
  1. Start a `perf_counter` timer and `await inner.parse(...)`.
  2. On success, the outcome is `REFUSED` if `result.refused`, else `OK`. Tokens and latency come from `result.usage`; latency falls back to the wrapper's own timer when `usage.latency_ms` is 0.
  3. `LlmError` maps to `REFUSED` when the code is `LLM_REFUSAL`, else `ERROR`. Tokens come from `err.usage` when present, else null. `error_code` is `err.code`.
  4. `asyncio.TimeoutError` or `CancelledError` gives `TIMEOUT` with null tokens. This covers s08's `wait_for` and fan-in cancel.
  5. Any other `Exception` gives `ERROR` with `error_code=None`.
  6. In every branch, `UsageEntry` is built and recorded, then the original result is returned or the original exception re-raised, unchanged.
  7. On cancellation, the record runs under `asyncio.shield` and a second `CancelledError` while recording is swallowed before the re-raise. The cancel is never lost.
- **`stream_text`** is an async generator. When the inner client satisfies `StreamUsageReporter` (`stream_text_metered(request, on_usage)`), it is iterated with a callback that captures the final `LlmUsage`. Otherwise the inner `stream_text` is used and tokens are null.
  - Outcomes: normal end is `OK`. `LlmError(LLM_REFUSAL)` is `REFUSED`. Other errors are `ERROR`. `GeneratorExit`/`CancelledError` (the consumer disconnected) is `TIMEOUT`.
  - Exactly one row is written per call, in a `finally`, and the record is shielded.
- **The recorder never fails the call.** `UsageRecorder.record` implementations catch and log `llm_usage_record_failed` (ids and the exception type only) and return.
- **`UsageEntry`** carries:
  - from the request: `work_item_id`, `purpose`, `station` (via `station_of(purpose)`), `prompt_version`, `schema_version`, `effort`
  - from the wrapper: `role`
  - from the call: `provider`, `model_id` (from the result or error usage, else the inner `model_id`), `input_tokens`, `output_tokens`, `latency_ms`, `outcome`, `error_code`, `occurred_at` (clock)
- Cost is not computed in the integration layer. The recorder computes it, so `pricing` stays a service.

### Recorder (`services/llm_usage/recorder.py`)

`DbUsageRecorder(uow_factory, runtime_config, *, clock)` handles each call in two steps.

1. **Write the row.**
   - It opens its **own short UoW** (`async with uow_factory() as uow`) and never uses the station's transaction.
   - `cost = compute_cost(model_id, input_tokens, output_tokens)` is null when tokens are null or the model is unknown.
   - It sets `USAGE_DAY = occurred_at.astimezone(UTC).date()`, calls `LlmUsageRepository.add` and commits.
2. **Check the budget**, only when `(await runtime_config.budget()).daily_usd` is set and the in-process `_alerted_day` isn't today.
   - A second short UoW runs `check_budget(uow, day=..., limit=..., now=...)`. If it returns an event, the UoW commits; otherwise it exits.
   - An `IntegrityError` here means another worker already alerted. It is caught, nothing more is done, and `_alerted_day` is set to today.
   - Every exception is logged and swallowed. The usage row was already committed in step 1.

Other recorder pieces:
- `InMemoryUsageRecorder` is the test fake. It has `entries: list[UsageEntry]` and an optional `fail: bool` that simulates a DB outage.
- `build_usage_recorder(uow_factory, config=None, *, clock=None)` accepts a `RuntimeConfig`. With a `ConfigSnapshot` or `None`, it builds `build_runtime_config(uow_factory)` (s28).
- `default_uow_factory(settings)` is `lru_cache`d per settings object and built with s01 `create_engine(settings.atp.url()..., **atp.engine_kwargs())` and s02 `make_uow_factory`. It's used only when a caller of `build_llm_clients` passes no `uow_factory`, for example a script or the API process before s22 wires its own.

### Budget (`services/llm_usage/budget.py`)

`check_budget(uow, *, day, limit, now) -> NotifyEvent | None` runs in this order.

1. `total = LlmUsageRepository.cost_for_day(day)`. If `total <= limit`, return None.
2. Try `LlmBudgetAlertRepository.add(LlmBudgetAlert(alert_day=day, limit_usd=limit, total_usd=total, emitted_at=now))`. The flush raises `IntegrityError` on the `ALERT_DAY` PK if a row exists. The caller handles that.
3. Build the event: `NotifyEvent(kind="budget_exceeded", severity="warning", work_item_id=None, error_code=None, summary=f"LLM spend for {day} UTC is {total} USD, over the daily budget of {limit} USD", occurred_at=now)`.
4. Write `enqueue(uow, topic=default_namer().named("notify"), key=f"budget_exceeded:{day.isoformat()}", payload=event)` (s03). It goes in the same transaction as the alert row, so the alert and the outbox message commit together.
5. Return the event.

Once per day is guaranteed by the PK across processes. The in-process `_alerted_day` only saves the query.

### Pricing (`services/llm_usage/pricing.py`)

```python
PRICES_AS_OF: Final = date(2026, 10, 23)
PRICES_SOURCE: Final = "claude-api skill model table (cached 2026-10-06), first-party Claude API rates"
PRICES: Final[Mapping[str, ModelPrice]] = MappingProxyType({
    "claude-opus-5-5":  ModelPrice(input_per_mtok=Decimal("4.00"), output_per_mtok=Decimal("20.00")),
    "claude-haiku-5-5": ModelPrice(input_per_mtok=Decimal("0.10"), output_per_mtok=Decimal("0.50"),
                                   long_context_threshold=100_000,
                                   long_input_per_mtok=Decimal("0.50"), long_output_per_mtok=Decimal("2.50")),
    "cohere.command-a-vision": ModelPrice(billing="dedicated"),   # billed per cluster-hour; 0 per call
})
```

- `compute_cost(model_id, input_tokens, output_tokens)` works as follows:
  - Tokens of `None` give `None`.
  - `billing == "dedicated"` gives `Decimal("0.000000")`.
  - Otherwise, when `input_tokens > long_context_threshold`, both long rates apply.
  - The result is `to_usd((in*ip + out*op) / 1_000_000)`.
  - An unknown model gives `None` and a single `logger.warning("llm_price_unknown", extra={"model_id": ...})` per model id per process.
- A model id containing `fable` is never added. A test asserts it.
- **The coder re-checks these figures with the claude-api skill at coding time** and updates `PRICES_AS_OF` if anything changed.

### Reporting (`services/llm_usage/reporting.py`)

- **`daily_usage(uow, *, from_day, to_day, group_by)`** returns `list[DailyUsage]`.
  - The repository groups by `USAGE_DAY` plus `STATION` or `MODEL_ID`.
  - Each row has `calls`, `input_tokens`, `output_tokens` (null sums become 0), `cost_usd` (the sum of known costs, 0 when none) and `unpriced_calls` (rows with null cost).
  - Rows are ordered by day, then key.
- **`item_usage(uow, item_id)`** returns `list[UsageCall]`, every row for the item ordered by `CREATED_AT, ID`.
- **`cohere_utilisation(uow, *, window_minutes=60, clock=None, cluster=None)`** returns `CohereUtilisation`.
  - It looks at `role = reader_b` rows with `CREATED_AT >= now - window`.
  - `busy_seconds` is `sum(LATENCY_MS)/1000`, rounded to 1 dp, and `calls` is the count.
  - `utilisation_pct = round(busy_seconds / (window_minutes*60) * 100, 1)`. It is not capped: concurrent calls can push it over 100, and the docstring says so.
  - `cluster_utilisation_pct` comes from `await cluster.utilisation(window_minutes)` when a cluster is given and configured. On any error it is `None`, and the error is logged.
  - `best_pct` is `cluster_utilisation_pct` when not None, else `utilisation_pct`. s19 shows `best_pct`.

### Cluster metrics (`integrations/llm/cluster_metrics.py`)

- `OciClusterMetrics(client: MonitoringQueryClient, *, compartment_ocid, cluster_ocid, namespace, query_template)` sets `configured = bool(cluster_ocid and query_template)`.
- `utilisation(window_minutes)` calls `client.summarize_metrics_data(compartment_id, SummarizeMetricsDataDetails(namespace, query=query_template.format(cluster_ocid=...), start_time, end_time))` through `asyncio.to_thread`. It returns `ClusterUtilisation(pct=mean of the latest aggregated datapoints, source="oci_monitoring", metric=query)` or `None` when no datapoints come back.
- The namespace and metric name are **UNVERIFIED**. The default is `cluster_metric_query=None`, so the metric is off until someone sets it. The coder confirms the class names by introspecting the pinned `oci.monitoring.models` and never guesses them.
- `build_cluster_metrics(settings)` returns `OciClusterMetrics` with a signer chosen the s08 way (resource principal, then instance principal, then `~/.oci/config`), or `None` when it isn't configured.
- `FakeClusterMetrics(pct | Exception | None)` is the test fake.

### Router (`api/routers/llm_usage.py`)

- **`GET /llm-usage/daily`** requires `require_permission(Permission.REPORTS_READ)`.
  - Query: `from: date = Query(alias="from")`, `to: date`, `group_by: UsageGroupBy = "station"`. Defaults: `to` is today (UTC) and `from` is `to - 6 days`.
  - `from > to`, or a range over 366 days, raises `ApiError(422, "invalid_range", ...)`.
  - Returns `list[DailyUsageOut]`.
- **`GET /llm-usage/items/{item_id}`** requires `REPORTS_READ`.
  - A missing work item raises `ApiError(404, "work_item_not_found")`.
  - Returns `list[UsageCallOut]`, which is empty when the item has no calls.
- **`GET /llm-usage/cohere-utilisation?window_minutes=60`** (1 to 1440) requires `require_permission(Permission.ITEMS_READ)`, the flow monitor's permission (see Assumptions). It returns `CohereUtilisationOut`. The cluster comes from a module-level cached `build_cluster_metrics(get_settings())`.
- The UoW comes from s04's `UowFactoryDep`: one read-only UoW per request, never committed.

## Interfaces provided (pinned)

```python
# cashapp/domain/llm_usage.py
class LlmRole(StrEnum): READER_A="reader_a"; READER_B="reader_b"; ADJUDICATOR="adjudicator"; WORKHORSE="workhorse"
class UsageOutcome(StrEnum): OK="ok"; REFUSED="refused"; ERROR="error"; TIMEOUT="timeout"
class UsageGroupBy(StrEnum): STATION="station"; MODEL="model"
UsdStr = Annotated[Decimal, ...]                  # 6 dp, string in JSON/OpenAPI
def to_usd(value: Decimal | int | str) -> Decimal
def station_of(purpose: str) -> str
@dataclass(frozen=True, slots=True)
class UsageEntry:
    role: LlmRole; provider: str; model_id: str; purpose: str; station: str
    work_item_id: int | None; prompt_version: str | None; schema_version: str | None; effort: str | None
    input_tokens: int | None; output_tokens: int | None; latency_ms: int
    outcome: UsageOutcome; error_code: str | None; occurred_at: datetime   # tz-aware UTC
```

```python
# cashapp/integrations/llm/metered.py
class UsageRecorder(Protocol):
    async def record(self, entry: UsageEntry) -> None: ...      # never raises
@runtime_checkable
class StreamUsageReporter(Protocol):
    def stream_text_metered(self, request: LlmRequest, on_usage: Callable[[LlmUsage], None]) -> AsyncIterator[str]: ...
class MeteredLlmClient:                                          # implements LlmClient
    def __init__(self, inner: LlmClient, role: LlmRole, recorder: UsageRecorder, *, clock: Clock | None = None) -> None
    inner: LlmClient; role: LlmRole
    provider / model_id / with_model / parse / stream_text  per s08's LlmClient
```

```python
# cashapp/integrations/llm/factory.py   (s08 signature, extended keyword-only)
def build_llm_clients(settings: Settings, config: RuntimeConfig | ConfigSnapshot | None = None, *,
                      recorder: UsageRecorder | None = None, uow_factory: UowFactory | None = None) -> LlmClients
    # every role is MeteredLlmClient(inner, LlmRole.<ROLE>, recorder); recorder defaults to
    # build_usage_recorder(uow_factory or default_uow_factory(settings), config)  (lazy import of the service)
    # s30 container: build_llm_clients(settings, self.config, uow_factory=self.uow_factory)
    # s22 (API process): build_llm_clients(get_settings(), runtime_config, uow_factory=<UowFactoryDep factory>)
```

```python
# cashapp/integrations/llm/cluster_metrics.py
@dataclass(frozen=True, slots=True)
class ClusterUtilisation: pct: float; source: Literal["oci_monitoring"]; metric: str
class ClusterMetrics(Protocol):
    configured: bool
    async def utilisation(self, window_minutes: int) -> ClusterUtilisation | None: ...
class OciClusterMetrics: ...       # real (UNVERIFIED metric)
class FakeClusterMetrics: def __init__(self, result: float | Exception | None = None) -> None
def build_cluster_metrics(settings: Settings) -> ClusterMetrics | None
```

```python
# cashapp/services/llm_usage/pricing.py   (s24 consumes PRICES and compute_cost)
@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_mtok: Decimal = Decimal(0); output_per_mtok: Decimal = Decimal(0)
    long_context_threshold: int | None = None
    long_input_per_mtok: Decimal | None = None; long_output_per_mtok: Decimal | None = None
    billing: Literal["per_token", "dedicated"] = "per_token"
PRICES: Final[Mapping[str, ModelPrice]]; PRICES_AS_OF: Final[date]; PRICES_SOURCE: Final[str]
def compute_cost(model_id: str, input_tokens: int | None, output_tokens: int | None) -> Decimal | None
def cost_of_usage(usage: LlmUsage) -> Decimal | None          # convenience for s24: compute_cost(usage.model_id, ...)
```

```python
# cashapp/services/llm_usage/recorder.py
class DbUsageRecorder:          # implements UsageRecorder
    def __init__(self, uow_factory: UowFactory, runtime_config: RuntimeConfig, *, clock: Clock | None = None) -> None
class InMemoryUsageRecorder:    # implements UsageRecorder (tests)
    entries: list[UsageEntry]
    def __init__(self, *, fail: bool = False) -> None
def build_usage_recorder(uow_factory: UowFactory, config: RuntimeConfig | ConfigSnapshot | None = None, *,
                         clock: Clock | None = None) -> DbUsageRecorder
def default_uow_factory(settings: Settings) -> UowFactory

# cashapp/services/llm_usage/budget.py
BUDGET_NOTIFY_KIND: Final = "budget_exceeded"
async def check_budget(uow: UnitOfWork, *, day: date, limit: Decimal, now: datetime) -> NotifyEvent | None

# cashapp/services/llm_usage/reporting.py   (s19 and s41 consume)
@dataclass(frozen=True, slots=True)
class DailyUsage: day: date; station: str | None; model: str | None; calls: int; input_tokens: int
                  output_tokens: int; cost_usd: Decimal; unpriced_calls: int
@dataclass(frozen=True, slots=True)
class UsageCall: id: int; created_at: datetime; station: str; purpose: str; role: LlmRole; provider: str
                 model_id: str; prompt_version: str | None; schema_version: str | None; effort: str | None
                 input_tokens: int | None; output_tokens: int | None; latency_ms: int
                 cost_usd: Decimal | None; outcome: UsageOutcome; error_code: str | None
@dataclass(frozen=True, slots=True)
class CohereUtilisation: window_minutes: int; busy_seconds: float; calls: int; utilisation_pct: float
                         cluster_utilisation_pct: float | None
    @property
    def best_pct(self) -> float     # cluster value when present, else ledger-derived
async def daily_usage(uow: UnitOfWork, *, from_day: date, to_day: date, group_by: UsageGroupBy) -> list[DailyUsage]
async def item_usage(uow: UnitOfWork, item_id: int) -> list[UsageCall]
async def cohere_utilisation(uow: UnitOfWork, *, window_minutes: int = 60, clock: Clock | None = None,
                             cluster: ClusterMetrics | None = None) -> CohereUtilisation
```

```python
# cashapp/data/models/llm_usage.py   (tables llm_usage → LLM_USAGE, llm_budget_alert → LLM_BUDGET_ALERT)
class LlmUsage(Base):
    id: int (IdentityPk); work_item_id: int | None (FK work_item.id, FK_LLM_USAGE_WI); station: str (String(40))
    purpose: str (String(100)); role: LlmRole (StrEnumType); provider: str (String(20)); model_id: str (String(100))
    prompt_version: str | None (String(20)); schema_version: str | None (String(20)); effort: str | None (String(10))
    input_tokens: int | None; output_tokens: int | None; latency_ms: int; cost_usd: Decimal | None (Numeric(12, 6, asdecimal=True))
    outcome: UsageOutcome (StrEnumType); error_code: str | None (String(40)); usage_day: date (Date); created_at: datetime (UtcDateTime)
class LlmBudgetAlert(Base):
    alert_day: date (PK, Date); limit_usd: Decimal (MoneyNumeric); total_usd: Decimal (Numeric(12, 6)); emitted_at: datetime (UtcDateTime)

# cashapp/data/repositories/llm_usage.py
@dataclass(frozen=True, slots=True)
class DailyUsageRow: day: date; key: str; calls: int; input_tokens: int; output_tokens: int; cost_usd: Decimal; unpriced_calls: int
class LlmUsageRepository(BaseRepository[LlmUsage]):
    async def daily(self, *, from_day: date, to_day: date, group_by: UsageGroupBy) -> list[DailyUsageRow]
    async def for_item(self, item_id: int) -> list[LlmUsage]                 # created_at, id
    async def cost_for_day(self, day: date) -> Decimal                       # SUM(COST_USD) where USAGE_DAY=day; 0 when none
    async def busy_since(self, role: LlmRole, since: datetime) -> tuple[int, int]   # (sum latency_ms, calls)
    async def purge_before(self, cutoff: datetime) -> int                    # for s45 if it chooses to age usage rows
class LlmBudgetAlertRepository(BaseRepository[LlmBudgetAlert]):
    async def for_day(self, day: date) -> LlmBudgetAlert | None
```

```python
# cashapp/api/schemas/llm_usage.py
class DailyUsageOut(BaseModel): day: date; station: str | None; model: str | None; calls: int; input_tokens: int
                                output_tokens: int; cost_usd: UsdStr; unpriced_calls: int
class UsageCallOut(BaseModel): ...UsageCall fields; cost_usd: UsdStr | None
class CohereUtilisationOut(BaseModel): window_minutes: int; busy_seconds: float; calls: int; utilisation_pct: float
                                       cluster_utilisation_pct: float | None; best_pct: float
# Routes: GET /llm-usage/daily -> list[DailyUsageOut]; GET /llm-usage/items/{item_id} -> list[UsageCallOut];
#         GET /llm-usage/cohere-utilisation -> CohereUtilisationOut
```

## Migrations

- There is one revision, `api/alembic/versions/<rev>_s36_llm_usage.py`, hand-written.
  - **Expected parent:** the current head when coded. Wave-index-2 siblings (s07 `CLASSIFICATION`, s09 `ADJUDICATION`, s18) may land first. With none of them merged, the parent is the wave-1 head (s08 `EXTRACTION_READING`, or whichever wave-1 revision is last).
  - The merger re-points `down_revision` and checks that `alembic heads` returns exactly one head.
- It creates **`LLM_USAGE`**:
  - `ID` (identity PK)
  - `WORK_ITEM_ID NUMBER NULL` with FK `FK_LLM_USAGE_WI` to `WORK_ITEM.ID`. It's nullable because chat about the flow has no item.
  - `STATION VARCHAR2(40) NOT NULL`
  - `PURPOSE VARCHAR2(100) NOT NULL`
  - `ROLE VARCHAR2(20) NOT NULL`
  - `PROVIDER VARCHAR2(20) NOT NULL`
  - `MODEL_ID VARCHAR2(100) NOT NULL`
  - `PROMPT_VERSION VARCHAR2(20) NULL`
  - `SCHEMA_VERSION VARCHAR2(20) NULL`
  - `EFFORT VARCHAR2(10) NULL`
  - `INPUT_TOKENS NUMBER(10) NULL`
  - `OUTPUT_TOKENS NUMBER(10) NULL`
  - `LATENCY_MS NUMBER(10) NOT NULL`
  - `COST_USD NUMBER(12,6) NULL`
  - `OUTCOME VARCHAR2(10) NOT NULL`
  - `ERROR_CODE VARCHAR2(40) NULL`
  - `USAGE_DAY DATE NOT NULL`
  - `CREATED_AT TIMESTAMP WITH TIME ZONE NOT NULL`
  - Indexes: `IX_LLM_USAGE_DAY` (`USAGE_DAY`, `STATION`), `IX_LLM_USAGE_ITEM` (`WORK_ITEM_ID`, `CREATED_AT`) and `IX_LLM_USAGE_ROLE_AT` (`ROLE`, `CREATED_AT`).
  - No CHECK constraints (the s02 enum rule).
- It creates **`LLM_BUDGET_ALERT`**: `ALERT_DAY DATE` PK (`PK_LLM_BUDGET_ALERT`), `LIMIT_USD NUMBER(18,2) NOT NULL`, `TOTAL_USD NUMBER(12,6) NOT NULL` and `EMITTED_AT TIMESTAMP WITH TIME ZONE NOT NULL`.
- Downgrade drops the indexes, then both tables. DEV ATP only.

## TEST PLAN (written and run in step 5 only)

`metered` is `api/tests/unit/integrations/llm/test_metered.py`. `recorder` is `api/tests/unit/services/llm_usage/test_recorder.py`. Unit tests use s02's sqlite `uow_factory`, s08's `ReplayLlmClient`/`scripted_llm`, s02's `FrozenClock`, s28's `make_config_snapshot` and s03's `InMemoryEventBus` with the outbox relay. They make no network calls.

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `api/tests/integration/test_llm_usage_migration_atp.py::test_upgrade_downgrade_atp` (`-m atp`) | `LLM_USAGE` has exactly the listed columns and types (`COST_USD` NUMBER(12,6)), identity PK, nullable FK to `WORK_ITEM` and 3 indexes. `LLM_BUDGET_ALERT` PK on `ALERT_DAY`. Downgrade drops both. One Alembic head. |
| 1 | `api/tests/unit/data/test_llm_usage_schema.py::test_models_match_migration_columns` | ORM column sets equal the migration's `create_table` columns (offline Oracle SQL), and `alembic heads` is a single head (ScriptDirectory). |
| 1 | `api/tests/unit/data/test_llm_usage_repository.py::test_add_and_cost_roundtrip_decimal` | A row with `cost_usd=Decimal("0.123457")` round-trips as `Decimal` at 6 dp; `usage_day` is stored. |
| 2 | `metered::test_parse_ok_records_one_row` | Scripted OK result: exactly one `UsageEntry` with role, provider, model_id, purpose, `station="extract"`, work_item_id, tokens and latency from `result.usage`, `outcome=ok`. The result is returned unchanged. |
| 2 | `metered::test_parse_refused_result_records_refused` | `ReplayLlmClient.refusal()` gives `outcome=refused`, and the result still comes back with `refused=True`. |
| 2 | `metered::test_parse_llm_error_records_error_and_reraises` | `transient()` gives `outcome=error`, `error_code="LLM_TRANSIENT"`, tokens from `err.usage` or null. The same `LlmError` instance is re-raised. `LLM_REFUSAL` error gives `refused`. |
| 2 | `metered::test_timeout_and_cancel_record_timeout` | `asyncio.wait_for(metered.parse(...), 0.05)` around `timeout()` gives one `outcome=timeout` row and `TimeoutError` propagates. A cancelled task records `timeout` and stays cancelled. |
| 2 | `metered::test_stream_text_records_once_with_usage` | An inner client with `stream_text_metered` reporting usage: chunks pass through in order and one row carries the reported tokens. An inner client without the method gives one row with null tokens. A consumer `aclose()` mid-stream gives `timeout`. A refusal mid-stream gives `refused` and re-raises. |
| 2 | `metered::test_with_model_keeps_metering` | `LlmClients(...).with_models(snapshot.models())` returns `MeteredLlmClient`s with the same role and recorder and the new `model_id`. |
| 2 | `metered::test_recorder_failure_never_breaks_call` | `InMemoryUsageRecorder(fail=True)` or a `DbUsageRecorder` on a disposed engine: `parse` still returns the result, and `llm_usage_record_failed` is logged with no content. |
| 2 | `recorder::test_row_committed_outside_station_transaction` | A station UoW opened and rolled back around a metered call: the usage row is still visible from a fresh UoW. |
| 2 | `api/tests/unit/integrations/llm/test_factory_metered.py::test_build_llm_clients_wraps_all_four_roles` | `build_llm_clients(settings, config, uow_factory=...)` returns four `MeteredLlmClient`s with roles reader_a, reader_b, adjudicator and workhorse. Inner clients are the s08 Anthropic/Cohere clients, built with fake transports as in s08's factory test. |
| 3 | `api/tests/unit/services/llm_usage/test_pricing.py::test_opus_and_haiku_cost` | Opus 1,000,000 in + 100,000 out gives `6.000000`. Haiku 50,000 in + 2,000 out gives `0.006000`. Haiku 150,000 in (over 100K) + 1,000 out gives `0.077500` (long rates). 6 dp, `ROUND_HALF_UP`. |
| 3 | `…::test_cohere_dedicated_is_zero` | `cohere.command-a-vision` gives `Decimal("0.000000")`. |
| 3 | `…::test_unknown_model_is_null_and_warns_once` | An unknown id gives `None`, and two calls produce exactly one `llm_price_unknown` warning. Null tokens give `None`. |
| 3 | `…::test_prices_table_metadata` | `PRICES_AS_OF` is a `date`, `PRICES_SOURCE` is non-empty, no key contains `fable`, and every per-token price is a `Decimal`. |
| 3 | `recorder::test_cost_written_on_row` | A recorded Opus entry stores `COST_USD` equal to `compute_cost(...)`; an unknown model stores NULL. |
| 4 | `metered::test_prompt_and_schema_version_stored` | An `LlmRequest(prompt_version="7", schema_version="3")` call is stored with those values; defaults (None) are stored as NULL. |
| 4 | `api/tests/unit/stations/test_versions_on_usage.py::test_extract_runner_rows_carry_versions` | `ExtractRunner` (s08) with metered replay readers gives two usage rows with `PROMPT_VERSION == extract.prompts.PROMPT_VERSION` and `SCHEMA_VERSION == domain.extraction.SCHEMA_VERSION`, roles reader_a and reader_b, `station="extract"`. |
| 4 | `…::test_adjudicate_runner_rows_carry_versions` | The s09 runner with a metered replay adjudicator gives one row with s09's `PROMPT_VERSION` and `SCHEMA_VERSION`, role adjudicator. |
| 5 | `api/tests/api/test_llm_usage_routes.py::test_daily_group_by_station_and_model` | Seeded rows over two days, stations and models. `group_by=station` and `group_by=model` return the expected `{day, station or model, calls, input_tokens, output_tokens, cost_usd}`. `cost_usd` is a 6-dp string. `unpriced_calls` counts null-cost rows. |
| 5 | `…::test_daily_defaults_and_range_validation` | No params gives the last 7 days. `from > to` or more than 366 days gives 422 in the single error shape. |
| 5 | `…::test_daily_requires_reports_read` | Without `reports:read`, 403 `forbidden`. Unauthenticated, 401. |
| 5 | `…::test_item_calls_and_404` | `/llm-usage/items/{id}` lists that item's calls in time order, with no content fields. An unknown item gives 404. An item with no calls gives `[]`. |
| 5 | `…::test_routes_in_openapi` | The three operations are present, and `cost_usd` is `type: string` in the schema. |
| 6 | `api/tests/unit/services/llm_usage/test_budget.py::test_emits_once_per_day` | `budget.daily_usd=1.00` with calls totalling 0.60 emits no event. The next call pushes the total to 1.20 and gives exactly one outbox row on `<prefix>.<env>.notify` with `kind=budget_exceeded`, `severity=warning`, key `budget_exceeded:<day>`. Further calls that day add nothing. After `FrozenClock` moves to the next day and spend goes over again, there is exactly one more. |
| 6 | `…::test_no_budget_configured_no_check` | `daily_usd=None` runs no budget query (repository spy) and writes no outbox row. |
| 6 | `…::test_concurrent_recorders_alert_once` | Two `DbUsageRecorder`s (separate in-process state) on one DB, both over the limit: exactly one `LLM_BUDGET_ALERT` row and one outbox row. The `IntegrityError` path is swallowed. |
| 6 | `…::test_notify_summary_has_no_content` | The event summary contains only totals, limit and day, with no sentinel prompt or payer text. |
| 7 | `api/tests/unit/services/llm_usage/test_reporting.py::test_cohere_utilisation_from_ledger` | reader_b rows in the last 60 min: 3 calls with latencies of 30 s, 60 s and 90 s give `busy_seconds=180.0`, `calls=3`, `utilisation_pct=5.0`. Rows outside the window and other roles are ignored. `best_pct` is the ledger value when there is no cluster. |
| 7 | `…::test_cluster_metric_preferred_and_errors_tolerated` | `FakeClusterMetrics(42.0)` gives `cluster_utilisation_pct=42.0` and `best_pct=42.0`. `FakeClusterMetrics(RuntimeError())` gives `None`, the ledger value and a logged warning. |
| 7 | `api/tests/unit/integrations/llm/test_cluster_metrics.py::test_oci_query_shape_and_thread` | A fake `MonitoringQueryClient` captures the call: namespace, query containing the cluster OCID, start and end window, and the call ran via `asyncio.to_thread`. Unconfigured (no query) means `build_cluster_metrics` returns `None`. |
| 7 | `api/tests/api/test_llm_usage_routes.py::test_cohere_utilisation_route` | Returns `CohereUtilisationOut`. `window_minutes` outside 1–1440 gives 422. Requires `items:read`. |

Gates for the coder: `uv run ruff check . && uv run ruff format --check .` and `uv run pyright` only.

## Assumptions and deviations

- **An extra `USAGE_DAY DATE` column** (UTC date, set at insert) makes daily grouping and the budget sum portable across Oracle and SQLite, and indexable without `TRUNC()` on a timestamp. **The day boundary is UTC** for both reports and budget; a tenant-local day would be a later config key.
- **Extra nullable columns `PURPOSE`, `EFFORT` and `ERROR_CODE`.** AC1 reads "STATION/PURPOSE", so both are stored: station is derived from the purpose prefix, and the full purpose keeps the role detail. Effort and error code make the cost of "re-run at higher effort" and the cost of failures visible. All three are additive.
- **A second table, `LLM_BUDGET_ALERT`, goes in the same single revision.** It gives a durable, cross-process "once per day" through its PK. A per-process flag or an outbox lookup would double-alert with several workers. The alert row and the outbox message commit in one transaction.
- **Tokens are null when the provider returned no usage** (timeouts, transport errors, or a stream from a client without `stream_text_metered`). Cost is then null, and reports count those rows in `unpriced_calls` rather than pretending they cost zero.
- **Cancellation is recorded as `timeout`.** That covers both the s08 fan-in deadline and a chat client disconnecting.
- **No prompt-cache token pricing.** s08's `LlmUsage` carries only input and output tokens, and no station uses prompt caching. If caching is added, `LlmUsage` and `ModelPrice` gain cache fields together.
- **Haiku long-context rule.** When a request's input exceeds 100K tokens, both its input and output are billed at the higher rate, following the claude-api skill note "($0.50 / $2.50 beyond)". The coder confirms this at coding time.
- **s08 file edits.**
  - `factory.py`: keyword-only parameters, so the s30 call shape keeps working.
  - `anthropic_client.py`: an additive `stream_text_metered`, so chat (s22) gets real token counts without changing `base.py`.
  - `config` may be a `RuntimeConfig`, which is what s30 actually passes, or a `ConfigSnapshot`, which is what s08 typed. The merger reconciles the s08 annotation to the union.
- **s30 container edit.** One line passes `uow_factory=self.uow_factory`, so usage rows reuse the worker's engine. Without it, `default_uow_factory(settings)` opens a second small pool. That's correct, but wasteful.
- **s27 settings append.** The cluster OCID and metric query live in `OciGenAiSettings` (infrastructure facts, not runtime-tunable). Defaults are None, so OCI metrics are off until someone configures them.
- **`/llm-usage/cohere-utilisation` uses `items:read`, not `reports:read`.** It feeds the flow monitor, which every operator sees. `/daily` and `/items/{id}` use `reports:read` as the story says.
- **`utilisation_pct` isn't capped at 100.** Concurrent reader_b calls can make busy time exceed wall time; capping would hide saturation.
- **s18 dependency.** The plan codes against the story's `NotifyEvent` shape (`event_id, kind, severity, work_item_id, error_code, summary, occurred_at`) in `cashapp/domain/notifications.py`, with the topic from `default_namer().named("notify")`. If s18's plan pins a helper (for example `notify(uow, event)`), the coder uses it instead of calling `enqueue` directly.
- **s09 dependency for AC4.** This plan assumes s09's adjudication `LlmRequest` sets `prompt_version` and `schema_version`. If s09's merged code omits them, the coder adds those two keyword arguments in s09's request builder; that's the only edit.

## Risks

- **Recording cost on the hot path.** Each LLM call adds one insert and one commit, plus one `SUM` per call when a budget is set. This is small next to a multi-second model call, and the `IX_LLM_USAGE_DAY` index keeps the sum cheap. `_alerted_day` skips the check after the day's alert.
- **The shielded record during cancellation** can delay a cancelled reader task by one DB round trip. The fan-in deadline in s08 already waits for cancelled tasks, so the delay is bounded.
- **The OCI Monitoring metric for dedicated AI clusters is UNVERIFIED** (namespace, metric name, dimension key). It's off by default. The ledger-derived value always works. A `-m live` probe is left for when credentials exist and isn't part of this story's test plan.
- **The price table goes stale.** Prices are code, dated and sourced. A price change means a code change that the coder re-checks with the claude-api skill. Usage rows store the cost at the time of the call, so history isn't re-priced.
- **Cross-story contracts in the same wave** (s18 `NotifyEvent`, s09 runner) are coded against their story ACs. The merger reconciles names if their plans differ.
- **The column name `ROLE`** isn't on Oracle's reserved-word list, but if DEV ATP rejects it unquoted, the fallback is `LLM_ROLE`. The ORM attribute stays `role`. The `atp` migration test catches this.
