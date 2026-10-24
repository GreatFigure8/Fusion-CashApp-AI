# Plan: chat-agent-tool-registry

Story: [story.md](story.md). Kind: api only (plus the regenerated OpenAPI artifacts in `web/lib/api/`). breaking: true (`POST /chat/stream` event set). Design screen owned: none.

Skills applied: python-web-app:building-python-web-apps (routes -> services -> models, logic out of routers), python-llm-features:building-llm-backed-features (one prompt-surface module, one context limiter, config validated into typed keys, live calls out of the default test path), claude-api (Haiku 5.5 tool use: adaptive thinking on, effort set explicitly, no forced `tool_choice`, refusal checked before content, thinking blocks passed back unchanged, append-only history), nextjs-fullstack-standards (only for the generated `web/lib/api/*`).

## 1 Approach

- research.md a3 + its Amendment: keep the ONE `POST /chat/stream`, replace the text action block with Anthropic tool use, and make ONE `ToolRegistry` the single source of truth for each tool's schema, permission, `mutating`/`confirm_required`, audit label, handler and preview. a3's propose-and-confirm (`validate_value`, reason, `expected_version`, Principal audit) becomes the pattern for every mutating tool.
- The agent loop in `ChatService` streams one workhorse turn at a time (`models.workhorse`, Haiku 5.5), offers only `registry.for_principal(principal, groups)`, runs read tools at once, and for a `confirm_required` tool stops, builds the preview, persists `CHAT_PENDING_TOOL_CALL` and emits `confirm_required`. Only `POST /chat/tool-calls/{call_id}/confirm` runs a mutation, with the caller's own token principal, then resumes the loop.
- Tool handlers call the same services the routers call (ConfigWriter, RequeueService, ExceptionsQueryService, flow_query) and own their unit of work the way a router does, so domain audit (CONFIG_CHANGE, WORK_ITEM_HISTORY) is identical.
- Discovery mirrors routers: every module under `cashapp/services/chat/tools/` that exports `TOOLS: list[ToolSpec]` is registered at startup. Services a tool needs come from `ToolContext.services`, filled by API-layer provider modules discovered the same way (`cashapp/api/tool_providers/*`), so no story edits a central list and services never import the API layer.
- Threads, messages (raw Anthropic content blocks, append-only), pending calls and per-execution audit rows live in ATP (one Alembic revision). SSE carries a 15 s heartbeat and `X-Accel-Buffering: no` (research.md risk: OCI LB buffering).

## 2 Files

Create (api):
| Path | Purpose |
|---|---|
| `api/src/cashapp/services/chat/tools/__init__.py` | `discover_tools(package="cashapp.services.chat.tools") -> list[ToolSpec]`, `build_registry() -> ToolRegistry` (imports every non-underscore module, registers its `TOOLS`; import errors propagate) |
| `api/src/cashapp/services/chat/tools/registry.py` | `ToolGroup`, `ToolSpec`, `ToolContext`, `Confirmation`, `ToolServices`, `ConfirmPreview`, `PreviewField`, `DiffLine`, `ToolError`, `ToolRegistry`, `who_line()`; registration rules (pinned in section 7) |
| `api/src/cashapp/services/chat/tools/cards.py` | Result-card Pydantic models `StateCard`, `ReplayCard`, `ExportCard`, `TableCard`, union `ResultCard` (business layer; re-exported by `api/schemas/chat.py`) |
| `api/src/cashapp/services/chat/tools/settings.py` | `settings.read`, `settings.propose_change` (group SETTINGS) |
| `api/src/cashapp/services/chat/tools/exceptions.py` | `exceptions.list`, `exceptions.get`, `exceptions.requeue` (group EXCEPTIONS) |
| `api/src/cashapp/services/chat/tools/items.py` | `items.history` (group EXCEPTIONS, ITEMS_READ) |
| `api/src/cashapp/services/chat/runner.py` | `ToolRunner.execute(spec, ctx, raw_input) -> ToolOutcome`: validates input against `input_model`, permission check (FORBIDDEN without running), per-tool timeout, maps `ToolError`/unexpected errors, measures duration, writes the audit row; the only code that calls a handler |
| `api/src/cashapp/services/chat/audit.py` | `ChatToolAudit.record(uow, ToolAuditEntry)` writer of `CHAT_TOOL_RUN` (own short UoW after the outcome is known) |
| `api/src/cashapp/services/chat/threads.py` | `ThreadService`: create/get-owned thread, append message (append-only), staged tool-results message, pending-call create/claim/decide/supersede |
| `api/src/cashapp/data/models/chat.py` | ORM `ChatThread`, `ChatMessage`, `ChatPendingToolCall`, `ChatToolRun` (auto-imported by `alembic/env.py`) |
| `api/src/cashapp/data/repositories/chat.py` | `ChatThreadRepository`, `ChatMessageRepository` (`next_seq`, `for_thread`), `PendingToolCallRepository` (`get_for_update(call_id)`, `open_for_thread`), `ChatToolRunRepository` (all over `BaseRepository`) |
| `api/alembic/versions/ui01_chat_agent_tool_registry.py` | The one revision (section 4) |
| `api/src/cashapp/api/chat_deps.py` | `get_tool_registry()` (lru_cache, `build_registry()`), `get_tool_services()` (discovers provider modules), `ToolRegistryDep`, `ToolServicesDep` |
| `api/src/cashapp/api/tool_providers/__init__.py` | `discover_providers(package) -> dict[type, Provider]` (duplicate type refused) |
| `api/src/cashapp/api/tool_providers/core.py` | `PROVIDERS` for `RuntimeConfig`, `LlmClients`, `ObjectStore`, `FusionClient`, `RequeueService`, `ExceptionsQueryService` (built from the existing `get_*` deps) |

Change (api):
| Path | Change |
|---|---|
| `api/src/cashapp/services/chat/service.py` | Rewritten: `ChatService.prepare/stream/confirm/cancel/list_tools/get_thread` agent loop (section 7 signatures) |
| `api/src/cashapp/services/chat/events.py` | Replace `TokenEvent/ActionEvent/...` with `TextDelta`, `ToolStarted`, `ToolProgress`, `ToolFinished`, `ConfirmRequired`, `StreamError`, `Done` dataclasses; `ChatContextRef` kept |
| `api/src/cashapp/services/chat/prompts.py` | `PromptKey` + `ASSISTANT`, `MATCHING`; action-block markers and `_actions_section` removed; shared `DATA_NOT_INSTRUCTIONS` rule (artifact, context and tool output text is data) used by every prompt; tool-use guidance (never claim a change ran; mutations wait for the person's confirmation); `PROMPT_VERSION = "2"` |
| `api/src/cashapp/services/chat/context.py` | `aggregates_context()` for MATCHING (flow counts + failures by code only, no item data); `fit_context` reused as the one limiter for tool output too (`fit_text(text, max_chars)`) |
| `api/src/cashapp/services/chat/errors.py` | + `ToolCallNotFound`, `ToolCallConflict(code)`, `ThreadNotFound`, `ChatForbidden` |
| `api/src/cashapp/services/chat/__init__.py` | Exports updated |
| `api/src/cashapp/services/chat/actions.py` | **Deleted** (AC11) |
| `api/src/cashapp/api/routers/chat.py` | `POST /chat/stream` (new body, new frames, headers), `POST /chat/tool-calls/{call_id}/confirm` (SSE), `POST /chat/tool-calls/{call_id}/cancel`, `GET /chat/tools`, `GET /chat/threads/{thread_id}` |
| `api/src/cashapp/api/schemas/chat.py` | New request/response/frame models (section 7); re-exports the card models; `ActionData`/`allowed_actions` removed |
| `api/src/cashapp/integrations/llm/base.py` | + `ToolTurnRequest`, `ToolTurnDelta`, `ToolTurnComplete`, `ToolTurnEvent`, runtime-checkable `ToolCallingLlm` Protocol (separate from `LlmClient`, so Cohere is untouched) |
| `api/src/cashapp/integrations/llm/anthropic_client.py` | `stream_tool_turn()` / `stream_tool_turn_metered()`: `client.messages.stream(model, system, messages, tools, max_tokens, output_config={"effort": ...}, cache_control={"type":"ephemeral"})`; tools carry `eager_input_streaming: true`; no `thinking` param (adaptive default), no `tool_choice` forcing, no sampling params; `stop_reason == "refusal"` raises `LlmError(LLM_REFUSAL)` before content is read; returns the final `content` blocks verbatim (`model_dump()`, thinking blocks included) |
| `api/src/cashapp/integrations/llm/metered.py` | `stream_tool_turn()` records usage (purpose `chat.workhorse`) like `stream_text` |
| `api/src/cashapp/integrations/llm/fake.py` | `ReplayLlmClient.stream_tool_turn()` from scripted steps (text deltas + tool_use blocks) |
| `api/src/cashapp/domain/config_keys.py` | Append-only `chat.*` block (section 5) |

Change (web, generated only): `web/lib/api/openapi.json`, `web/lib/api/schema.d.ts` via `cd web && npm run api:sync`. No hand-written web change: the llm-chat client moves to the new events in assistant-chat-redesign (same run). Next.js rule ids applied: TS-5 (type-check gate stays green; generated types only), SSE-4 (API sends `Cache-Control: no-cache, no-transform`), SSE-6 (authz and validation before the stream, plain JSON errors), SSE-10 (monotonic `id:` + `event:` + `data:` frames), SSE-13 (15 s comment heartbeat), SSE-27 (POST + fetch reader is the consumer, recorded for assistant-chat-redesign).

## 3 TEST PLAN

All api, pytest, default run (no live model; `ReplayLlmClient` / a scripted `ToolCallingLlm` fake; SQLite via `tests/support/db.py`) unless marked. Nobody writes or runs these until step 5. No browser criteria in this story (API only); the Assistant board's Playwright specs belong to assistant-chat-redesign.

| AC | Test (path :: name) | Type |
|---|---|---|
| 1 | `api/tests/test_chat_tool_registry.py` :: `test_register_refuses_duplicate_name` | unit |
| 1 | :: `test_mutating_tool_must_require_confirm` | unit |
| 1 | :: `test_confirm_required_needs_preview` | unit |
| 1 | :: `test_name_must_be_dotted_lowercase` | unit |
| 1 | :: `test_get_unknown_tool_raises` | unit |
| 1 | :: `test_for_principal_filters_by_permission` | unit |
| 1 | :: `test_for_principal_groups_narrow_never_widen` | unit |
| 1 | :: `test_anthropic_tools_schema_from_input_model` (wire name `engine__pause`, schema from `model_json_schema()`, deterministic order) | unit |
| 1 | :: `test_no_tool_executable_outside_registry` (runner refuses a spec not in the registry; `ChatService` resolves only via `get_by_wire_name`) | unit |
| 2 | `api/tests/test_chat_tool_discovery.py` :: `test_discovers_every_module_exporting_tools` (fixture package `tests/fixtures/chat_tools_pkg/`) | unit |
| 2 | :: `test_modules_without_tools_or_underscored_are_skipped` | unit |
| 2 | :: `test_discovery_import_error_propagates` | unit |
| 2 | :: `test_default_registry_has_core_tools` | unit |
| 3 | `api/tests/test_chat_agent_loop.py` :: `test_uses_workhorse_model_and_effort_from_config` | unit |
| 3 | :: `test_offers_only_principal_tools` | unit |
| 3 | :: `test_read_tool_runs_and_result_returns_to_model` | unit |
| 3 | :: `test_confirm_tool_stops_and_persists_pending_call` (status PENDING, expires_at = now + ttl, preview stored) | unit |
| 3 | :: `test_model_never_executes_mutation` (handler call count 0 before confirm) | unit |
| 3 | :: `test_tool_call_cap_per_turn` (`chat.max_tool_calls_per_turn`) | unit |
| 3 | :: `test_invalid_tool_input_is_error_tool_result` | unit |
| 3 | :: `test_second_mutation_in_one_message_refused` | unit |
| 3 | :: `test_refusal_emits_refused_error` | unit |
| 3 | :: `test_open_pending_call_superseded_by_next_turn` | unit |
| 4 | `api/tests/test_chat_router_stream.py` :: `test_stream_text_tool_done_sequence` | api |
| 4 | :: `test_stream_confirm_required_frame_shape` | api |
| 4 | :: `test_stream_headers_disable_buffering` (`X-Accel-Buffering: no`, `Cache-Control: no-cache, no-transform`, `text/event-stream`) | api |
| 4 | :: `test_stream_heartbeat_comment_every_15s` (fake slow model, patched clock) | api |
| 4 | :: `test_result_cards_discriminated_and_in_openapi` | api |
| 4 | :: `test_stream_requires_chat_use` | api |
| 4 | :: `test_stream_invalid_body_is_json_error_before_stream` | api |
| 5 | `api/tests/test_chat_tool_call_confirm.py` :: `test_confirm_runs_handler_with_caller_principal` | api |
| 5 | :: `test_confirm_rechecks_permission_from_token` (role lost -> 403, nothing runs) | api |
| 5 | :: `test_confirm_expired_409` | api |
| 5 | :: `test_confirm_other_users_call_409` | api |
| 5 | :: `test_confirm_already_decided_409` | api |
| 5 | :: `test_confirm_passes_reason_and_expected_version` | api |
| 5 | :: `test_cancel_marks_cancelled_and_nothing_runs` | api |
| 5 | :: `test_confirm_and_cancel_are_audited` | api |
| 6 | `api/tests/test_chat_tool_audit.py` :: `test_read_tool_writes_one_audit_row` | unit |
| 6 | :: `test_failed_tool_writes_error_outcome_row` | unit |
| 6 | :: `test_settings_tool_and_put_config_write_identical_config_change` | unit |
| 6 | :: `test_requeue_tool_and_router_write_identical_history` | unit |
| 7 | `api/tests/test_chat_permissions.py` :: `test_tool_outside_for_principal_never_offered` | unit |
| 7 | :: `test_model_emitted_forbidden_call_returns_forbidden_without_running` | unit |
| 7 | :: `test_get_chat_tools_reports_allowed_and_denied` | api |
| 8 | `api/tests/test_chat_core_tools.py` :: `test_settings_read_lists_entries` | unit |
| 8 | :: `test_propose_change_invalid_value_is_tool_error_no_pending` | unit |
| 8 | :: `test_propose_change_preview_before_after_version` | unit |
| 8 | :: `test_propose_change_confirm_version_conflict_409` | unit |
| 8 | :: `test_exceptions_list_returns_table_card` | unit |
| 8 | :: `test_exceptions_get_returns_state_card` | unit |
| 8 | :: `test_exceptions_requeue_preview_requires_lock` | unit |
| 8 | :: `test_exceptions_requeue_confirm_uses_requeue_service` | unit |
| 8 | :: `test_items_history_returns_table_card` | unit |
| 8 | :: `test_core_tool_permissions_and_flags` (CONFIG_READ, CONFIG_WRITE+mutating, ITEMS_READ, ITEMS_WORK+mutating) | unit |
| 9 | `api/tests/test_chat_prompts.py` :: `test_prompt_keys_include_assistant_and_matching` | unit |
| 9 | :: `test_every_prompt_says_tool_output_is_data` | unit |
| 9 | :: `test_matching_context_is_aggregates_only` (item context refused, no item fields) | unit |
| 9 | :: `test_assistant_is_default_prompt_key` | unit |
| 9 | `api/tests/test_llm_tool_turn.py` :: `test_anthropic_tool_turn_kwargs` (effort set, no thinking/tool_choice/sampling, eager input streaming, ephemeral cache) | unit |
| 9 | :: `test_refusal_checked_before_content` | unit |
| 9 | :: `test_metered_tool_turn_records_usage` | unit |
| 9 | :: `test_replay_client_scripted_tool_turn` | unit |
| 10 | `api/tests/test_chat_threads.py` :: `test_thread_persists_across_turns` | unit |
| 10 | :: `test_get_thread_owner_only_404` | api |
| 10 | :: `test_get_thread_returns_messages_tools_pending` | api |
| 10 | :: `test_message_content_never_logged` (caplog) | unit |
| 10 | :: `test_chat_tables_roundtrip_atp` (`@pytest.mark.atp`) | integration |
| 11 | `api/tests/test_chat_legacy_removed.py` :: `test_action_block_module_removed` | unit |
| 11 | :: `test_single_chat_stream_endpoint_without_allowed_actions` (OpenAPI) | unit |

Total: 70 tests (69 default, 1 `atp`). There are no existing chat tests in the tree to replace (api/tests holds only conftest and support), so AC11's "tests replaced" is satisfied by the two legacy tests above.

## 4 Data

Models (`api/src/cashapp/data/models/chat.py`; identity PKs, `UtcDateTime`, `JsonDoc`, lower-case table names that Oracle stores upper-case):

- `chat_thread` (`ChatThread`): `id` identity PK; `owner_subject` String(200) NN; `owner_name` String(200) NN; `prompt_key` String(20) NN; `context_kind` String(20) NN; `context_id` Integer NULL; `title` String(200) NN (first user message clipped, no model call); `created_at`, `updated_at` NN. Index `IX_CHAT_THREAD_OWNER_UPDATED (owner_subject, updated_at)`.
- `chat_message` (`ChatMessage`): `id` PK; `thread_id` FK -> chat_thread NN; `seq` Integer NN; `role` String(20) NN (`user` | `assistant` | `tool_results`); `content` JsonDoc NN (Anthropic content blocks verbatim, thinking blocks included); `display_text` String(4000) NULL (what `GET /chat/threads/{id}` shows); `created_at` NN. Unique `UQ_CHAT_MESSAGE_THREAD_SEQ (thread_id, seq)`.
- `chat_pending_tool_call` (`ChatPendingToolCall`): `id` PK; `call_id` String(64) NN unique `UQ_CHAT_PENDING_CALL_ID` (the model's tool_use id); `thread_id` FK NN; `tool` String(80) NN; `input` JsonDoc NN; `principal_subject` String(200) NN; `principal_name` String(200) NN; `preview` JsonDoc NN; `expires_at` NN; `status` String(20) NN (`PENDING|CONFIRMED|CANCELLED|EXPIRED|FAILED|SUPERSEDED`); `decided_at` NULL; `decided_by` String(200) NULL; `reason` String(1000) NULL; `created_at` NN. Index `IX_CHAT_PENDING_THREAD_STATUS (thread_id, status)`.
- `chat_tool_run` (`ChatToolRun`, the per-execution audit row): `id` PK; `at` NN; `thread_id` NULL; `call_id` String(64) NN; `tool` String(80) NN; `audit_label` String(120) NN; `actor_subject`, `actor_name` String(200) NN; `input_summary` String(400) NN (never full SQL/payload text); `outcome` String(20) NN (`OK|ERROR|FORBIDDEN|CANCELLED|EXPIRED|INVALID_INPUT|TIMEOUT`); `error_code` String(60) NULL; `duration_ms` Integer NN; `phase` String(20) NN (`run|confirm|cancel`). Index `IX_CHAT_TOOL_RUN_AT (at)`, `IX_CHAT_TOOL_RUN_ACTOR_AT (actor_subject, at)`.

Migration: ONE revision `api/alembic/versions/ui01_chat_agent_tool_registry.py`, `revision = "ui01_chat_agent_tool_registry"`, `down_revision = "s45_retention_purge"` (today's single head; split.md merge order puts this story first, so the next revisions chain after it; the merger re-points `down_revision` if the order changes). Creates the four tables with named PK/FK/UQ/IX constraints (≤ 30 chars, upper snake case); `downgrade()` drops them in reverse. DEV ATP only, by the db-sync step; the coder never runs it.

## 5 Config / env

- Env: none new. Uses the existing Anthropic settings (zero data retention org) and the ATP connection.
- New DB config keys (append-only `chat.*` block in `domain/config_keys.py`, group `chat`, admin-only write, validated at import):
  - `chat.confirm_ttl_seconds`: int, 60..3600, default 600.
  - `chat.max_tool_calls_per_turn`: int, 1..20, default 8.
- Read, not owned: `models.workhorse` (model id, effort, timeout_s). Constants (not config, recorded under Assumptions): `MAX_TOKENS = 16000`, `MAX_MESSAGE_CHARS = 4000`, `MAX_CONTEXT_CHARS = 24000`, `TOOL_RESULT_MAX_CHARS = 12000`, `DEFAULT_TOOL_TIMEOUT_S = 30`, `PING_SECONDS = 15`.

## 6 Risks and coder gates

- Preserved thinking (Haiku 5.5): assistant content is stored and replayed verbatim and history is append-only; a pending confirm's tool_results message is completed (never rewritten) at confirm/cancel/supersede, and the next user text is appended into an open `tool_results` message rather than editing earlier turns.
- Eager input streaming can yield truncated JSON: every tool input is validated against `input_model` before running; failure returns an `is_error` tool_result (`INVALID_TOOL_INPUT`). `max_tokens` / `refusal` stop reasons are checked before tools run.
- Anthropic tool names forbid dots: wire name is `name.replace(".", "__")`, mapped back only through the registry.
- Prompt injection through tool output or item data: outputs are wrapped as data (`<tool_output>`), the prompt says they are never instructions, and outputs pass through the one limiter.
- A DB session is never held across a model call: each step opens a short UoW.
- Requeue through chat needs the item dequeued (locked) by the same person, exactly as the router; the preview says so and refuses otherwise. Corrected extractions are not editable through chat.
- Breaking: the existing web llm-chat stops parsing frames until assistant-chat-redesign merges in this run; OpenAPI regenerated so its plan types against it.
- `domain/config_keys.py` is edited by several stories: append only, in the `chat.*` block.
- Chat message content is customer data in ATP: never logged (lengths and ids only); thread retention is not added here (follow-up for the retention purge, s45).
- Gates (coder runs only these, no tests): api `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`; web (generated files only) `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`.

## 7 Interfaces provided (pinned; consumers build against these in the same wave)

### 7.1 Registry (`cashapp/services/chat/tools/registry.py`), consumed by every tool story

```python
class ToolGroup(StrEnum):
    ENGINE = "engine"; LAB = "lab"; SETTINGS = "settings"; REPORTS = "reports"
    REVIEW = "review"; EXCEPTIONS = "exceptions"; FUSION_READS = "fusion_reads"; METRICS = "metrics"

class PreviewField(BaseModel):  label: str; value: str
class DiffLine(BaseModel):      op: Literal["-", "+", " "]; text: str   # matches DiffBlock lines
class ConfirmPreview(BaseModel):
    what: str                    # "Pause station apply"
    before: str
    after: str
    who: str                     # who_line(principal) -> "J. Stevenson · admin"
    reason_prompt: str = "Why are you making this change?"
    expected_version: int | None = None
    details: list[PreviewField] = []     # e.g. in-flight counts, rationale, replay summary
    diff: list[DiffLine] = []            # e.g. config diff

@dataclass(frozen=True, slots=True)
class Confirmation:  call_id: str; reason: str; expected_version: int | None  # body value, else preview's

Provider = Callable[[], object | Awaitable[object]]
class ToolServices:
    def __init__(self, providers: Mapping[type[Any], Provider]) -> None: ...
    async def get[T](self, kind: type[T]) -> T: ...   # raises ToolError("SERVICE_UNAVAILABLE", ..., 503)

@dataclass(frozen=True, slots=True)
class ToolContext:
    principal: Principal
    uow_factory: UowFactory
    clock: Clock
    services: ToolServices
    thread_id: int
    call_id: str
    confirmation: Confirmation | None             # None for read tools and for previews
    progress: Callable[[int, int], Awaitable[None]]   # emits tool_progress{call_id, done, total}

class ToolError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400) -> None: ...
    # e.g. CONFLICT (409), NOT_FOUND (404), LOCK_REQUIRED (409), INVALID_VALUE (422); message is safe to show

@dataclass(frozen=True, slots=True)
class ToolSpec[InT: BaseModel, OutT: BaseModel]:
    name: str                    # ^[a-z]+(\.[a-z_]+)+$ , e.g. "engine.pause"
    group: ToolGroup
    description: str             # prompt surface: the model reads it
    input_model: type[InT]       # never carries `reason`: the person types it at confirm
    output_model: type[OutT]     # dumped (JSON) back to the model as data, clipped by the shared limiter
    permission: Permission
    mutating: bool
    confirm_required: bool       # True whenever mutating (enforced in __post_init__)
    audit_label: str             # "Paused a station"
    handler: Callable[[ToolContext, InT], Awaitable[OutT]]
    preview: Callable[[ToolContext, InT], Awaitable[ConfirmPreview]] | None = None   # required when confirm_required
    card: Callable[[OutT], ResultCard | None] | None = None   # result_card on tool_finished
    summarize_input: Callable[[InT], str] | None = None       # audit + tool_started summary, ≤ 200 chars
    summarize_output: Callable[[OutT], str] | None = None     # tool_finished summary ("apply is running, 7 in flight")
    timeout_s: float = 30.0
    @property
    def wire_name(self) -> str: ...   # name.replace(".", "__")

class ToolRegistry:
    def register(self, spec: ToolSpec[Any, Any]) -> None        # duplicate name -> ToolRegistrationError
    def get(self, name: str) -> ToolSpec[Any, Any]               # UnknownTool
    def get_by_wire_name(self, wire: str) -> ToolSpec[Any, Any]
    def all(self) -> list[ToolSpec[Any, Any]]                    # sorted by name
    def for_principal(self, principal: Principal, groups: Collection[ToolGroup] | None = None) -> list[ToolSpec[Any, Any]]
    def anthropic_tools(self, principal: Principal, groups: Collection[ToolGroup] | None = None) -> list[dict[str, Any]]

def who_line(principal: Principal) -> str
```

Rules for tool modules: a module `cashapp/services/chat/tools/<feature>.py` exports `TOOLS: list[ToolSpec[Any, Any]]`; handlers open their own UoW (`async with ctx.uow_factory() as uow: ...; await uow.commit()`) and call the same service the router calls with `ctx.principal` and, for mutations, `ctx.confirmation.reason` / `ctx.confirmation.expected_version`; they raise `ToolError` for expected failures. The runner writes the `CHAT_TOOL_RUN` row; tools never write it. A service a tool needs is fetched with `await ctx.services.get(EngineService)`; its provider lives in a new API-layer module `cashapp/api/tool_providers/<feature>.py` exporting `PROVIDERS: dict[type, Provider]` (zero-arg, may be async; built from that story's own `get_*` dependency). Core providers here: `RuntimeConfig`, `LlmClients`, `ObjectStore`, `FusionClient`, `RequeueService`, `ExceptionsQueryService`.

### 7.2 Result cards (`cashapp/services/chat/tools/cards.py`, re-exported from `cashapp/api/schemas/chat.py`)

```python
Tone = Literal["ok", "accent", "warn", "err", "locked", "muted"]
class CardStat(BaseModel):   label: str; value: str
class CardStatus(BaseModel): label: str; tone: Tone
class StateCard(BaseModel):
    kind: Literal["state_card"] = "state_card"
    title: str; status: CardStatus; stats: list[CardStat] = []; history_id: str | None = None
class ReplayCurrency(BaseModel): currency: str; newly_matched: MoneyStr; newly_unmatched: MoneyStr; items: int
class ReplayCard(BaseModel):
    kind: Literal["replay_card"] = "replay_card"
    candidate_id: str; replay_id: str; status: Literal["RUNNING", "DONE", "FAILED", "STALE"]
    changed: int; newly_matched: int; newly_failed: int; newly_ambiguous: int
    currencies: list[ReplayCurrency] = []; lab_href: str     # "/lab?candidate=p_0001&replay=rp_0001"
class ExportCard(BaseModel):
    kind: Literal["export_card"] = "export_card"
    filename: str; size_bytes: int; media_type: Literal["text/html"] = "text/html"
    self_contained: bool = True; preview_href: str; download_href: str
class TableColumn(BaseModel): key: str; label: str; numeric: bool = False
class TableCard(BaseModel):
    kind: Literal["table_card"] = "table_card"
    title: str; columns: list[TableColumn]; rows: list[dict[str, str | int | None]]
    total: int | None = None; truncated: bool = False
ResultCard = Annotated[StateCard | ReplayCard | ExportCard | TableCard, Field(discriminator="kind")]
```

### 7.3 HTTP + SSE (`cashapp/api/routers/chat.py`, schemas in `cashapp/api/schemas/chat.py`), consumed by assistant-chat-redesign

- `POST /chat/stream` (CHAT_USE), body `ChatStreamIn{thread_id: int | None = None, system_prompt_key: "assistant"|"item"|"flow"|"matching" = "assistant", context: {kind: "none"|"item"|"flow", id: str | None} = {kind:"none"}, message: str (1..4000), tool_groups: list[ToolGroup] | None = None}` (only narrows the principal's tools; `item` key needs an item context; `matching` refuses an item context; a follow-up turn must keep the thread's key, else 422 `chat_prompt_mismatch`). Pre-stream failures are JSON in the single error shape (403, 404 `thread_not_found` / `item_not_found`, 422).
- Response `text/event-stream`, headers `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`; comment heartbeat every 15 s; every frame has a monotonic `id:`, `event: <name>`, `data: <json>`:
  - `text_delta` `{text: str}`
  - `tool_started` `{call_id: str, tool: str, group: ToolGroup, summary: str, mutating: bool}`
  - `tool_progress` `{call_id: str, done: int, total: int}`
  - `tool_finished` `{call_id: str, tool: str, duration_ms: int, ok: bool, summary: str | null, result_card: ResultCard | null, error: {code: str, message: str} | null}`
  - `confirm_required` `{call_id: str, tool: str, preview: ConfirmPreview, expires_at: datetime}` (the tool row shows "waiting for your confirmation"; the turn then ends with `done`)
  - `error` `{code: "FORBIDDEN"|"UNKNOWN_TOOL"|"INVALID_TOOL_INPUT"|"TOOL_LIMIT"|"TIMEOUT"|"LLM_UNAVAILABLE"|"REFUSED"|"INTERNAL_ERROR", message: str, call_id: str | null, fatal: bool, thread_id: int}`; `fatal: true` is the last frame (no `done`)
  - `done` `{thread_id: int, message_id: int, stop: "end_turn"|"awaiting_confirmation"|"tool_limit", usage: {model_id: str, latency_ms: int, input_tokens: int | null, output_tokens: int | null}}`
- `POST /chat/tool-calls/{call_id}/confirm` (CHAT_USE + the tool's own permission re-checked from the caller's token), body `{reason: str (1..1000), expected_version: int | null}`. Pre-stream refusals JSON: 403 `forbidden`; 409 `tool_call_expired` | `tool_call_not_yours` | `tool_call_decided`; 404 `tool_call_not_found`. Success: the same SSE stream as above starting with `tool_started` → `tool_progress*` → `tool_finished`, then the resumed agent turn (`text_delta`… `done`). A handler conflict is `tool_finished{ok:false, error:{code:"CONFLICT"}}` ("… Nothing changed.").
- `POST /chat/tool-calls/{call_id}/cancel` (CHAT_USE) → `200 {call_id: str, status: "CANCELLED"}`; same 404/409 refusals; nothing runs.
- `GET /chat/tools` (CHAT_USE) → `list[ToolGroupOut{group: ToolGroup, allowed: bool (any tool allowed), tools: list[{name, description, mutating, allowed}]}]`, every registered group listed, sorted by group.
- `GET /chat/threads/{thread_id}` (CHAT_USE, owner only, else 404) → `ChatThreadOut{id, prompt_key, context: {kind, id}, title, created_at, updated_at, messages: list[{id, seq, role: "user"|"assistant", text: str, tools: list[{call_id, tool, group, summary, ok, duration_ms, status: "done"|"failed"|"waiting"|"cancelled"|"expired", result_card: ResultCard | null}], created_at}], pending: {call_id, tool, preview, expires_at} | null}`. The dock links to `/assistant?thread=<id>`.
- Web proxy note for assistant-chat-redesign: `/chat/stream` is already in `web/lib/api/stream-paths.ts`; the confirm stream path `/chat/tool-calls/{id}/confirm` must be added there by that story (POST + fetch reader, SSE-27).

### 7.4 Prompt keys (`cashapp/services/chat/prompts.py`)

`PromptKey = ITEM "item" | FLOW "flow" | ASSISTANT "assistant" | MATCHING "matching"`. matching-lab-replay-api's tools are offered on MATCHING threads (and ASSISTANT) through `tool_groups=["lab"]` from the Lab page.

### 7.5 Interfaces per consumer

| Consumer | Contract | plannable |
|---|---|---|
| engine-control-api | 7.1 (`ToolSpec`, `ToolContext`, `ConfirmPreview`, `TOOLS` discovery, `ToolServices` + `api/tool_providers/engine.py`), `StateCard` | true |
| fusion-mcp-transport | 7.1 (read tools, `summarize_input` keeps SQL out of audit: hash only), `TableCard`, provider module for its client | true |
| live-progress-dashboard | 7.1 (`metrics.read`, group METRICS), `StateCard`/`TableCard`, provider for `MetricsService` | true |
| failed-receipt-review | 7.1 (`review.submit` mutating + preview, `review.queue`), `StateCard`, provider for `UploadService` | true |
| html-progress-reports | 7.1 (`reports.export`, not mutating), `ExportCard` | true |
| matching-lab-replay-api | 7.1 (`ctx.progress` for `lab.replay`, `lab.promote` preview with `diff` + `details` + `expected_version`), `ReplayCard`, `PromptKey.MATCHING` | true |
| assistant-chat-redesign | 7.2 + 7.3 (all routes, request body, SSE event names and payloads, heartbeat, thread shape) | true |

## Assumptions

- A generic per-tool audit writer does not exist today (`record_history` is item-scoped, `ConfigAudit` is key-scoped), so "through the existing audit writer" is read as: domain audit goes through the existing writers (via the same services), and the per-execution chat audit is one new writer (`ChatToolAudit`) over a fourth table `CHAT_TOOL_RUN` in the same single migration.
- Result-card models are defined in the business layer (`services/chat/tools/cards.py`) and re-exported from `api/schemas/chat.py` (AC4's path), because tool modules build cards and services must not import the API layer.
- The SSE error frame is named `error` as the AC and assistant-chat-redesign's story pin, not `stream-error` (SSE-14): the chat is consumed with POST + a fetch reader (SSE-27), where `EventSource`'s own `error` event cannot collide.
- The client no longer sends the conversation: the server owns threads (`thread_id`), which is what lets `/assistant?thread=<id>` reopen it and keeps thinking blocks verbatim.
- One confirm per assistant message: a second mutating call in the same message gets an `is_error` tool_result asking the model to propose it after the first is decided. An open pending call is superseded (status SUPERSEDED, tool_result "superseded") when the person sends a new message.
- Confirm/cancel refusals for expired, another user's and already-decided calls are all 409 with distinct codes (AC5); an unknown call id is 404.
- `settings.propose_change` writes the reason exactly as typed (so config history is identical to `PUT /config/{key}`); the chat link lives in `CHAT_TOOL_RUN.call_id`. Operators are simply not offered it (no CONFIG_WRITE).
- The chat makes no non-streaming model call (thread title = first message clipped), so AC9's structured-output rule binds tool modules that add one: they use `LlmClients.workhorse.parse`.
- Tool-result clip, max tokens and tool timeout are constants, not config keys; only the two keys in the story are added.
