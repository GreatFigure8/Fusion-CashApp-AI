# s29-observability: Structured logs, traces and metrics per work item

- Issue: #29
- Wave: 2 (owns `cashapp/observability/`)
- breaking: false

## Story

As an operator, I want any work item followed end to end across stations, and stage health measured, without remittance content ever being logged, so that I can diagnose problems without leaking client data.

## Context

CLAUDE.md *Conventions*: raw artifacts, prompts and model output are never logged in full outside the database or Object Storage. research.md: the redaction filter lands before any station logs. OCI Logging and Monitoring only.

## Acceptance criteria

1. [unit] `cashapp/observability/logging.py`: `configure_logging(settings)` installs JSON logging (python-json-logger) on stdout; `get_logger(name)`; `bind_item_context(work_item_id, stage, attempt, trace_id)` (contextvars) so every line carries `work_item_id`, `stage`, `attempt`, `trace_id` (null when unbound) plus `request_id` in API requests.
2. [unit] A `RedactionFilter` on every handler drops/obscures fields named in a deny-list (`payload`, `content`, `artifact`, `prompt`, `output`, `body`, `text`, `payer_name`, `email`, `subject`, `raw`) and truncates any string value over 200 chars to a length + hash marker; message strings are not formatted with record args that are bytes or Pydantic models.
3. [unit] `cashapp/observability/tracing.py`: OpenTelemetry tracer provider (OTLP exporter when `observability.otlp_endpoint` set, else no-op); `span(name, **attrs)` context manager; conventions `station.<stage>`, `fusion.<method>`, `llm.<role>` with attributes `work_item_id`, `model`, `input_tokens`, `output_tokens`, `latency_ms`; a span-attribute sanitiser applies the same deny-list.
4. [unit] `cashapp/observability/metrics.py`: `Metrics` facade — `stage_processed(stage, outcome, latency_s)`, `stage_failed(stage, error_code)`, `queue_depth(stage, state, count, oldest_age_s)`, `bus_health(stage, lag, dlq_depth)`, `llm_call(role, model, tokens_in, tokens_out, latency_ms)`; exporter `OciMonitoringExporter` posts batched `PostMetricData` to namespace `observability.oci_monitoring_namespace` (via `asyncio.to_thread`), and an `InMemoryMetrics` for tests.
5. [unit] `cashapp/observability/queue_stats.py`: `collect_queue_stats(uow) -> list[QueueStat{stage, state, count, oldest_age_s}]` (one grouped query in a new repository module) used by the worker host's health/metrics loop and by s19's flow API.
6. [unit] PII test: run a station-shaped flow with a work item whose payer, email body and extraction contain sentinel strings; assert no sentinel appears in captured log records or exported span attributes.

## Out of scope

Dashboards in OCI console; alerting (s42).

## Deps

- s27-settings-secrets-wiring — `Settings.observability{log_level, otlp_endpoint, oci_monitoring_namespace}`. plannable.
- s02-data-layer-foundation — `Stage`, `ItemState`, `UnitOfWork.repo`. plannable.

## Test-support files owned

`api/tests/support/telemetry.py`: `capture_logs()` fixture (list of dict records), `capture_spans()` (in-memory span exporter), `InMemoryMetrics` instance fixture. Used by every story asserting logs/spans.

## Assumptions

- Metrics are pushed from the worker host after each processed event and on the host's health tick; OCI Monitoring is the only sink.
