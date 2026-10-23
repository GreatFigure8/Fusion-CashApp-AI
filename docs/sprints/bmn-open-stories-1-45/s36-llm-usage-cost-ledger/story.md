# s36-llm-usage-cost-ledger: LLM usage and cost ledger

- Issue: #36
- Wave: 3 (owns `cashapp/services/llm_usage/`, `cashapp/data/repositories/llm_usage.py`, `cashapp/api/routers/llm_usage.py`; edits `cashapp/integrations/llm/factory.py` from s08 to wrap clients)
- breaking: false

## Story

As the person paying for the models, I want every LLM call recorded with model, tokens, latency and cost against its work item and station, so that cost per remittance and per station is known and a budget can alert.

## Context

Wraps s08's `LlmClient` with a decorator, so no station code changes. Prompt/schema versions are already recorded by s08/s09 on their rows; this story adds them to the usage row too. Cohere runs on a dedicated cluster billed per hour, so its "cost" is tracked as utilisation.

## Acceptance criteria

1. [integration] One Alembic revision creates `LLM_USAGE` (ID, WORK_ITEM_ID, STATION/PURPOSE, ROLE (reader_a|reader_b|adjudicator|workhorse), PROVIDER, MODEL_ID, PROMPT_VERSION, SCHEMA_VERSION, INPUT_TOKENS, OUTPUT_TOKENS, LATENCY_MS, COST_USD NUMBER(12,6), OUTCOME (ok|refused|error|timeout), CREATED_AT).
2. [unit] `MeteredLlmClient(inner, role, recorder)` implements `LlmClient`; every `parse`/`stream_text` call (success or failure) writes one usage row through `UsageRecorder.record(...)` in its own short transaction (never inside the station's transaction, so a failed station still keeps its usage). `build_llm_clients` wraps all four roles.
3. [unit] Cost = tokens × per-model price from a code table `PRICES` (`claude-opus-5-5`, `claude-haiku-5-5`; Cohere dedicated = 0 per call) — Anthropic prices looked up via the `claude-api` skill at coding time and recorded with the date; unknown model → cost null and a warning.
4. [unit] `LlmRequest` carries `prompt_version` and `schema_version` (optional fields added to s08's dataclass, default None) and they are stored on each row; extraction and adjudication calls set them (test with s08/s09 runners).
5. [api] `GET /llm-usage/daily?from=&to=&group_by=station|model` (`reports:read`) → rows `{day, station|model, calls, input_tokens, output_tokens, cost_usd}`; `GET /llm-usage/items/{id}` → that item's calls.
6. [unit] Budget: after each recorded call, if today's total cost exceeds `config.budget().daily_usd` (when set) and no `budget_exceeded` notification was emitted today, emit one `NotifyEvent(kind="budget_exceeded")` via the outbox (once per day, test).
7. [unit] Cohere utilisation: `cohere_utilisation(window_minutes=60) -> {busy_seconds, calls, utilisation_pct}` derived from LLM_USAGE latency for role reader_b, plus `OciClusterMetrics.utilisation()` reading the dedicated AI cluster's OCI Monitoring metric when configured (UNVERIFIED metric name); exposed at `GET /llm-usage/cohere-utilisation` for the flow monitor's Extract tile (s19).

## Out of scope

Alert delivery (s42); dashboards (s19 shows the Cohere tile, s41 reports).

## Deps

- s08-extraction-fan-out — `LlmClient`, `LlmRequest`, `LlmResult.usage`, `build_llm_clients`. plannable.
- s18-auto-fix-engine — `NotifyEvent` from `cashapp/domain/notifications.py`. plannable (same wave).
- s28-runtime-config-service — `config.budget().daily_usd`. plannable.
- s03-pipeline-runtime — `emit`. plannable.
- s04-sign-in-authorization — `require_permission(REPORTS_READ)`. plannable.

## Assumptions

- Usage rows are written outside the station transaction deliberately (cost happened even if the station rolled back).
