# s22-ui-shared-llm-chat: plan

Issue #22, wave 5. Builds the one LLM chat in the app: `POST /chat/stream` (Haiku via the workhorse `LlmClient.stream_text`, SSE) and `<LlmChat>` in `web/components/common/llm-chat.tsx`. s19 puts it on `/items/[id]` and `/flow`.

## Standards followed

- **CLAUDE.md**:
  - non-negotiable 7 (one chat component, one endpoint, one prompt module);
  - layered architecture: the router only validates and streams; the service gets the `Principal` and plain arguments; queries live only in repositories;
  - Workhorse = `claude-haiku-5-5`, zero data retention;
  - prompts and model output are never logged;
  - no transcript persistence.
- **python-web-app**: routes → services → repositories; `Annotated` dependency aliases; external SDK behind the `LlmClient` interface.
- **python-llm-features**:
  - one prompt module of shared constants (the action-block markers, the "Check before acting" wording) that both the prompt and the parser import;
  - one context limiter (`fit_context`) for every prompt path;
  - model id, effort and timeout come from typed config (`ModelsConfig.workhorse`);
  - no live-model calls in default tests (`ReplayLlmClient`);
  - no over-claiming fields: the `done.usage` token fields are nullable, not invented.
- **claude-api**: Haiku 5.5 effort defaults to `medium`, so chat sets `effort` explicitly from `ModelsConfig.workhorse.effort`, falling back to `"low"`. No prefill. No `temperature`. Refusal surfaces as `LlmError(LLM_REFUSAL)` from s08.
- **nextjs-fullstack-standards / BMN `nextjs.md`**:
  - non-negotiables 8 and 14;
  - SSE-6 (auth and validation before the stream; 401/403/404/422 as plain JSON);
  - SSE-10, SSE-13 (sse-starlette ping, 15 s);
  - SSE-14 (failures after the stream starts go out as `stream-error`, never `error`);
  - SSE-15/17 (client abort cancels the generator and closes the LLM stream);
  - SSE-23/27 (fetch + reader POST through s31's `useEventStream`);
  - SSE-25 (Zod-validated payloads);
  - TEST-1, TEST-2, TEST-9, TEST-14, TEST-25 (handler errors in state), TEST-35 (no content in logs);
  - `"use client"` only on the chat leaf; shadcn primitives from the CLI; named exports; strict TS with `noUncheckedIndexedAccess`.
- **design.md §7**: layout, copy, states and placement. §9: `llm-chat` is the single shared component.

## Files to touch

All files are new and owned by s22 (file-disjoint), except the one marked otherwise.

### API (`api/src/cashapp/…`)

| Path | Content |
|---|---|
| `services/chat/__init__.py` | re-exports `ChatService`, `ChatTurnIn`, `ChatContextRef`, `ChatEvent*`, `PromptKey` |
| `services/chat/prompts.py` | `PromptKey` (`item`, `flow`); `ChatPrompt` (`key`, `version`, `system`); `PROMPTS`; constants `ACTION_BLOCK_OPEN = "<<<actions"`, `ACTION_BLOCK_CLOSE = ">>>"`, `CHECK_BEFORE_ACTING`; `render_system(key, context_json, allowed_actions) -> str` |
| `services/chat/context.py` | `ChatContextBuilder`: `item_context(uow, item_id) -> dict`, `flow_context(uow, now) -> dict`; `fit_context(doc, max_chars)`; `scrub_extraction(final)`, which drops every `source.quote` and keeps no artifact text |
| `services/chat/actions.py` | `ActionBlockSplitter` (streaming hold-back of the trailing block); `parse_action_block(raw, allowed) -> list[ProposedAction]` |
| `services/chat/service.py` | `ChatService.stream(...)`, an async iterator of `ChatEvent`; limits (`MAX_TURNS = 20`, `MAX_MESSAGE_CHARS = 4000`, `MAX_CONTEXT_CHARS = 24000`, `MAX_TOKENS = 2048`) |
| `data/repositories/chat_context.py` | `ChatContextRepository(BaseRepository[WorkItemHistory])` with `failures_by_code_since(since) -> list[tuple[ErrorCode, int]]` (history rows with `error_code` not null and `at >= since`, grouped by code, counting distinct items) |
| `api/schemas/chat.py` | `ChatStreamIn`, `ChatContextIn`, `ChatMessageIn`, and the event payload models `TokenData`, `ActionData`, `DoneData`, `UsageData`, `StreamErrorData` (these appear in OpenAPI through `responses` on the route, so `schema.d.ts` carries them) |
| `api/routers/chat.py` | `router`: `POST /chat/stream` (`chat:use`), auto-discovered |
| `api/llm_deps.py` | `get_llm_clients()` (process-cached `build_llm_clients(get_settings())`) and `LlmClientsDep`. **Pinned for later API callers.** Skip it if a merged story already ships an equivalent API dependency, and reuse that one. |

### Web (`web/…`)

| Path | Content |
|---|---|
| `components/common/llm-chat.tsx` | `"use client"`: `LlmChat`, the only entry point |
| `components/common/llm-chat/chat-schemas.ts` | Zod: `chatEventSchemas` (`token`, `action`, `done`, `stream-error`); the types `ChatContextRef`, `ChatActionSpec`, `ChatActionHandler`, `ChatMessage`; `CHAT_STREAM_PATH = "/chat/stream"` |
| `components/common/llm-chat/chat-reducer.ts` | pure `chatReducer(state, action)`. Phases: `idle`, `streaming`, `done`, `error`, `disconnected`, `stopped` |
| `components/common/llm-chat/use-chat.ts` | `"use client"`: `useChat({context, systemPromptKey, actions})`, which wraps s31's `useEventStream(CHAT_STREAM_PATH, {body, schema, onEvent, onStreamError, enabled, reconnect: false})` |
| `components/common/llm-chat/message-list.tsx` | messages in a `ScrollArea`; user messages right-aligned in a muted bubble; assistant messages left-aligned plain; a streaming caret |
| `components/common/llm-chat/assistant-markdown.tsx` | `react-markdown` + `rehype-sanitize` (`defaultSchema` with `img` removed, links forced to `rel="noopener noreferrer" target="_blank"`). No `rehype-raw`, no `dangerouslySetInnerHTML`. |
| `components/common/llm-chat/composer.tsx` | `Textarea` + Send; Stop while streaming; Enter sends, Shift+Enter adds a newline |
| `components/common/llm-chat/suggestions.tsx` | the suggestion buttons for the empty state |
| `components/common/llm-chat/action-chips.tsx` | a chip per proposed action, plus an `AlertDialog` confirm that calls `onAction` only on confirm, then shows the result through a toast (`sonner`) |
| `components/common/llm-chat/chat-status.tsx` | the error banner ("The assistant didn't answer (timeout). Try again", with retry) and the disconnected banner (with retry) |
| `components/common/llm-chat/defaults.ts` | `DEFAULT_SUGGESTIONS: Record<PromptKey, string[]>` (item: "Why is this stuck?", "Which receipt fits best?"; flow: "What's driving failures today?"); `FOOTER_NOTE = "Answers by Claude Haiku 5.5. Check before acting."` |
| `components/ui/textarea.tsx`, `components/ui/scroll-area.tsx` | `npx shadcn@latest add textarea scroll-area`, CLI output only |
| `lib/api/openapi.json`, `lib/api/schema.d.ts` | regenerated with `npm run api:sync` (s31 rule: regenerate, never hand-merge) |

Not touched:
- `main.py`
- lockfiles
- `stream-paths.ts`: s31 already allow-lists `/chat/stream`
- s19 pages (s19 renders `<LlmChat>`)
- Alembic

## Design

### API: `POST /chat/stream`

1. **Before the stream starts** (SSE-6), the dependencies and validation run:
   - `require_permission(Permission.CHAT_USE)` (403);
   - the body goes through `ChatStreamIn` (422);
   - `system_prompt_key` must equal `context.kind`, otherwise 422 `chat_prompt_mismatch`;
   - `kind="item"` requires `id` matching `^(WI-)?\d+$`, otherwise 422;
   - the last message must have role `user`;
   - at most `MAX_TURNS` messages, and each `content` is 1..`MAX_MESSAGE_CHARS`;
   - `allowed_actions` has at most 10 ids, each matching `^[a-z][a-z0-9_]{0,39}$`.

   The context is built in a short read-only UoW before the response starts. An unknown item gives 404 `item_not_found` in the single error shape.
2. **The router returns** `EventSourceResponse(gen(), ping=15)`. It converts each `ChatEvent` to `ServerSentEvent(event=…, data=model.model_dump_json(), id=str(n))`. No DB session is held while streaming.
3. **`ChatService.stream`**:
   - takes `cfg = await runtime.snapshot()` and `role = cfg.models().workhorse`;
   - selects `client = llm.workhorse.with_model(role.model_id)`;
   - builds `LlmRequest(system=render_system(...), parts=(TextPart(last_user),), history=prior turns as ChatTurn, max_tokens=MAX_TOKENS, timeout_s=role.timeout_s, effort=role.effort or "low", purpose="chat.workhorse", work_item_id=item id | None, prompt_version=prompt.version)`;
   - wraps the iteration in `asyncio.timeout(role.timeout_s)`;
   - feeds each delta through `ActionBlockSplitter.feed()` and yields `token{text}` for the safe text. The splitter holds back any suffix that could begin `ACTION_BLOCK_OPEN`, and everything after it.

   When the stream ends:
   - `splitter.finish()` returns the remaining safe text plus the raw block.
   - `parse_action_block` reads it as JSON `[{id, label?, args?}]`, validated by a `TypeAdapter`. It keeps only ids in `allowed_actions`, dedupes, caps at 3, truncates `label` to 80 characters (default: the id), and requires `args` to be a flat object of str/int/bool/null.
   - An `action` event is yielded for each kept action, then `done{usage}`.
   - An unparsable block is dropped with a warning that logs only its length.
4. **Errors after the stream starts** go out as `event: stream-error` with data `{code, message}`, and then the stream closes:

   | Cause | `code` | `message` |
   |---|---|---|
   | `TimeoutError` | `timeout` | "The assistant didn't answer (timeout)." |
   | `LlmError` LLM_TRANSIENT | `llm_unavailable` | — |
   | `LlmError` LLM_REFUSAL | `refused` | — |
   | anything else | `internal_error` | — |

   Only the code and the exception name are logged, never content.
5. **Client disconnect.** sse-starlette cancels the generator, and its `finally` calls `aclose()` on the `stream_text` iterator, so the Anthropic stream closes (SSE-15/17).
6. **Context** is a JSON document from `ChatContextBuilder`.
   - **Item:**
     - `{wi: "WI-<id>", stage, state, attempts, last_error_code, last_error_detail` (keys only, values ≤200 characters)`, escalation_summary, payer_name, currency, payment_amount, payment_date, payment_status, info_flags, lock: {owner_name}|null}`;
     - `extraction`: from `AdjudicationRepository.latest_for(id)`, `result().final` with `scrub_extraction` applied, plus `confidence`, `missing_reader` and `disagreements`. It is `{purged: true}` on `AdjudicationPurged`.
     - `lines`: s15's line results for the item;
     - `candidate_receipts`: s13's candidates and reservation, listing receipt number, date, amount, remaining, customer and score;
     - `recent_history`: the last 10 entries `{at, action, to_stage, error_code, reasoning}`.
   - **Flow:**
     - `{as_of, stages: collect_queue_stats(uow)` (s29) as `[{stage, state, count, oldest_age_s}]`;
     - `failures_today: ChatContextRepository.failures_by_code_since(start of today UTC)}`.

   Money is serialised as strings. `fit_context` serialises with sorted keys and trims `recent_history`, then `lines`, then `candidate_receipts` (with a `truncated: true` marker) until the result is ≤ `MAX_CONTEXT_CHARS`. Character count is a proxy here; the token cost is bounded by these caps.

   The context goes into the system prompt between `<context>` tags, with the instruction to treat it as data. The system prompt also lists `allowed_actions`, the action-block format, and the rule to propose actions only from that list and never claim to have run them.
7. **Usage.** `done.usage = {model_id, latency_ms, input_tokens: null, output_tokens: null}`. s08's `stream_text` yields only text. Token and cost rows are written by s36's `MeteredLlmClient` around the same call.

### Web: `<LlmChat>`

- **Props** are pinned below. `suggestions` defaults from `DEFAULT_SUGGESTIONS[systemPromptKey]`.
- **`variant="panel"`** fills its container: a flex column with the list, composer and footer. **`variant="sheet"`** wraps the same body in a shadcn `Sheet` (side `right`, bottom-anchored, `sm:max-w-md`), with a trigger button labelled "Ask". s19 renders only `<LlmChat variant="sheet" …/>`. `open` and `onOpenChange` are optional for controlled use.
- **`useChat` state** (reducer):
  - `send(text)` appends the user message and an empty assistant draft, then sets `request = {body, nonce}`. The hook is `enabled` only while the phase is `streaming`.
  - The body is `{context, system_prompt_key, messages: completed turns + the new user turn, allowed_actions: actions.map(a => a.id)}`.
  - `token` appends to the draft.
  - `action` adds a proposal to the draft. It is ignored if the id is not in `actions`, which is defence in depth.
  - `done` finalises the draft and sets `enabled=false`.
  - `stream-error` (through `onStreamError`, Zod-parsed) sets phase `error`; a `timeout` code uses the design's exact copy.
  - If `status === "disconnected"` arrives while the phase is still `streaming` and no `done` or `stream-error` was seen, the phase becomes `disconnected`.
  - **Stop** sets `enabled=false`, which aborts the fetch through s31's connection key. The phase becomes `stopped` and the partial text is kept, marked "Stopped".
  - **Retry** (error or disconnected) drops the failed draft and calls the hook's `retry()`, which re-posts the same body.
  - Composer and suggestions are disabled while streaming.
- **Action chip.** The chip text is the prop `label`; the event `label` is the model's reason, shown as secondary text. A click opens an `AlertDialog` with `confirm ?? "Run \"<label>\"?"`. Only the confirm button calls `await onAction(id, args)`. The returned `Result` is shown as a toast: success, or the `ApiError` message with its request id (TEST-25: errors are kept in state, never thrown). No action ever runs automatically.
- **Footer:** `FOOTER_NOTE`. Accessibility: the list is `role="log"` with `aria-live="polite"`; the Stop and Retry buttons have labels.
- **No secrets or tokens:**
  - the component imports only `@/lib/api/use-event-stream`, `@/lib/api/errors`, `@/lib/result` and `@/components/ui/*`;
  - no `fetch`, no `process.env`, no `lib/api/client|actions` (s31's ESLint rule also enforces this);
  - all traffic goes to `/api/stream/chat/stream` through s31's proxy, which attaches the bearer server-side.

## Interfaces provided (pinned)

```ts
// web/components/common/llm-chat.tsx  ("use client")
export type PromptKey = "item" | "flow";
export type ChatContextRef = { kind: PromptKey; id?: string };            // id = "WI-20481" or "20481" for kind "item"
export type ChatActionSpec = { id: string; label: string; confirm?: string };
export type ChatActionHandler = (id: string, args: Readonly<Record<string, string | number | boolean | null>>)
  => Promise<Result<unknown, ApiError>>;                                    // a server action passed from a Server Component
export type LlmChatProps = {
  context: ChatContextRef;
  systemPromptKey: PromptKey;
  actions?: readonly ChatActionSpec[];   // default []
  onAction?: ChatActionHandler;          // required when actions is non-empty (dev warning otherwise; chips disabled)
  variant: "panel" | "sheet";
  suggestions?: readonly string[];       // default DEFAULT_SUGGESTIONS[systemPromptKey]
  open?: boolean; onOpenChange?: (open: boolean) => void;   // sheet only, optional control
  className?: string;
};
export function LlmChat(props: LlmChatProps): React.JSX.Element;

// web/components/common/llm-chat/chat-schemas.ts
export const CHAT_STREAM_PATH: "/chat/stream";
export const tokenDataSchema:   z.ZodType<{ text: string }>;
export const actionDataSchema:  z.ZodType<{ id: string; label: string; args: Record<string, string | number | boolean | null> }>;
export const doneDataSchema:    z.ZodType<{ usage: { model_id: string; latency_ms: number; input_tokens: number | null; output_tokens: number | null } }>;
export const streamErrorSchema: z.ZodType<{ code: "timeout" | "llm_unavailable" | "refused" | "internal_error" | string; message: string }>;
```

```text
POST /chat/stream   permission chat:use   (web: POST /api/stream/chat/stream via s31 proxy)
body  { context: {kind: "item"|"flow", id?: string}, system_prompt_key: "item"|"flow",
        messages: [{role: "user"|"assistant", content: string}] (1..20, last = user, content 1..4000),
        allowed_actions: string[] (0..10, ^[a-z][a-z0-9_]{0,39}$) }
pre-stream errors (JSON, single shape): 401, 403 forbidden, 404 item_not_found, 422 validation_error | chat_prompt_mismatch
SSE   retry/ping comments; each event has id: n
      event: token        data {"text": str}
      event: action       data {"id": str (∈ allowed_actions), "label": str (≤80), "args": {str: str|int|bool|null}}
      event: done         data {"usage": {"model_id": str, "latency_ms": int, "input_tokens": int|null, "output_tokens": int|null}}
      event: stream-error data {"code": "timeout"|"llm_unavailable"|"refused"|"internal_error", "message": str}
```

```python
# cashapp/services/chat/prompts.py
class PromptKey(StrEnum): ITEM = "item"; FLOW = "flow"
@dataclass(frozen=True, slots=True)
class ChatPrompt: key: PromptKey; version: str; system: str
PROMPTS: Mapping[PromptKey, ChatPrompt]
ACTION_BLOCK_OPEN: Final = "<<<actions"; ACTION_BLOCK_CLOSE: Final = ">>>"
def render_system(key: PromptKey, context_json: str, allowed_actions: Sequence[str]) -> str

# cashapp/services/chat/service.py
@dataclass(frozen=True, slots=True)
class ChatContextRef: kind: PromptKey; item_id: int | None
@dataclass(frozen=True, slots=True)
class ChatTurnIn: role: Literal["user", "assistant"]; content: str
@dataclass(frozen=True, slots=True)
class TokenEvent: text: str
@dataclass(frozen=True, slots=True)
class ActionEvent: id: str; label: str; args: Mapping[str, str | int | bool | None]
@dataclass(frozen=True, slots=True)
class DoneEvent: model_id: str; latency_ms: int; input_tokens: int | None = None; output_tokens: int | None = None
@dataclass(frozen=True, slots=True)
class StreamErrorEvent: code: str; message: str
ChatEvent = TokenEvent | ActionEvent | DoneEvent | StreamErrorEvent
class ChatService:
    def __init__(self, *, uow_factory: UowFactory, llm: LlmClients, runtime: RuntimeConfig, clock: Clock | None = None) -> None
    async def prepare(self, principal: Principal, ref: ChatContextRef, key: PromptKey,
                      turns: Sequence[ChatTurnIn], allowed_actions: Sequence[str]) -> PreparedChat
        # raises ChatNotFound (→404), ChatInvalid (→422); builds context in a short read-only UoW
    def stream(self, prepared: PreparedChat) -> AsyncIterator[ChatEvent]   # never raises after start; ends with Done or StreamError

# cashapp/services/chat/actions.py
class ActionBlockSplitter:
    def feed(self, delta: str) -> str          # safe-to-emit text
    def finish(self) -> tuple[str, str | None] # (remaining safe text, raw block or None)
def parse_action_block(raw: str | None, allowed: Collection[str], *, limit: int = 3) -> list[ActionEvent]

# cashapp/data/repositories/chat_context.py
class ChatContextRepository(BaseRepository[WorkItemHistory]):
    async def failures_by_code_since(self, since: datetime) -> list[tuple[ErrorCode, int]]

# cashapp/api/llm_deps.py
def get_llm_clients() -> LlmClients            # lru_cache; build_llm_clients(get_settings())
LlmClientsDep = Annotated[LlmClients, Depends(get_llm_clients)]
```

Consumers:
- s19 renders `<LlmChat context={{kind:"item", id}} systemPromptKey="item" actions=[…] onAction={serverAction} variant="panel" />` and `<LlmChat context={{kind:"flow"}} systemPromptKey="flow" variant="sheet" />`.
- Any later API story that needs LLM clients in the API process uses `LlmClientsDep`.

## Migrations

None.

## Test plan (written and run in step 5)

- **API tests** use s02's `uow` (SQLite), s28's `make_runtime_config`, s08's `scripted_llm`/`ReplayLlmClient` with `ScriptedStep(text_chunks=…)`, `timeout()` and `transient()`, and s04's principal fixtures.
- **Web unit tests** use jsdom with s31's `sse-mock` (`mockStream`, `streamRequests`).
- **E2E** specs go in `web/e2e/` (s01's `testDir`) and run against the production build. They drive s19's pages with s19/s04's signed-in session and fake-API harness, and use `page.route("**/api/stream/chat/stream", …)` to fulfil the SSE body in the browser. They run after s19 merges (see the story's assumption).

| AC | Test | Asserts |
|---|---|---|
| 1 | `web/tests/unit/llm-chat/single-chat.test.ts` › `only llm-chat modules reference /chat/stream` | glob `web/{app,components,lib,hooks}/**/*.{ts,tsx}`: `"/chat/stream"` appears only in `components/common/llm-chat/**` and `lib/api/stream-paths.ts` |
| 1 | › `only llm-chat renders markdown message streams` | `react-markdown` and `rehype-sanitize` are imported only under `components/common/llm-chat/**`, and no other module imports `useEventStream` with a chat path |
| 1 | `web/tests/unit/llm-chat/llm-chat.test.tsx` › `renders panel and sheet variants from props` | panel renders the list, composer and footer; sheet shows an "Ask" trigger that opens the same body |
| 1 | `…llm-chat.typecheck.ts` (tsc gate) | `@ts-expect-error` on an unknown `systemPromptKey`, a missing `variant`, and an action without `label` |
| 2 | `api/tests/unit/chat/test_router.py::test_requires_chat_use_permission` | without `chat:use` → 403 in the single error shape; no LLM call |
| 2 | `…::test_validation_before_stream` | kind/key mismatch → 422 `chat_prompt_mismatch`; last message from the assistant → 422; 21 messages → 422; a bad action id → 422; all JSON, not `text/event-stream` |
| 2 | `…::test_unknown_item_404_before_stream` | 404 `item_not_found` |
| 2 | `…::test_streams_tokens_then_done` | scripted chunks become `token` events in order with monotonic ids, then one `done` with `usage.model_id` equal to the workhorse model |
| 2 | `api/tests/unit/chat/test_actions.py::test_splitter_holds_back_block_across_chunk_boundaries` | the marker split over 3 deltas never leaks; text before it is emitted |
| 2 | `…::test_parse_filters_to_allowed_and_caps` | ids outside `allowed_actions` are dropped; duplicates removed; at most 3; label truncated; nested args rejected |
| 2 | `…::test_bad_block_dropped_without_logging_content` | invalid JSON gives no `action` event; `capture_logs` has no block text |
| 2 | `api/tests/unit/chat/test_service.py::test_action_events_only_for_allowed_ids` | a model block proposing `requeue` and `delete_all` with allowed `[requeue]` yields one `action` |
| 2 | `…::test_request_uses_workhorse_role_config` | `ReplayLlmClient.calls[0]`: `purpose="chat.workhorse"`, effort from config (default `low`), `history` equals the prior turns, `timeout_s` and `max_tokens` set, `prompt_version` set |
| 2 | `…::test_item_context_contents_and_no_artifact_text` | the system prompt contains stage, state, error code, escalation summary, extraction final, lines and candidate receipts; no `quote`, no artifact or part text, no object keys |
| 2 | `…::test_flow_context_stage_counts_and_failures_today` | `collect_queue_stats` rows and today's failures by code are present; yesterday's failures are excluded |
| 2 | `…::test_context_is_bounded` | an item with 500 lines gives context ≤ `MAX_CONTEXT_CHARS` and `truncated: true` |
| 2 | `…::test_timeout_emits_stream_error` / `…::test_transient_and_refusal_map_codes` | `stream-error` codes `timeout`, `llm_unavailable` and `refused`; no `done` after them |
| 2 | `…::test_client_disconnect_closes_llm_stream` | cancelling the consumer runs the generator's `aclose` (the fake records the close) |
| 2 | `api/tests/unit/chat/test_prompts.py::test_prompts_keyed_item_and_flow` | `PROMPTS` keys equal `PromptKey`; `render_system` embeds the action markers from the constants and the allowed ids |
| 2 | `api/tests/integration/test_chat_context_repo.py::test_failures_by_code_since` | grouped distinct-item counts (SQLite; ATP when available) |
| 3 | `web/e2e/chat-item.spec.ts` › `item chat shows suggestions, streams with caret, stop aborts` | on `/items/[id]`, Chat tab: both suggestions visible; clicking one streams tokens (delayed SSE) with the caret visible; Stop hides the caret, keeps the partial text and the route sees the abort |
| 3 | › `assistant markdown is sanitised` | the mocked token `<script>window.__pwned=1</script><img src=x onerror="window.__pwned=2">**bold**` gives `window.__pwned` undefined, no `script` or `img` in the log, and `bold` rendered as `strong` |
| 3 | › `footer note` | "Answers by Claude Haiku 5.5. Check before acting." |
| 3 | `web/tests/unit/llm-chat/markdown.test.tsx` › `rehype-sanitize strips script and handlers` | the same payload in jsdom; no `script`, no `on*` attributes |
| 4 | `web/e2e/chat-flow.spec.ts` › `Ask opens the sheet with the flow suggestion` | "What's driving failures today?" |
| 4 | › `action chip needs confirmation; no request before confirm` | an `action` event renders a chip. Clicking it opens the dialog; the server-action request counter (`page.on("request")` on the action POST) stays at 0. Cancel → still 0; Confirm → 1 |
| 4 | `web/tests/unit/llm-chat/action-chips.test.tsx` › `onAction called only after confirm` | `vi.fn` not called on chip click or cancel; called once with `(id, args)` on confirm; an error `Result` shows a toast with the request id |
| 4 | › `ignores action ids not in props` | |
| 5 | `web/e2e/chat-item.spec.ts` › `timeout shows try-again and retry re-posts` | a `stream-error {code:"timeout"}` shows "The assistant didn't answer (timeout). Try again"; Retry sends a second POST with the same body and recovers |
| 5 | › `disconnect shows disconnected state with retry` | the route aborts mid-stream; the disconnected banner and Retry show |
| 5 | `web/tests/unit/llm-chat/use-chat.test.tsx` › `uses useEventStream POST body` | `streamRequests()[0]`: URL `/api/stream/chat/stream`, method POST, JSON body with context, `system_prompt_key`, messages and `allowed_actions` |
| 5 | › `clean end after done is not disconnected; clean end without done is` | |
| 5 | `web/tests/unit/llm-chat/chat-reducer.test.ts` › `phase transitions` | idle → streaming → done, error, disconnected, stopped; retry drops the failed draft |
| 6 | `web/tests/unit/llm-chat/client-boundary.test.ts` › `llm-chat is a client component with no secrets` | `llm-chat.tsx` starts with `"use client"`; no file under `llm-chat/**` contains `fetch(`, `process.env`, `lib/api/client`, `lib/api/actions`, `lib/env`, `lib/auth`, or `server-only` |
| 6 | › `talks only to the s31 proxy` | a render plus send: the only request is to `/api/stream/chat/stream`, with no `Authorization` header set by the client |

## Assumptions and deviations

1. **SSE-14: the failure event is named `stream-error`, not `error`.** AC2 names it `error`. s31's `useEventStream` routes `stream-error` frames to `onStreamError`, and BMN SSE-14 forbids naming a frame `error`. The payload `{code, message}` is unchanged.
2. **`done.usage` tokens are null.** s08 pins `stream_text -> AsyncIterator[str]` with no usage. Token and cost rows come from s36's `MeteredLlmClient`. `model_id` and `latency_ms` are real.
3. **An `onAction` prop is added** beyond the AC1 signature. Actions call existing endpoints through server actions passed as props (story Out of scope), so the component needs a handler. The event `label` is the model's reason; the chip shows the prop `label`.
4. **Context sources outside the story's deps.**
   - s09 `AdjudicationRepository.latest_for`, s29 `collect_queue_stats`, and s02 `HistoryRepository` are pinned.
   - Line results and candidate receipts use s15's and s13's repository reads as merged before s22 in wave 5. Expected names: `LineResultRepository.for_item`, s13's candidate/reservation repository. Their plans weren't written at planning time, so the coder binds to the merged names, adding no queries outside repositories.
   - `escalation_summary` and `last_error_*` are s02 columns.
5. **New files outside the story's three named paths**, all still file-disjoint: `data/repositories/chat_context.py` (no query outside a repository), `api/schemas/chat.py` (following s21 and s40), and `api/llm_deps.py` (no API-process `LlmClients` dependency is pinned anywhere; s30's container is for workers).
6. **Chat limits are module constants**, not runtime config: turns, message size, context size, `max_tokens`. They aren't auto-fix thresholds, and adding keys would edit s02's `config_keys.py`. They can be promoted later. Model id, effort and timeout do come from config.
7. **Transcripts are not persisted, and nothing is written to history.** Chat makes no automated decision, and actions are recorded by the endpoints they call.
8. **E2E location is `web/e2e/`** (s01's `testDir`), not `web/tests/e2e/`.
9. **`npx shadcn@latest add textarea scroll-area`** must not change `package.json` or the lockfile. With the Base UI base, both come from the existing package. If the CLI tries to add a dependency, the coder reverts it, builds from the existing primitives (a native `textarea` with the `Input` styles and an `overflow-y-auto` list) and records this in the return.

## Risks

- **Prompt injection through item data** (payer names, extracted text) could make the model propose actions. Mitigations:
  - the allow-list is enforced server-side and again client-side;
  - every action needs human confirmation, and it runs through endpoints that do their own authorization;
  - the context is wrapped as data in the system prompt.
- **The model emits a malformed or partial block, or text after the block.** The splitter keeps it out of the stream and parsing fails closed (no actions). Text after the block is discarded.
- **s31's `useEventStream` connection-key semantics** (`enabled` toggling to abort, `retry()` re-posting the same body) are relied on. If the merged s31 differs, adapt `use-chat.ts` only.
- **The E2E specs depend on s19's pages and fake-API harness.** They run only after s19 merges, and the jsdom tests cover the same behaviour earlier.
- **Haiku 5.5 thinking is on by default**, which adds latency before the first token. Effort `low` keeps it short, and the timeout from config bounds it.
