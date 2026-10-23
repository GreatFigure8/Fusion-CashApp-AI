# Plan: assistant-chat-redesign

Story: [story.md](story.md). Design screen: **Assistant** (`design/project/glass/Chat.dc.html`, design.md §3.5, §6; dock as on `Shell.dc.html`). web/ only; no API change, no migration.

Skills/references applied: nextjs-fullstack-standards, dev-bother-me-nope `references/nextjs.md` + `nextjs/{typescript,testing-and-observability,sse-and-streaming,rendering-and-caching,route-handlers-and-apis,routing-and-metadata,proxy-auth-and-security}.md`, python-web-app:rendering-untrusted-content (markdown sanitising). claude-api / building-llm-backed-features read for the contract only (the model call lives in chat-agent-tool-registry).

## 1. Approach

- research.md **a3**: keep the ONE `components/common/llm-chat` component and the one `POST /chat/stream`; port payroll-compare **visuals, not code** (`D:\AIX-Payroll-Compare\webapp\src\features\chat\ui\{composer,thread,turns,activity,proposals,side-panel}` looked at for structure only). a4 (wholesale port / AI-SDK) stays rejected.
- Move the client to chat-agent-tool-registry's tool-event SSE contract (Amendment in research.md: one tool registry, confirm-before-mutate); delete the action-block handling (`token`/`action` frames, `actions`/`onAction` props, `action-chips.tsx` as an action surface).
- One `LlmChat` with `variant: dock | page | compact`; parts split into `llm-chat/*` files; state in one reducer; one `useChat` over the shared `useEventStream` (live-progress-dashboard).
- `AssistantDock` mounted once in `app/(shell)/layout.tsx` (Server Component fetches `GET /chat/tools` + `/me`, passes plain props, RC-5/RC-7); `/assistant` page is a Server Component reading `?thread=` (TS-13, TS-16, RT-28) that preloads `GET /chat/threads/{id}`.
- Confirm/cancel go through thin server actions (`apiAction`, SEC-21/22) for cancel, and through the stream proxy for confirm (the confirm response streams the result, SSE-27).
- Images: `+` uses failed-receipt-review's `DropZone` and its proxy `POST /api/review/uploads?stage_only=true` -> `upload_ids` sent with the next turn.
- Visuals only through glass-theme-shell tokens and common components (`Pill`, `SuggestionChip`, `GlassPanel`, `StateCard`, `MonoLabel`, `Button` warn variant); no per-page CSS.

## 2. Files

### Change
| File | Purpose |
|---|---|
| `web/components/common/llm-chat.tsx` | The one `LlmChat` (props in §7). Picks layout by `variant`; owns `useChat`; forwards result cards to `onToolResult`. Removes `actions`/`onAction`/`open`/`onOpenChange`/`panel`/`sheet`. |
| `web/components/common/llm-chat/chat-schemas.ts` | Zod schemas for the 7 registry events (`text_delta`, `tool_started`, `tool_progress`, `tool_finished`, `confirm_required`, `error`, `done`), `ConfirmPreview`, result-card discriminated union (`state_card`, `replay_card`, `export_card`, `table_card`), `ChatToolsOut`, `ChatThreadOut`, request body. Types mirror `Schemas[...]` from the regenerated OpenAPI (`satisfies` checks so drift breaks tsc). Old `tokenDataSchema`/`actionDataSchema`/`ChatAction*` removed. |
| `web/components/common/llm-chat/chat-reducer.ts` | Turn model: messages with ordered `parts: (text | activity-group | confirm | card)`; activity rows keyed by `call_id` with `running|waiting|ok|failed|cancelled`, `done/total`, `duration_ms`; `threadId`; phases idle/streaming/awaiting_confirm/done/error/disconnected/stopped. Actions for every event plus `confirm-sent`, `cancel-sent`, `hydrate` (thread load). |
| `web/components/common/llm-chat/use-chat.ts` | `useChat({context, systemPromptKey, toolGroups, threadId, initialMessages})` over `useEventStream` (POST, `reconnect:false`); `send(text, uploadIds?)`, `confirm(callId, reason)`, `cancel(callId)`, `stop`, `retry`. Confirm opens a second stream on `/chat/tool-calls/{id}/confirm`. Handles both `error` event and `stream-error` frame. |
| `web/components/common/llm-chat/composer.tsx` | Two forms: `dock` (single-line input, "ASSISTANT" mono label, "Full screen" link, 32px send, halo) and `full` (chips row, textarea min 48px 15px, toolbar `+` / tool-group muted pill / send, hint row kbd chips). ↵ send, Ctrl+↵ newline, `/` opens prompt list. |
| `web/components/common/llm-chat/message-list.tsx` | Thread column max 880; user bubble (`bg-surface-3`, `border-line-strong`, radius 12, max 78%, 15.5px); renders parts in order via `AssistantMarkdown`, `ToolActivity`, `ConfirmCard`, `ResultCard`. |
| `web/components/common/llm-chat/action-chips.tsx` | Becomes the suggestion-chips row only (`SuggestionChip` from glass-theme-shell; horizontal scroll variant for the narrow dock). No action handling. |
| `web/components/common/llm-chat/suggestions.tsx` | Empty welcome: "What should CashApp do?" + Show live progress / Pause a station / Submit failed receipts. |
| `web/components/common/llm-chat/chat-status.tsx` | Becomes the 40px mono header (Assistant / title, Connected dot via `Pill dot`, "Haiku 5.5 · zero retention", "Acting as <name> · <role>"); keeps error/disconnected banners (`StateCard kind=error`). |
| `web/components/common/llm-chat/assistant-markdown.tsx` | 14px/1.7, inline code mono on `--s3`; keeps rehype-sanitize without `img`, no rehype-raw; links only `http(s)`/relative with `rel=noopener noreferrer`. |
| `web/components/common/llm-chat/defaults.ts` | ONE place for: route -> dock chips map (`ROUTE_CHIPS`, longest-prefix match), full-composer chips, welcome chips, prompt list, copy strings (placeholder, hints, denied copy, footer), tool-group labels (`TOOL_GROUP_LABELS`). |
| `web/app/(shell)/layout.tsx` | Mount `<AssistantDock>` once after `AppShell` children (glass-theme-shell owns the rest of the layout; this story adds only the dock line and its props: `me`, `tools` from `getChatTools()`). |
| `web/lib/api/stream-paths.ts` | Append-only: allow `/chat/tool-calls/{id}/confirm` via a `STREAM_PATH_PATTERNS` regex list next to `STREAM_PATHS` (`^/chat/tool-calls/[A-Za-z0-9_-]{1,64}/confirm$`); `isStreamPath` checks both. If live-progress-dashboard/matching-lab-ui already merged a pattern mechanism, add the one entry to it instead (no second mechanism). |
| `web/components/items/item-view.tsx` | Migrate to `variant="compact"`, `systemPromptKey="item"`, `tools={["EXCEPTIONS"]}`; drop `ITEM_CHAT_ACTIONS`/`onAction`. |
| `web/components/flow/flow-monitor.tsx` | Remove the sheet chat and `FLOW_CHAT_ACTIONS` (the dock is on /flow with flow chips); minimal edit, exceptions-workbench-restyle restyles the rest. |
| `web/components/shell/command-palette.tsx` | ⌘K: add one "Ask the assistant" entry that focuses the dock composer (`focusAssistantDock()` from `dock.tsx`). |

### Create
| File | Purpose |
|---|---|
| `web/components/common/llm-chat/dock.tsx` | `AssistantDock` (client): `usePathname()` -> route chips; hidden on `/assistant` (the page renders the full chat); centered `min(880px,100%)`; below 1024px fixed to viewport bottom, chips `overflow-x-auto`; hint "Acts with your permissions · every change asks you to confirm · ⌘K"; "Full screen" -> `/assistant?thread=<id>` (or `/assistant` before the first turn). Expanded dock thread shows above the composer in a capped-height panel. |
| `web/components/common/llm-chat/tool-activity.tsx` | Bordered strip of rows: lucide icon per group, mono tool name, one-line description (text only), mono duration; running = pulsing dot (reduced-motion safe) + "N of M"; waiting = "waiting for your confirmation"; failed = err tone + message. |
| `web/components/common/llm-chat/confirm-card.tsx` | Warn border + glow, "CONFIRM A CHANGE" + `Pill tone=locked` "Audited"; What/Before/After/Who/Reason grid; required reason `Textarea` (prefilled from `preview.reason_prompt` as placeholder only); warn-filled Confirm (disabled until reason non-blank and while sending) and Cancel. Decided state shows "Confirmed"/"Cancelled". |
| `web/components/common/llm-chat/result-cards.tsx` | `ResultCard` switch: `StateResultCard` (title, status `Pill`, mini-stats grid, history id mono), `ReplayResultCard` (Changed, Newly matched, Newly failed, per-currency affected; Promote… link to `/lab?candidate=<id>`, Discard sends "Discard candidate <id>" as a turn, Open in Lab link), `ExportResultCard` (file chip, mono filename, "<size> · self-contained", Preview / Download links, only same-origin `/api/` hrefs), `TableResultCard` (DataTable). |
| `web/components/common/llm-chat/live-context.tsx` | Panel `flex 1 1 280`: Automation 7d, Open exceptions (from `/metrics/summary?window=7d` + `useEventStream("/metrics/stream")` `summary`), Bus lag, Apply status (`/engine/status` + `/engine/stream` `status`), Fusion reads (`/integrations/mcp/status`; "unknown" on 403/failure); "Your tools" Allowed/Denied pills per group from `GET /chat/tools`; footnote "The assistant can never do more than your role allows."; each value degrades to "—" with stale marker independently. |
| `web/components/common/llm-chat/prompt-list.tsx` | `/` prompt list on shadcn `command` + `popover` (existing primitives); picking inserts the prompt. |
| `web/components/common/llm-chat/attach.tsx` | `+` button -> popover with `DropZone{accept: image/png,image/jpeg,image/webp,application/pdf, maxBytes, maxFiles, onFiles}`; posts each batch to `/api/review/uploads?stage_only=true` (multipart), shows staged chips, returns `upload_ids`; limits from `GET /review/quota`-adjacent props (server-provided `uploads.*` values via layout props, fallback 5 MB/10). |
| `web/components/common/llm-chat/actions.ts` | `"use server"`: `cancelToolCall(callId)` -> `POST /chat/tool-calls/{id}/cancel`, Zod-validated id (SEC-21, SEC-22, TEST-10), returns `Result`. |
| `web/lib/chat.ts` | `server-only`: `getChatTools()` (cached per request via React `cache`), `getChatThread(id)` -> `Result`. |
| `web/app/(shell)/assistant/page.tsx` | Server Component: awaits `searchParams` (`thread` validated with Zod, RT-13), loads thread + tools + me, renders `<LlmChat variant="page" systemPromptKey="assistant" context={{kind:"assistant"}} threadId initialMessages …/>`; unknown/foreign thread -> starts fresh with a notice (no 404). |
| `web/app/(shell)/assistant/loading.tsx` | Skeleton header + thread (RT-8). |
| `web/app/(shell)/assistant/error.tsx` | `'use client'` generic error with Retry (TEST-19/20/21). |

Total: 16 changed + 12 created = **28 files**.

### UI checklist (Assistant board; coder ticks each in validation.md)
- [ ] Dock: chips (pill `--s2`, `--line2`, 13px, min-h 34, centered, wrap), composer `--s2` radius 16 halo `0 0 0 4px #4f7cff1f` + drop shadow, "ASSISTANT" mono accent label, placeholder "Ask or tell CashApp to do something…", "Full screen" link, 32px `--acc` send radius 8 arrow-up, hint "Acts with your permissions · every change asks you to confirm · ⌘K"; <1024 pinned bottom, chips scroll.
- [ ] Route chips e.g. "Where are items waiting longest?", "Pause apply until 15:00", "Export this week's report".
- [ ] Header 40px mono uppercase 11.75px: Assistant, Connected (glowing dot), "Haiku 5.5 · zero retention", "Acting as <name> · <role>".
- [ ] Thread max 880, padding 24x16, gap 18; user bubble `--s3`, `--line2`, radius 12, max 78%, 15.5px; assistant md 14px/1.7, mono inline code on `--s3`.
- [ ] Tool rows: icon, mono 12.5px name, `--soft` description, right mono duration; pulsing dot + "1,140 of 1,912 items"; "waiting for your confirmation".
- [ ] Confirm card: warn border `#ffc96b66` + glow `0 0 40px -22px #ffc96b`; "CONFIRM A CHANGE"; "Audited" pill; What/Before/After/Who/Reason; warn-filled Confirm; Cancel.
- [ ] State card (title, status pill, mini-stats e.g. In flight 3 → 0, Waiting 96, Resumes 15:00, History h_…); replay card (Changed 41, Newly matched +19, Newly failed +3, INR affected; Promote…, Discard, Open in Lab); export card (HTML file chip, mono filename, "84 KB · self-contained", Preview, Download).
- [ ] Full composer chips: "Where is time lost between stations?", "Which auto-fix fails most?", "Is the Cohere cluster oversized?", "Work my oldest exception"; textarea min 48 15px; `+`; muted pill "Engine · Lab · Settings · Reports · Review · Exceptions · Fusion reads" (only allowed groups); send; hints mono 10.75px kbd: ↵ Send, Ctrl+↵ New line, / Prompts, + Images, "Changes run only after you confirm".
- [ ] Live context: "Live context", Automation · 7d, Open exceptions, Bus lag, Apply, Fusion reads; "Your tools": Engine control, Change settings, Lab replay and promote, Work exceptions, Submit receipt images, Export reports (+ Fusion reads, Progress) with Allowed/Denied; footnote.
- [ ] States: "Empty · welcome" "What should CashApp do?" + 3 chips; "Loading · tool running"; "Error · tool failed" "<tool> returned 409 … Nothing changed."; "Denied · permission" "Settings changes need config write" / "You're an operator. The assistant can draft the change for an admin."
- [ ] Shared components used: `Pill`, `SuggestionChip`, `GlassPanel`, `StateCard`, `MonoLabel`, `DataTable`, `DropZone`, `Button` warn, shadcn `textarea`, `command`, `popover`, `skeleton`.

## 3. Test plan (written and run only in step 5)

Unit: Vitest + Testing Library + msw (`web/tests/support/{api-mock,sse-mock}.ts`). Browser: Playwright against the production build with the mock API (`web/tests/support/mock-api-server.ts`, `e2e/global-setup.ts`), board = Assistant (`Chat.dc.html`), dock also checked on the Shell board.

| AC | Test (path :: name) | Type |
|---|---|---|
| 1 | `web/tests/components/common/llm-chat/single-chat.test.ts` :: `only llm-chat names the /chat/stream path` (scans `web/{app,components,lib,hooks}` sources; allowed: `llm-chat/chat-schemas.ts`, `lib/api/stream-paths.ts`, generated `schema.d.ts`/`openapi.json`) | unit |
| 1 | `.../llm-chat.test.tsx` :: `variant dock renders the dock composer`, `variant page renders header, thread and live context`, `variant compact renders the compact layout` | unit |
| 1 | `.../chat-reducer.test.ts` :: `text_delta appends to the assistant draft`, `tool_started adds a running activity row`, `tool_progress updates done and total`, `tool_finished ok attaches the result card`, `tool_finished not ok marks the row failed`, `confirm_required adds a confirm card and marks the row waiting`, `error sets the error phase with code and message`, `done ends streaming and stores thread_id`, `cancel-sent marks the row cancelled` | unit |
| 1 | `.../chat-schemas.test.ts` :: `parses every registry event payload`, `drops a malformed frame`, `refuses an unknown result card kind`, `event map has exactly the seven registry events` (no `token`/`action`) | unit |
| 1 | `.../use-chat.test.tsx` :: `streams a turn over POST /chat/stream`, `confirm streams from /chat/tool-calls/{id}/confirm with the reason`, `cancel calls the cancel action and runs nothing`, `stream-error frame becomes the error phase` | unit |
| 2 | `web/e2e/assistant.spec.ts` :: `dock is mounted once on every shell screen`, `dock shows route chips, composer copy and hint`, `dock pins to the bottom with scrolling chips below 1024px`, `full screen opens /assistant with the same thread` | browser |
| 2 | `.../dock.test.tsx` :: `route chips come from ROUTE_CHIPS by longest prefix`, `dock hides on /assistant` | unit |
| 3 | `assistant.spec.ts` :: `assistant page header and thread layout` | browser |
| 4 | `assistant.spec.ts` :: `tool activity rows show name, description and duration`, `running tool shows pulsing dot and N of M`, `waiting tool reads waiting for your confirmation` | browser |
| 5 | `assistant.spec.ts` :: `confirm card requires a reason before Confirm`, `confirm posts to /chat/tool-calls/{id}/confirm`, `cancel posts to /cancel and nothing runs` (mock asserts no confirm call) | browser |
| 5 | `.../confirm-card.test.tsx` :: `confirm disabled until reason is non-blank`, `confirm passes the reason` | unit |
| 6 | `assistant.spec.ts` :: `state card renders title, pill, stats and history id`, `replay card renders figures and actions`, `export card renders file chip, size and links` | browser |
| 7 | `assistant.spec.ts` :: `composer chips, textarea, toolbar and hint row`, `slash opens the prompt list`, `attach stages images through /review/uploads?stage_only=true` | browser |
| 7 | `.../composer.test.tsx` :: `enter sends`, `ctrl+enter inserts a new line`, `tool-group pill lists allowed groups only` | unit |
| 8 | `assistant.spec.ts` :: `live context shows values and Your tools pills from /chat/tools`, `live context drops under the thread at 375px with no horizontal scroll` | browser |
| 8 | `.../live-context.test.tsx` :: `one failing source degrades only its value` | unit |
| 9 | `assistant.spec.ts` :: `empty welcome state`, `tool running state`, `tool failed state says nothing changed`, `denied state names the permission` | browser |
| 10 | `.../llm-chat.test.tsx` :: `compact shows header line, one tool-group chip and hints row`, `compact has no live-context panel`, `onToolResult receives each result card in every variant` (parametrised over dock/page/compact) | unit |
| 11 | `.../assistant-markdown.test.tsx` :: `raw html in model output is shown as text`, `script, img and javascript: links are stripped`; `.../tool-activity.test.tsx` :: `tool description is rendered as text`; `.../result-cards.test.tsx` :: `card strings render as text`, `export card ignores non same-origin urls` | unit |

Counts: unit 37 (in 12 files under `web/tests/components/common/llm-chat/`), browser 23 (one file `web/e2e/assistant.spec.ts`). **Total 60.** Mock API additions (tester): SSE scripts for `/chat/stream` and `/chat/tool-calls/{id}/confirm`, JSON for `/chat/tools`, `/chat/threads/{id}`, `/chat/tool-calls/{id}/cancel`, `/metrics/summary`, `/engine/status`, `/integrations/mcp/status`, `/review/uploads`.

## 4. Data

None. No model, no Alembic migration (thread/pending-call tables belong to chat-agent-tool-registry).

## 5. Config / env

- No new env vars. Uses existing `API_BASE_URL` (server), `NEXT_PUBLIC_ENV_LABEL`.
- DB-stored keys read (owned elsewhere, values arrive via API responses, never hard-coded): `models.workhorse` (header model label comes from the thread/`done.usage.model_id`; static fallback "Haiku 5.5"), `uploads.max_file_bytes`, `uploads.max_files_per_request`, `uploads.allowed_types` (failed-receipt-review; passed to the attach `DropZone`), `chat.confirm_ttl_seconds` (expired confirm -> 409 shown as "This change expired. Ask again.").
- No new keys owned here.

## 6. Risks and coder gates

- **Contract drift with chat-agent-tool-registry** (same wave): every Zod schema is checked against the regenerated OpenAPI types with `satisfies`; coder runs `npm run api:sync` after merging the registry wip branch. Consumed shapes pinned in §7b; any mismatch is the registry's pin, not a local guess (L-comparison-wizard-from-fusion-2: no stubs at owners' paths).
- **Shared-file conflicts:** `(shell)/layout.tsx` (glass-theme-shell), `flow-monitor.tsx` (exceptions-workbench-restyle), `stream-paths.ts` (dashboard, lab): one-line, append-only edits; merge after owners.
- **XSS from model/tool output:** markdown sanitised, no raw HTML, card hrefs restricted to same-origin `/api/` and `/lab`, `/items` paths.
- **Confirm safety:** nothing mutates client-side; Confirm only POSTs; double-click guarded by `sending` state; server re-checks the principal.
- **SSE through LB:** handled server-side (heartbeat, `X-Accel-Buffering`); the client never re-posts a chat turn (`reconnect:false`).
- **Dock in layout** must not make the shell layout slow: tools fetch in its own `<Suspense>` (RC-38/39); dock renders with no tools until loaded.
- Gates (coder, nothing else): `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`. No tests, no build.

Rule ids applied: TS-1, TS-2, TS-5, TS-10, TS-13, TS-16, TS-17, TS-19, TS-20; RT-8, RT-9, RT-13, RT-22, RT-26, RT-27, RT-28; RC-5, RC-6, RC-7, RC-8, RC-12, RC-15, RC-38, RC-39; SSE-14, SSE-23, SSE-25, SSE-27; API-8, API-10, API-12, API-13; SEC-5, SEC-16, SEC-21, SEC-22, SEC-23; TEST-1, TEST-2, TEST-3, TEST-9, TEST-10, TEST-12, TEST-14, TEST-17, TEST-18, TEST-19, TEST-20, TEST-21, TEST-25, TEST-35, TEST-37.

## 7. Interfaces

### 7a. Provided (consumer: matching-lab-ui) — plannable: true

```ts
// web/components/common/llm-chat.tsx
import type { ChatContextRef, PromptKey, ToolGroup, ResultCard, ChatToolsOut, ChatMessageOut } from "./llm-chat/chat-schemas";
export type { ChatContextRef, PromptKey, ToolGroup, ResultCard };
export type LlmChatVariant = "dock" | "page" | "compact";
export type LlmChatProps = {
  context: ChatContextRef;              // { kind: PromptKey; id?: string }
  systemPromptKey: PromptKey;           // "assistant" | "matching" | "item" | "flow"
  variant: LlmChatVariant;
  tools?: readonly ToolGroup[];         // groups offered this chat; default = all allowed groups
  chips?: readonly string[];            // default from defaults.ts per variant/route
  title?: string;                       // compact/page header label, e.g. "Lab assistant"
  threadId?: string;
  initialMessages?: readonly ChatMessageOut[];
  catalog?: ChatToolsOut;               // GET /chat/tools; fetched client-side when absent
  onToolResult?: (card: ResultCard) => void;  // called once per tool_finished with result_card, every variant
  className?: string;
};
export function LlmChat(props: LlmChatProps): React.JSX.Element;

// chat-schemas.ts
export type ToolGroup = "ENGINE" | "LAB" | "SETTINGS" | "REPORTS" | "REVIEW" | "EXCEPTIONS" | "FUSION_READS" | "METRICS";
export type ResultCard =
  | { kind: "state_card"; title: string; status: string; stats: { label: string; value: string }[]; history_id: string | null }
  | { kind: "replay_card"; replay_id: string; candidate_id: string; changed: number; newly_matched: number;
      newly_failed: number; newly_ambiguous: number; affected: { currency: string; amount: string }[] }
  | { kind: "export_card"; filename: string; size_bytes: number; preview_url: string; download_url: string }
  | { kind: "table_card"; title: string; columns: string[]; rows: string[][] };
```
Compact layout: header line (`title` · Connected · model), one tool-group chip (first of `tools`), thread, composer with ↵ and / hints; no live-context panel, no dock positioning; fills its parent (`h-full min-h-0`). Lab usage: `<LlmChat variant="compact" systemPromptKey="matching" context={{kind:"matching"}} tools={["LAB"]} title="Lab assistant" onToolResult={(c) => c.kind === "replay_card" && follow(c.replay_id)} />`.

### 7b. Consumed (pinned here so this story builds in the same wave; owners must match)

- chat-agent-tool-registry: `POST /chat/stream` body `{thread_id: string | null, context: {kind, id?}, system_prompt_key, message: string (<= 4000), tool_groups: ToolGroup[] | null, upload_ids: string[]}`; events exactly per its AC4, with `done{thread_id, usage:{model_id, latency_ms, input_tokens, output_tokens}}` and `tool_started.summary` / `tool_finished.result_card` / `confirm_required.preview = ConfirmPreview{what, before, after, who, reason_prompt}` and `tool_finished{ok:false}` carrying `error{code, message}`; `POST /chat/tool-calls/{id}/confirm {reason}` -> SSE of the same events; `POST /chat/tool-calls/{id}/cancel` -> `{status:"CANCELLED"}`; `GET /chat/tools` -> `[{group, tools:[{name, description, mutating, allowed}]}]`; `GET /chat/threads/{id}` -> `{id, messages:[{role, content, parts?}]}`; result-card fields as in 7a. `PromptKey` values lower-case on the wire (`assistant`, `matching`, `item`, `flow`).
- glass-theme-shell: `Pill{tone, dot, mono}`, `SuggestionChip`, `GlassPanel/PanelHeader/PanelBody`, `StateCard{kind,label,headline,body,actions}`, `MonoLabel`, `DataTable`, `Button variant="warn"`; `(shell)/layout.tsx` leaves a slot after the footer for the dock.
- failed-receipt-review: `DropZone{accept, maxBytes, maxFiles, onFiles, disabled}`; `web/app/api/review/uploads/route.ts` forwards the `stage_only` query and returns `{upload_ids: string[]}`.
- live-progress-dashboard: `useEventStream` from `@/hooks/use-event-stream` (same signature as today's `lib/api/use-event-stream.ts`); `GET /metrics/summary?window=7d` `{window, as_of, data: {automation_rate, open_exceptions, …}}`; `/metrics/stream` `summary` event.
- engine-control-api: `GET /engine/status` (`total_lag`, stations[`apply`].state) and `/engine/stream` `status`.
- fusion-mcp-transport (indirect, optional): `GET /integrations/mcp/status` `{healthy, latency_ms}`; 403 shows "unknown".

## Assumptions

- `/assistant` is reachable for any user with `CHAT_USE`; no nav entry (board shows none); ⌘K and the dock link reach it.
- Promote… on a replay card links to the Lab (`/lab?candidate=<id>`), which owns the audited promote; Discard sends a chat turn so `lab.discard` goes through its own confirm card. No client-side mutation path.
- flow-monitor's sheet chat and item-view's action chips are removed; their actions become registry tools (exceptions.*), offered by the dock (flow) and the compact chat (item).
- The dock's expanded thread shows inline above the composer (max 50vh); the full page is the place for long threads.
- Header model label uses `done.usage.model_id` mapped to a display name in `defaults.ts`; before the first turn it reads "Haiku 5.5 · zero retention".
- `ChatContextRef.kind` widens to `PromptKey`; `"assistant"` context carries no id.
