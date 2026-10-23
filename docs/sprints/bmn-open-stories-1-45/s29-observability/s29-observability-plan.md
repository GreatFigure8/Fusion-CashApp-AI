# Plan: s29-observability

Issue #29. Wave 1 (research.md lists #29 in the runtime wave: "the redaction filter lands before any
station logs"; the story file says wave 2, so it is planned to land with s03/s05/s08 in the same wave).
Owns `cashapp/observability/`. Backend only: no web files, so design.md does not apply.

## Standards followed

- **CLAUDE.md Conventions:** raw artifacts, prompts and model output are never logged in full outside the
  database or Object Storage. Enforced in one place (`redaction.py`) and applied to both log records and
  span attributes (DRY: one deny-list, one sanitiser).
- **CLAUDE.md hosting:** OCI only. Metrics go to OCI Monitoring (`PostMetricData`) in `us-ashburn-1`; traces
  go to an OTLP endpoint only when one is configured (an OCI APM collector, set by s25). Nothing else.
- **CLAUDE.md layering:** observability imports no FastAPI and no SQLAlchemy except through the new
  repository module (`cashapp/data/repositories/queue_stats.py`), the only code that queries.
- **research.md (a3):** library-composed: `python-json-logger`, `opentelemetry-api/sdk/exporter-otlp`, `oci`
  (all pinned by s01, no lockfile edit). Exactly two implementations of the metrics sink: the real
  `OciMonitoringExporter` and the in-memory fake. OCI calls are sync SDK calls wrapped in `asyncio.to_thread`.
- **python-web-app:building-python-web-apps:** observability is no-op until configured and never breaks a
  request or an event: exporter failures are logged (without content) and swallowed.
- **python-web-app:wiring-application-config:** reads `Settings.observability` (s27) as typed attributes,
  no `.get(default)`, no `or`-defaults.
- pyright strict on `src/`, ruff (`S`, `B`, `ASYNC` rules), Python 3.12.

## Files to touch

| Path | Action |
|---|---|
| `api/src/cashapp/observability/__init__.py` | edit (s01 created it empty): re-export the public names below, plus `configure_observability` |
| `api/src/cashapp/observability/redaction.py` | new: `DENY_LIST`, `is_denied_key`, `sanitize_value`, `sanitize_mapping`, `truncation_marker`, `RedactionFilter` |
| `api/src/cashapp/observability/context.py` | new: contextvars, `ItemContext`, `bind_item_context`, `current_item_context` |
| `api/src/cashapp/observability/logging.py` | new: `configure_logging`, `get_logger`, `build_json_handler`, `ContextFilter`, `CashappJsonFormatter` |
| `api/src/cashapp/observability/tracing.py` | new: `configure_tracing`, `span`, `SafeSpan`, `use_tracer_provider`, `current_trace_id`, span-name helpers |
| `api/src/cashapp/observability/metrics.py` | new: `MetricPoint`, `MetricSink`, `Metrics`, `InMemoryMetrics`, `OciMonitoringExporter`, `build_metrics` |
| `api/src/cashapp/observability/queue_stats.py` | new: `QueueStat`, `collect_queue_stats` |
| `api/src/cashapp/data/repositories/queue_stats.py` | new: `QueueStatsRepository`, `QueueStatRow` |
| `api/src/cashapp/main.py` | edit, one line inside `create_app()` after `get_settings()`: `configure_logging(settings, service_name="cashapp-api")` (and `configure_tracing`). Cross-story edit of an s01/s27 file; no other change |
| `api/tests/support/telemetry.py` | new (owned): `capture_logs`, `capture_spans`, `in_memory_metrics` fixtures |
| `api/tests/conftest.py` | edit: append `"tests.support.telemetry"` to `pytest_plugins` (s02 convention: append only) |
| `api/tests/unit/observability/__init__.py` | new, empty |
| `api/tests/unit/observability/test_logging.py` | new (step 5) |
| `api/tests/unit/observability/test_redaction.py` | new (step 5) |
| `api/tests/unit/observability/test_tracing.py` | new (step 5) |
| `api/tests/unit/observability/test_metrics.py` | new (step 5) |
| `api/tests/unit/observability/test_queue_stats.py` | new (step 5) |
| `api/tests/unit/observability/test_pii.py` | new (step 5) |

No lockfile, settings or Alembic edits.

## Design

### Redaction (`redaction.py`, the one sanitiser)

- `DENY_LIST: frozenset[str] = {"payload", "content", "artifact", "prompt", "output", "body", "text",
  "payer_name", "email", "subject", "raw"}`.
- `is_denied_key(key)`: lower-cased key equals a deny word **or ends with `_<word>`** (`email_body`,
  `raw_text`, `extraction_output` are denied). Prefix matches are deliberately not denied, so
  `output_tokens`, `prompt_key`, `content_hash` stay readable. Exact-or-suffix is pinned; tests cover both.
- Denied values are replaced with `"[REDACTED]"` (the key is kept so a reader sees something was there).
- `sanitize_value(v)`, recursive to depth 5 for dicts/lists/tuples:
  - `str` over 200 chars → `truncation_marker(s)` = `"<truncated len=<n> sha256=<first 12 hex>>"`.
  - `bytes`/`bytearray`/`memoryview` → `"<bytes len=<n>>"`.
  - Pydantic `BaseModel` → `"<model <ClassName>>"` (never `repr`, which prints field values).
  - `Decimal`, `Enum` (value), `datetime`/`date` (isoformat), `int`/`float`/`bool`/`None` pass through.
  - anything else → `"<<TypeName>>"` (no `str()`/`repr()` of unknown objects).
- `RedactionFilter(logging.Filter)`, attached to **every handler** (not the logger, so records from
  third-party loggers that propagate to root are covered):
  1. Args: each arg is replaced via `sanitize_value` *before* formatting, so a bytes or Pydantic arg is
     never formatted. Then `record.msg = record.getMessage()`, `record.args = ()`; the formatted message
     itself goes through `sanitize_value` (200-char rule).
  2. Every non-standard `LogRecord` attribute (the `extra=` fields): denied keys → `"[REDACTED]"`, other
     values → `sanitize_value`.
  3. Exceptions: `exc_info` is rendered as `exc_type` (class name) plus `stack` (frames as
     `file:line in function`, no locals, no exception message); the exception message goes to
     `exc_message` and through `sanitize_value`. `record.exc_info`/`exc_text` are then cleared so the
     formatter cannot print the raw message (pydantic `ValidationError` messages carry `input_value`).
  4. Idempotent: sets `record._cashapp_redacted = True` and skips a second pass.
- `sanitize_mapping(attrs) -> dict[str, AttrValue]` is used by tracing (same deny-list, same rules,
  output restricted to OTel-legal types: str/bool/int/float and homogeneous sequences of them).

### Context (`context.py`)

- Contextvars `_work_item_id`, `_stage`, `_attempt`, `_trace_id` (all default `None`).
- `bind_item_context(work_item_id, stage, attempt, trace_id=None)` is a **context manager** that sets all
  four and resets them on exit (tokens), so concurrent `asyncio` tasks never leak each other's item.
- `current_item_context() -> ItemContext` (frozen dataclass of the four values).

### Logging (`logging.py`)

- `CashappJsonFormatter` subclasses `pythonjsonlogger.json.JsonFormatter` (python-json-logger ≥ 3.1;
  fallback import `pythonjsonlogger.jsonlogger` recorded if the locked version is older). Fixed keys on
  every line: `timestamp` (UTC ISO-8601), `level`, `logger`, `message`, `service`, `work_item_id`, `stage`,
  `attempt`, `trace_id`, `request_id`, plus sanitised extras. Absent values are JSON `null`.
- `ContextFilter` fills the context keys: item context from `current_item_context()`; `trace_id` falls back
  to the active span's trace id (hex) only when unbound and a valid span is active, else `null`;
  `request_id` from s01's `cashapp.api.request_context.get_request_id()` (null outside API requests).
- `build_json_handler(stream: TextIO, *, service_name: str) -> logging.Handler`: `StreamHandler` +
  `ContextFilter` + `RedactionFilter` (in that order) + `CashappJsonFormatter`. The single place a handler
  is built; `configure_logging` and the `capture_logs` fixture both use it.
- `configure_logging(settings, *, stream=None, service_name="cashapp") -> None`: idempotent; replaces root
  handlers with one `build_json_handler(stream or sys.stdout)`, sets root level from
  `settings.observability.log_level`; strips handlers from `uvicorn`, `uvicorn.error`, `uvicorn.access`,
  `aiokafka`, `httpx`, `oci` loggers and sets `propagate=True`, so every line is JSON and redacted;
  `oci`/`httpx` floor at WARNING (their DEBUG lines can carry request bodies).
- `get_logger(name) -> logging.Logger` (plain stdlib logger; callers pass structured data via `extra=`).
- Convention pinned for all stories: **never interpolate remittance content into the message**; put IDs
  and counts in `extra=`. The filter cannot detect a short PII string typed into a message literal.

### Tracing (`tracing.py`)

- `configure_tracing(settings, *, service_name="cashapp", exporter: SpanExporter | None = None)
  -> TracerProvider`: builds an SDK `TracerProvider(resource={"service.name": service_name})`.
  When `settings.observability.otlp_endpoint` is set → `BatchSpanProcessor(OTLPSpanExporter(endpoint=...))`
  (HTTP/protobuf exporter, `opentelemetry.exporter.otlp.proto.http`); when `exporter` is passed (tests) →
  `SimpleSpanProcessor(exporter)`; otherwise no processor (spans are exported nowhere, but trace ids still
  exist for log correlation). Stored in a module-level holder; **the global OTel provider is not set**
  (`set_tracer_provider` is set-once and would break test isolation).
- `use_tracer_provider(provider) -> ContextManager[None]`: swap the holder (tests).
- `span(name, **attrs) -> ContextManager[SafeSpan]`: starts a span on the holder's tracer, sets
  `sanitize_mapping(attrs)`, sets `latency_ms` (monotonic) on exit. On exception: status `ERROR` with
  description = exception class name only, attribute `error.type`; **no `record_exception`** (it would copy
  the exception message into the span); the exception re-raises unchanged.
- `SafeSpan.set(**attrs)` (sanitised; used for tokens after an LLM call), `SafeSpan.trace_id -> str | None`.
- Name helpers (the conventions): `station_span(stage) -> "station.<stage lower>"`,
  `fusion_span(method) -> "fusion.<method>"`, `llm_span(role) -> "llm.<role>"`.
  Pinned attribute names: `work_item_id`, `model`, `input_tokens`, `output_tokens`, `latency_ms`.
- `current_trace_id() -> str | None` (32-hex of the active span).

### Metrics (`metrics.py`)

- `MetricPoint` (frozen dataclass): `name: str`, `value: float`, `dimensions: Mapping[str, str]`,
  `timestamp: datetime` (UTC), `unit: str | None`.
- `MetricSink` Protocol: `async def export(self, points: Sequence[MetricPoint]) -> None`.
- `Metrics(sink, *, clock: Clock | None = None, max_buffer: int = 10_000)` — the one facade. Methods append
  points to a buffer; `flush()` sends the buffer to the sink; a full buffer drops the oldest points and
  counts them in `dropped`. `flush` never raises: a sink error is logged (`metrics_export_failed`, with the
  error type and point count only) and the batch is discarded.

  | Method | Points (dimensions) |
  |---|---|
  | `stage_processed(stage, outcome, latency_s)` | `stage_processed` = 1 and `stage_latency_seconds` = latency (stage, outcome) |
  | `stage_failed(stage, error_code)` | `stage_failed` = 1 (stage, error_code) |
  | `queue_depth(stage, state, count, oldest_age_s)` | `queue_depth` = count, `queue_oldest_age_seconds` = age when not None (stage, state) |
  | `bus_health(stage, lag, dlq_depth)` | `bus_consumer_lag`, `bus_dlq_depth` (stage) |
  | `llm_call(role, model, tokens_in, tokens_out, latency_ms)` | `llm_calls` = 1, `llm_tokens_in`, `llm_tokens_out`, `llm_latency_ms` (role, model) |

  Enum arguments (`Stage`, `ItemState`, `ErrorCode`) are dumped by `.value`. Dimension values are never
  free text (all come from enums or config), so no PII reaches OCI Monitoring.
- `InMemoryMetrics(Metrics)`: sink is an in-memory list; `exported: list[MetricPoint]`,
  `points(name, **dims) -> list[MetricPoint]` (buffered + exported), `total(name, **dims) -> float`.
- `OciMonitoringExporter(client, *, namespace, compartment_id)` implements `MetricSink`: groups points by
  (name, dimensions) into `MetricDataDetails` (each with its datapoints), chunks at **50 metric streams per
  `PostMetricData` call**, and calls `client.post_metric_data(PostMetricDataDetails(...))` via
  `asyncio.to_thread`. A response with `failed_metrics_count > 0` logs a warning with the count only.
  `from_environment(namespace, compartment_id)` builds `oci.monitoring.MonitoringClient` with the ingestion
  endpoint `https://telemetry-ingestion.us-ashburn-1.oraclecloud.com` and a resource-principal signer when
  `OCI_RESOURCE_PRINCIPAL_VERSION` is set, else instance-principal (same rule as s27's Vault source).
- `build_metrics(settings) -> Metrics`: `env == "local"` → `InMemoryMetrics()`; otherwise
  `Metrics(OciMonitoringExporter.from_environment(settings.observability.oci_monitoring_namespace,
  settings.oci_genai.compartment_ocid))`. s30 resolves `Metrics` through this import path
  (`cashapp.observability.metrics:build_metrics`).

### Queue stats (`queue_stats.py` + repository)

- `QueueStatsRepository(BaseRepository[WorkItem])` in `cashapp/data/repositories/queue_stats.py`,
  obtained with `uow.repo(QueueStatsRepository)`. One grouped query:
  `SELECT stage, state, COUNT(*), MIN(COALESCE(awaiting_since, updated_at)) FROM work_item
  [WHERE state NOT IN (DONE, ARCHIVED)] GROUP BY stage, state` (uses `IX_WORK_ITEM_STAGE_STATE`).
  Returns `list[QueueStatRow]` (stage, state, count, oldest_at). Age is computed in Python, not SQL, so the
  query is identical on ATP and SQLite.
- `collect_queue_stats(uow, *, clock=None, include_terminal=False) -> list[QueueStat]`: sorted by
  `PIPELINE_ORDER` then state; `oldest_age_s = (clock.now() - oldest_at).total_seconds()`, rounded to 0.1;
  `None` for terminal states. Read-only: no commit.

## Interfaces provided (pinned)

```python
# cashapp/observability/redaction.py
DENY_LIST: Final[frozenset[str]]
MAX_STRING_LEN: Final = 200
REDACTED: Final = "[REDACTED]"
def is_denied_key(key: str) -> bool                       # exact or "_<word>" suffix, case-insensitive
def truncation_marker(value: str) -> str                  # "<truncated len=N sha256=xxxxxxxxxxxx>"
def sanitize_value(value: object, *, depth: int = 0) -> object
AttrValue = str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]
def sanitize_mapping(attrs: Mapping[str, object]) -> dict[str, AttrValue]
class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool   # always True; mutates the record

# cashapp/observability/context.py
@dataclass(frozen=True, slots=True)
class ItemContext: work_item_id: int | None; stage: str | None; attempt: int | None; trace_id: str | None
@contextmanager
def bind_item_context(work_item_id: int, stage: Stage | str, attempt: int,
                      trace_id: str | None = None) -> Iterator[ItemContext]
def current_item_context() -> ItemContext

# cashapp/observability/logging.py
LOG_FIELDS: Final = ("timestamp", "level", "logger", "message", "service",
                     "work_item_id", "stage", "attempt", "trace_id", "request_id")
def configure_logging(settings: Settings, *, stream: TextIO | None = None,
                      service_name: str = "cashapp") -> None
def get_logger(name: str) -> logging.Logger
def build_json_handler(stream: TextIO, *, service_name: str = "cashapp") -> logging.Handler
class ContextFilter(logging.Filter): ...
class CashappJsonFormatter(JsonFormatter): ...

# cashapp/observability/tracing.py
def configure_tracing(settings: Settings, *, service_name: str = "cashapp",
                      exporter: SpanExporter | None = None) -> TracerProvider
@contextmanager
def use_tracer_provider(provider: TracerProvider) -> Iterator[None]
class SafeSpan:
    def set(self, **attrs: object) -> None                # sanitised
    @property
    def trace_id(self) -> str | None
@contextmanager
def span(name: str, **attrs: object) -> Iterator[SafeSpan]
def station_span(stage: Stage | str) -> str               # "station.extract"
def fusion_span(method: str) -> str                       # "fusion.get_invoices"
def llm_span(role: str) -> str                            # "llm.reader_a"
def current_trace_id() -> str | None

# cashapp/observability/metrics.py
@dataclass(frozen=True, slots=True)
class MetricPoint: name: str; value: float; dimensions: Mapping[str, str]; timestamp: datetime; unit: str | None = None
class MetricSink(Protocol):
    async def export(self, points: Sequence[MetricPoint]) -> None: ...
class Metrics:
    def __init__(self, sink: MetricSink, *, clock: Clock | None = None, max_buffer: int = 10_000) -> None
    dropped: int
    def stage_processed(self, stage: Stage | str, outcome: str, latency_s: float) -> None
    def stage_failed(self, stage: Stage | str, error_code: ErrorCode | str) -> None
    def queue_depth(self, stage: Stage | str, state: ItemState | str, count: int, oldest_age_s: float | None) -> None
    def bus_health(self, stage: Stage | str, lag: int, dlq_depth: int) -> None
    def llm_call(self, role: str, model: str, tokens_in: int, tokens_out: int, latency_ms: float) -> None
    async def flush(self) -> None                          # never raises
class InMemoryMetrics(Metrics):
    def __init__(self, *, clock: Clock | None = None) -> None
    exported: list[MetricPoint]
    def points(self, name: str, **dims: str) -> list[MetricPoint]
    def total(self, name: str, **dims: str) -> float
class MonitoringClientLike(Protocol):
    def post_metric_data(self, post_metric_data_details: Any) -> Any: ...
class OciMonitoringExporter:                               # implements MetricSink
    MAX_STREAMS_PER_CALL: Final = 50
    def __init__(self, client: MonitoringClientLike, *, namespace: str, compartment_id: str) -> None
    @classmethod
    def from_environment(cls, namespace: str, compartment_id: str) -> "OciMonitoringExporter"
    async def export(self, points: Sequence[MetricPoint]) -> None
def build_metrics(settings: Settings) -> Metrics

# cashapp/observability/queue_stats.py
@dataclass(frozen=True, slots=True)
class QueueStat: stage: Stage; state: ItemState; count: int; oldest_age_s: float | None
async def collect_queue_stats(uow: UnitOfWork, *, clock: Clock | None = None,
                              include_terminal: bool = False) -> list[QueueStat]

# cashapp/data/repositories/queue_stats.py
@dataclass(frozen=True, slots=True)
class QueueStatRow: stage: Stage; state: ItemState; count: int; oldest_at: datetime | None
class QueueStatsRepository(BaseRepository[WorkItem]):
    async def grouped_counts(self, *, include_terminal: bool = False) -> list[QueueStatRow]

# cashapp/observability/__init__.py re-exports all of the above public names, plus
def configure_observability(settings: Settings, *, service_name: str) -> None   # logging + tracing

# api/tests/support/telemetry.py (registered via pytest_plugins)
@pytest.fixture
def capture_logs() -> Iterator[list[dict[str, Any]]]
    # attaches build_json_handler(StringIO) to root at DEBUG for the test, yields a live list of parsed
    # JSON dicts (re-parsed on each access via a list subclass), removes the handler afterwards
@pytest.fixture
def capture_spans() -> Iterator[InMemorySpanExporter]
    # TracerProvider + SimpleSpanProcessor(InMemorySpanExporter) under use_tracer_provider;
    # tests read .get_finished_spans()
@pytest.fixture
def in_memory_metrics() -> InMemoryMetrics   # InMemoryMetrics(clock=FrozenClock()) from tests.support.clock
```

Consumers: s03 (`get_logger`, `bind_item_context`, `span(station_span(stage))`, `Metrics.stage_*`),
s05 (`span(fusion_span(...))`), s08/s09/s07 (`span(llm_span(role), work_item_id=..., model=...)` then
`.set(input_tokens=..., output_tokens=...)`, `Metrics.llm_call`), s19 (`collect_queue_stats`),
s30 (`configure_logging`, `configure_tracing`, `build_metrics`, `collect_queue_stats`, `Metrics.queue_depth`,
`Metrics.bus_health` from `BusHealth.snapshot()`, `Metrics.flush`), every story's tests (`capture_logs`,
`capture_spans`, `in_memory_metrics`).

## Migrations

None. The grouped query uses s02's `IX_WORK_ITEM_STAGE_STATE`. Alembic head unchanged.

## TEST PLAN (written and run only at step 5)

All in `api/tests/unit/observability/`. SQLite via s02's `uow` fixture; no network.

| AC | Test (file::name) |
|---|---|
| 1 | `test_logging.py::test_configure_logging_emits_json_on_stream`: `configure_logging(make_settings(), stream=buf)`; one `get_logger("x").info("hello")` → one JSON line with every key in `LOG_FIELDS`; level from `observability.log_level` |
| 1 | `test_logging.py::test_unbound_context_fields_are_null`: no bind, no span → `work_item_id`, `stage`, `attempt`, `trace_id`, `request_id` are `null` |
| 1 | `test_logging.py::test_bind_item_context_sets_and_resets`: inside `bind_item_context(42, Stage.EXTRACT, 2, "ab"*16)` the record carries 42/"EXTRACT"/2/trace; after exit all null |
| 1 | `test_logging.py::test_bind_item_context_isolated_across_tasks`: two `asyncio` tasks bind different items concurrently; each task's records carry only its own id |
| 1 | `test_logging.py::test_request_id_in_api_request_logs`: small FastAPI app with s01 `RequestIdMiddleware`, route logs a line; with `X-Request-ID: req-1` the captured record has `request_id == "req-1"` |
| 1 | `test_logging.py::test_configure_logging_idempotent_and_routes_uvicorn`: called twice → root has exactly one handler; a `uvicorn.error` record comes out as redacted JSON |
| 2 | `test_redaction.py::test_denied_extra_fields_are_redacted` (parametrised over all 11 deny words, plus `email_body`, `raw_text`) → `"[REDACTED]"` |
| 2 | `test_redaction.py::test_prefix_matches_are_not_denied`: `output_tokens`, `prompt_key`, `content_hash` keep their values |
| 2 | `test_redaction.py::test_long_strings_truncated_to_marker`: a 201-char extra and a 201-char formatted message → `<truncated len=201 sha256=...>`; 200 chars unchanged; hash deterministic |
| 2 | `test_redaction.py::test_bytes_and_pydantic_args_not_formatted`: `log.info("got %s %s", b"secret-bytes", Model(secret="S"))` → message has `<bytes len=12>` and `<model Model>`, neither value |
| 2 | `test_redaction.py::test_nested_extras_sanitised`: `extra={"meta": {"body": "x", "n": 1}}` → nested body redacted, `n` kept |
| 2 | `test_redaction.py::test_exception_message_not_logged_raw`: `log.exception` on `ValueError("<long sentinel>")` → `exc_type == "ValueError"`, `stack` present, sentinel absent from the line |
| 2 | `test_redaction.py::test_filter_on_every_handler`: `build_json_handler` has `RedactionFilter` in `handler.filters`; after `configure_logging` every root handler has it |
| 3 | `test_tracing.py::test_span_exported_with_sanitised_attributes` (`capture_spans`): `span("station.extract", work_item_id=7, payload="p", note="n"*300)` → `work_item_id=7`, payload `[REDACTED]`, note truncated marker, `latency_ms` set |
| 3 | `test_tracing.py::test_safe_span_set_sanitises_and_records_tokens`: `llm_span("reader_a")`, `.set(model="m", input_tokens=10, output_tokens=5, output="x")` → tokens kept, `output` redacted |
| 3 | `test_tracing.py::test_span_name_helpers`: `station_span(Stage.MATCH_RECEIPT) == "station.match_receipt"`, `fusion_span`, `llm_span` |
| 3 | `test_tracing.py::test_span_error_records_type_not_message`: exception inside span → status ERROR, `error.type`, no event/attribute holding the message; exception re-raised |
| 3 | `test_tracing.py::test_configure_tracing_otlp_only_when_endpoint_set`: endpoint None → provider has no span processors; endpoint set → a `BatchSpanProcessor` wrapping `OTLPSpanExporter` (inspected, not called); global provider untouched |
| 3 | `test_tracing.py::test_log_trace_id_falls_back_to_active_span`: unbound log inside `span(...)` carries the span's 32-hex trace id |
| 4 | `test_metrics.py::test_facade_methods_produce_points` (`in_memory_metrics`): each of the five methods → expected names, values, dimensions (enum values), FrozenClock timestamp |
| 4 | `test_metrics.py::test_flush_moves_buffer_to_sink_and_never_raises`: a sink raising `RuntimeError` → `flush()` returns, buffer cleared, one `metrics_export_failed` warning with count only |
| 4 | `test_metrics.py::test_buffer_cap_drops_oldest`: `max_buffer=3`, 5 points → 3 kept, `dropped == 2` |
| 4 | `test_metrics.py::test_oci_exporter_batches_and_groups`: fake `MonitoringClientLike`; 120 distinct streams → 3 calls (50/50/20); same name+dims grouped into one `MetricDataDetails` with several datapoints; namespace and compartment set; call ran via `asyncio.to_thread` (thread id differs) |
| 4 | `test_metrics.py::test_oci_exporter_logs_failed_metrics_count`: response `failed_metrics_count=2` → warning, no raise |
| 4 | `test_metrics.py::test_build_metrics_local_vs_oci`: `env="local"` → `InMemoryMetrics`; `env="dev"` → `Metrics` with `OciMonitoringExporter` (with `from_environment` patched) and the configured namespace |
| 5 | `test_queue_stats.py::test_grouped_counts_and_oldest_age`: items in (EXTRACT, PENDING)×3 with different `updated_at`, (MATCH_RECEIPT, AWAITING_RECEIPT)×2 with `awaiting_since`, (DONE, DONE)×1 → two `QueueStat`s, counts 3 and 2, ages from the oldest timestamp (awaiting_since wins over updated_at), DONE excluded |
| 5 | `test_queue_stats.py::test_include_terminal_has_null_age`: `include_terminal=True` adds (DONE, DONE, 1, None) |
| 5 | `test_queue_stats.py::test_single_grouped_query`: SQLAlchemy `before_cursor_execute` listener counts exactly one SELECT with `GROUP BY` |
| 5 | `test_queue_stats.py::test_order_follows_pipeline_order` |
| 6 | `test_pii.py::test_station_flow_leaks_no_sentinels` (`capture_logs`, `capture_spans`, `uow`): a work item with `payer_name`, an email body and an extraction dict each holding distinct sentinels; a station-shaped function binds item context, opens `station.extract` and `llm.reader_a` spans with `payer_name=`, `prompt=`, `output=` attrs, logs with `extra={"payload": extraction, "email": ..., "subject": ...}`, logs a Pydantic extraction and the raw artifact bytes as args, logs a 500-char body string, and raises/logs an exception whose message holds a sentinel. Assert no sentinel in any `json.dumps(record)` or any exported span's attributes/status/events |
| 6 | `test_pii.py::test_metrics_dimensions_carry_no_free_text`: same flow's `InMemoryMetrics` points contain no sentinel in names or dimension values |

## Risks

- **Message-literal PII.** The filter can sanitise args, extras, long strings and exceptions, but not a short
  payer name concatenated into a message string by the caller (`f"paid by {name}"`). Pinned convention
  above; reviewers should reject f-string log messages carrying item data. A ruff rule (`G004`, logging
  f-string) is recommended for s26; not added here (s26 owns `pyproject.toml`).
- **OCI Monitoring contract unverified against live:** ingestion endpoint host, the 50-streams-per-call
  limit, namespace rules (lower-case, not `oci_`/`oracle_` prefixed) and datapoint age window (≈2 h past).
  Recorded "unverified against live" in a module docstring; the fake client is not a confirmed contract.
- **Compartment for metrics.** `Settings.observability` has no compartment field and s27 owns
  `settings.py` (`extra="forbid"`). This story uses `settings.oci_genai.compartment_ocid` (the app
  compartment). If s25 puts metrics in a different compartment, s27 adds
  `observability.monitoring_compartment_ocid` and `build_metrics` switches to it.
- **OCI signer duplication.** The resource/instance-principal selection repeats s27's
  `VaultSecretSource.from_environment` rule. If s27 exposes a shared signer helper at merge, use it (DRY);
  otherwise the merger should extract one into `cashapp/secrets.py`.
- **`main.py` edit** collides with s27's edit of the same function; a one-line insert, merged serially.
- **python-json-logger import path** changed in 3.1 (`pythonjsonlogger.json`); the coder checks the locked
  version and uses the matching import.
- **OTel SDK without the global provider:** third-party auto-instrumentation (none planned) would not see
  our provider. Acceptable; `configure_tracing` can additionally set the global once in production if
  needed later.
- **SQLite vs ATP:** `COALESCE` and `MIN` on a tz-aware `UtcDateTime` are portable; s02's type re-attaches
  UTC on SQLite. An `@pytest.mark.atp` variant of the grouped query is optional and not required for AC.

## Assumptions / deviations

- Deny-list matching is exact-or-`_<word>`-suffix (the story names words, not a matching rule); prefix
  matches stay readable so token counts are not redacted.
- "Drops/obscures": denied fields are kept as keys with `"[REDACTED]"`, not removed.
- `trace_id` is `null` when unbound **and** no span is active; inside an active span it falls back to the
  span's trace id (more useful, still null in the AC's unbound case).
- "Else no-op" tracing is an SDK provider with no exporter, so trace ids still exist for logs.
- `bind_item_context` is a context manager (resets on exit) rather than a bare setter.
- `oldest_age_s` measures time in the current stage/state: `awaiting_since` when set, else `updated_at`;
  terminal states excluded by default.
- Local env (`env == "local"`) uses `InMemoryMetrics` as the sink, keeping exactly two implementations.
- Metric names, dimension names and units are pinned in the Metrics table above (the story names methods,
  not metric names); s25's alarms (DLQ depth, consumer lag) must use `bus_dlq_depth` and `bus_consumer_lag`.
- Story file says wave 2; research.md places #29 in wave 1. Planned to land before any station logs.
