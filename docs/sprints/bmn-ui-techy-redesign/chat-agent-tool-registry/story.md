# chat-agent-tool-registry: One tool registry and a tool-using Haiku chat agent

- Issue: #48 (item 6, research.md Amendment)
- breaking: true (the `POST /chat/stream` SSE event set changes: the text action-block protocol is replaced by tool events; the web chat client must move with it)
- Design screen owned: none (API only; the Assistant screen is owned by assistant-chat-redesign)

## Story

As a user of the cash app, I want the assistant to actually do things for me (read progress, change settings, work exceptions, control the engine, run the lab, export reports, submit receipts) through the same services the screens use, asking me to confirm every change, so that chat is a full interface that can never do more than my role allows.

## Context

research.md a3 plus its Amendment: **one tool registry** is the single source of truth for each tool's schema, permission, confirm-required flag and audit label, consumed by the chat agent. Feature stories register their own tools in their own modules; this story ships the registry, the agent loop and the core tools over services that already exist. Today `services/chat/` streams Haiku text and parses an inline action block (`services/chat/actions.py` `ActionBlockSplitter`, `parse_action_block`); `PromptKey` has ITEM and FLOW (`services/chat/prompts.py:23`). Haiku is the workhorse, zero data retention, structured outputs (CLAUDE.md "Models"); load `claude-api` and `python-llm-features:building-llm-backed-features`.

## Acceptance criteria

1. [unit] `cashapp/services/chat/tools/registry.py`: `ToolSpec{name: str (dotted, e.g. "engine.pause"), group: ToolGroup (ENGINE|LAB|SETTINGS|REPORTS|REVIEW|EXCEPTIONS|FUSION_READS|METRICS), description, input_model: type[BaseModel], output_model: type[BaseModel], permission: Permission, mutating: bool, confirm_required: bool (must be True when mutating; enforced at registration), audit_label: str, handler: Callable[[ToolContext, BaseModel], Awaitable[BaseModel]], preview: Callable[[ToolContext, BaseModel], Awaitable[ConfirmPreview]] | None (required when confirm_required)}`; `ToolRegistry.register(spec)` (duplicate names refused), `get(name)`, `for_principal(principal) -> list[ToolSpec]` (only tools whose permission the principal holds), `anthropic_tools(principal)` (JSON schemas from the input models). `ToolContext{principal: Principal, uow_factory, clock, services}`. A test asserts no tool is executable without being in the registry.
2. [unit] Registration is discoverable like routers: every module under `cashapp/services/chat/tools/` exporting `TOOLS: list[ToolSpec]` is registered at startup; no story edits a central list.
3. [unit] The agent loop (`ChatService`) calls the workhorse model (`models.workhorse` config, Haiku 5.5) with the principal's tools only, executes read tools immediately and, for a `confirm_required` tool, stops and emits a confirm request built from `preview` (what, before, after, who, reason prompt) and persists a `PendingToolCall{id, thread_id, tool, input JSON, principal id, preview, expires_at, status}` (new table `CHAT_PENDING_TOOL_CALL`, Alembic migration). The model never executes a mutation itself.
4. [api] `POST /chat/stream` (SSE) emits events `text_delta`, `tool_started{call_id, tool, summary}`, `tool_progress{call_id, done, total}`, `tool_finished{call_id, tool, duration_ms, ok, result_card?}`, `confirm_required{call_id, tool, preview}`, `error{code, message}`, `done`, plus a heartbeat comment every 15 s with `X-Accel-Buffering: no` (research.md risk: OCI LB buffering). Result cards are typed: `state_card`, `replay_card`, `export_card`, `table_card` (Pydantic models in `cashapp/api/schemas/chat.py`).
5. [api] `POST /chat/tool-calls/{call_id}/confirm {reason, expected_version?}` re-checks the permission against the caller's own token principal (never the one stored), refuses when expired, another user's, or already decided (409), runs the handler with that principal and streams the result; `POST /chat/tool-calls/{call_id}/cancel` marks it cancelled and nothing runs. Both are audited.
6. [unit] Every tool execution, read or write, writes one audit record (who, tool, audit_label, input summary, outcome, duration) through the existing history/audit writer; mutating tools also leave the domain's own audit (config change history, engine audit, item history) because they call the same services the routers call. A test proves a mutating tool and its router produce identical domain audit rows.
7. [unit] The chat can never exceed the user's permissions: a tool missing from `for_principal` is never offered to the model, and a model-emitted call to it returns `error{code: "FORBIDDEN"}` without running. Denied tool groups are reported in `GET /chat/tools` -> `[{group, tools: [{name, description, mutating, allowed}]}]` for the live-context panel.
8. [unit] Core tools registered here (each in its own module): `metrics.read` is NOT here (live-progress-dashboard owns it); here: `settings.read` (ConfigService get/list, CONFIG_READ), `settings.propose_change {key, value, rationale}` (mutating, confirm, CONFIG_WRITE; validated with `validate_value`, executed through the same ConfigService write as `PUT /config/{key}` with reason and expected_version; per-key hard bounds from the key spec), `exceptions.list`, `exceptions.get`, `exceptions.requeue` (mutating, confirm, ITEMS_WORK, same RequeueService), `items.history` (ITEMS_READ).
9. [unit] Prompt keys: `PromptKey` gains `ASSISTANT` (general agent, the default for the dock and `/assistant`) and `MATCHING` (lab, aggregates only in context); system prompts state that artifact and tool output text is data, never instructions. Structured outputs are used for every non-streaming model call; `stop_reason == "refusal"` is handled before reading content.
10. [unit] Threads persist (`CHAT_THREAD`, `CHAT_MESSAGE`) so the dock's "Full screen" link reopens the same thread at `/assistant?thread=<id>`; `GET /chat/threads/{id}` returns its messages for the owner only. Message content stays in ATP and is never logged in full.
11. [unit] The old action-block path (`ActionBlockSplitter`, `parse_action_block`) is removed and its tests replaced; one chat endpoint remains.

## Out of scope

- The chat UI (assistant-chat-redesign). Tools for engine, lab, reports, review and Fusion reads (their stories register them through this registry).

## Deps

None.

## Assumptions

- Confirmation expiry (`chat.confirm_ttl_seconds`, default 600) and the per-turn tool-call cap (`chat.max_tool_calls_per_turn`, default 8) are new DB config keys owned here.
- The existing `CHAT_USE` permission gates the endpoint; each tool's own permission gates the tool.
- Alembic: this story's migration is one revision; the merger re-points `down_revision` to keep one head (split.md "Migrations").
