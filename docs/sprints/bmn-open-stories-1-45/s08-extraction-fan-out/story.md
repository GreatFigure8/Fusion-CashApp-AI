# s08-extraction-fan-out: Extraction fan-out (Opus 5.5 and Cohere Command A Vision read the same artifact)

- Issue: #8
- Wave: 2 (owns `cashapp/integrations/llm/`, `cashapp/domain/extraction.py`, `cashapp/stations/extract/`, `cashapp/data/repositories/readings.py`)
- breaking: false

## Story

As the adjudicator, I want two independent readers to extract the same remittance using one shared schema, with both results saved, so that every final value can be traced to a reader.

## Context

CLAUDE.md *Models: who does what* (roles are a decision; do not change). Reader A = `claude-opus-5-5` (Anthropic SDK, `messages.parse` structured outputs, zero data retention, never Fable, thinking can't be disabled, effort set explicitly, forced `tool_choice` returns 400, check `stop_reason == "refusal"` before content). Reader B = `cohere.command-a-vision` via OCI GenAI `GenerativeAiInferenceClient` with `DedicatedServingMode(endpoint_id=<config>)` (on-demand retired in Ashburn), wrapped in `asyncio.to_thread`. research.md: exactly two implementations per external system plus a replay fake; the Cohere dedicated endpoint is unverified until probed. This story also owns the shared `LlmClient` interface every other LLM user (s07, s09, s18, s22) consumes.

## Acceptance criteria

1. [unit] `cashapp/integrations/llm/base.py`: `LlmClient` Protocol `{provider: str; model_id: str; async parse(request: LlmRequest, schema: type[T]) -> LlmResult[T]; async stream_text(request: LlmRequest) -> AsyncIterator[str]}`; `LlmRequest{system: str, parts: list[ContentPart(text|image(bytes, media_type)|pdf(bytes))], effort: str|None, max_tokens: int, timeout_s: float, purpose: str (station/role), work_item_id: int|None}`; `LlmResult[T]{output: T|None, refused: bool, stop_reason: str, usage: LlmUsage{model_id, input_tokens, output_tokens, latency_ms}, response_id: str|None}`; `LlmError(code: LLM_TRANSIENT|LLM_REFUSAL|EXTRACTION_FAILED, ...)`. `LlmClients{reader_a, reader_b, adjudicator, workhorse}` built by `factory.build_llm_clients(settings, config)` from `config.models()`.
2. [unit] `AnthropicLlmClient` uses `client.messages.parse(..., output_format=<schema>)` (structured outputs), sets effort explicitly from config, never sets forced `tool_choice`, checks `stop_reason == "refusal"` before reading content (→ `refused=True`, `output=None`), maps rate-limit/overloaded/5xx/timeouts to `LLM_TRANSIENT`; constructor refuses any model id containing "fable". `stream_text` uses `messages.stream`. PDFs/images sent as document/image content blocks.
3. [unit] `OciCohereLlmClient` calls chat with `serving_mode=DedicatedServingMode(endpoint_id=settings.oci_genai.dedicated_endpoint_ocid)` in Ashburn, sends images (PDF pages rendered to PNG via pdf text+image fallback), requests JSON matching the schema (JSON schema in the prompt + `response_format` JSON), validates with Pydantic, and maps failures; `stream_text` raises `NotImplementedError` (Cohere is reader-only).
4. [unit] `ReplayLlmClient` (fake) returns recorded `LlmResult`s keyed by `(purpose, sha256(parts))` from `api/tests/fixtures/llm/*.json`, or a scripted sequence; can simulate refusal, timeout and transient errors.
5. [unit] `cashapp/domain/extraction.py`: one Pydantic schema `RemittanceExtraction` (`SCHEMA_VERSION = "1"`) with `Extracted[T]{value: T|None, source: SourceLocation{part_no, page|None, bbox|None (x,y,w,h normalised 0-1), quote|None}, confidence: float 0-1}` wrappers: payer_name, payer_bank_account, remittance_reference, payment_amount (`MoneyStr`), currency_raw, currency (ISO|None), currency_ambiguous: bool (`$` without country), dates: list[DateCandidate{value, kind: payment|issue|order|deposit|other}], payment_date (chosen), lines: list[ExtractedLine{line_no, kind: INVOICE|CREDIT_MEMO|UNKNOWN|BANK_FEE|TARIFF|DISCOUNT, transaction_number: str (never numeric; suffixes like `-1` kept), amount_paid|None, gross_amount|None, discount_claimed|None, deduction|None, po_number|None, sales_order|None, ers_reference|None}], po_refs, sales_order_refs, ers_refs, bank_fees: list[Money], notes. A test round-trips `"2598014"` and `"2598014-1"` as strings and a line with no amounts.
6. [unit] Prompts live in `cashapp/stations/extract/prompts.py` with `PROMPT_VERSION`; both readers get the same parts and the same schema.
7. [integration] One Alembic revision creates `EXTRACTION_READING` (ID, WORK_ITEM_ID, READER (A|B), MODEL_ID, PROMPT_VERSION, SCHEMA_VERSION, STATUS (OK|FAILED|TIMEOUT|REFUSED), OUTPUT JSON, ERROR_CODE, ERROR_MESSAGE, INPUT_TOKENS, OUTPUT_TOKENS, LATENCY_MS, ATTEMPT, CREATED_AT, PURGED_AT).
8. [integration] `ExtractRunner(StageRunner)` (stage EXTRACT): loads the item's `ARTIFACT_PART`s via `ObjectStore.get`, runs both readers concurrently each bounded by `config.extraction().fanin_timeout_seconds` (and its role `timeout_s`), persists each reading row separately as it completes (OK/FAILED/TIMEOUT/REFUSED, with prompt and schema version), then returns `Advance(ADJUDICATE)` if at least one reading is OK; if both failed it raises `StageError(EXTRACTION_FAILED)`. A re-run (auto-fix) adds new rows with `ATTEMPT+1` and can be limited to the failed reader(s) via `item.HUMAN_HINTS["rerun_readers"]` and a higher effort via `HUMAN_HINTS["effort"]`.
9. [unit] `ROLE = RoleSpec("extract", "consumer", build)`.
10. [integration] `-m live` probes: one Opus call and one Cohere dedicated-endpoint call on a synthetic remittance; skipped without credentials; the Cohere result is recorded as "unverified against live" until it passes.

## Out of scope

Adjudication (s09); usage/cost rows (s36 wraps `LlmClient`); classification (s07).

## Deps

- s03-pipeline-runtime — `StageRunner`, `StageContext`, `Advance`, `StageError`. plannable (same wave).
- s06-intake-poller — `ObjectStore.get(key)`, `ARTIFACT_PART` columns (`PART_NO, KIND, MEDIA_TYPE, OBJECT_KEY`). plannable (same wave).
- s27-settings-secrets-wiring — `Settings.anthropic`, `Settings.oci_genai`. plannable.
- s28-runtime-config-service — `config.models()`, `config.extraction()`. plannable.
- s02-data-layer-foundation — `MoneyStr`, `ErrorCode`, `Stage`. plannable.
- s29-observability — `span("llm.<role>")` with token attributes. plannable (same wave).
- s30-worker-host — `RoleSpec`. plannable (same wave).

## Test-support files owned

`cashapp/integrations/llm/fake.py` (`ReplayLlmClient`), `api/tests/fixtures/llm/`, `api/tests/support/llm.py` (`scripted_llm(outputs=...)`, `make_extraction(**overrides) -> RemittanceExtraction`). Used by s07, s09, s10, s11, s18, s22, s24.

## Assumptions

- The fan-in timeout is enforced here, where both readers run concurrently in one station; s09 adjudicates once both readings are terminal. (Running each reader as its own event would break single-claim semantics.)
- Default efforts: reader A `high`, adjudicator `medium` (config).
