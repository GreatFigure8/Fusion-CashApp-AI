# s22-ui-shared-llm-chat: UI shared LLM chat component

- Issue: #22
- Wave: 5 (owns `web/components/common/llm-chat.tsx` (+ its subcomponents under `web/components/common/llm-chat/`), `cashapp/services/chat/`, `cashapp/api/routers/chat.py`)
- breaking: false

## Story

As a person asking about an item or the flow, I want one chat component that streams answers from Haiku and can propose actions I confirm, so that every LLM conversation in the app behaves the same (CLAUDE.md DRY rule).

## Context

Design screen: design.md §7 "Shared LLM chat". Workhorse role (`claude-haiku-5-5`, streaming via s08's `LlmClient.stream_text`), zero data retention. Placed by s19 on the item view (right-rail tab) and the flow monitor (bottom-right sheet via an "Ask" button); s19 renders it with props, this story owns the component.

## Acceptance criteria

1. [unit] `<LlmChat context={{kind: "item"|"flow", id?: string}} systemPromptKey="item"|"flow" actions={[{id, label, confirm?: string}]} variant="panel"|"sheet" suggestions?={string[]} />` is the only chat implementation; an eslint/grep test asserts no other module in `web/` imports `/chat/stream` or renders a message-stream UI.
2. [api] `POST /chat/stream` (`chat:use`) body `{context: {kind, id?}, system_prompt_key, messages: [{role: "user"|"assistant", content}], allowed_actions: [id]}` → SSE events `token {text}`, `action {id, label, args}` (only ids in `allowed_actions`; proposed via a trailing structured block parsed server-side), `done {usage}`, `error {code, message}`. The service builds context server-side from the DB (item summary: stage, state, error code, escalation summary, extraction final, line results, candidate receipts; flow: stage counts, failures by code today) — no raw artifact text — with system prompts in `cashapp/services/chat/prompts.py` keyed `item` / `flow`.
3. [browser] Design §7 "Shared LLM chat" on the item view (`/items/[id]` right-rail Chat tab): empty state shows suggestions "Why is this stuck?", "Which receipt fits best?"; sending streams tokens with a caret; Stop aborts the stream; assistant markdown renders through `rehype-sanitize` (a `<script>` in a mocked response is not executed/rendered); footer "Answers by Claude Haiku 5.5. Check before acting."
4. [browser] Design §7 on the flow monitor (`/flow`, "Ask" button opens the sheet variant): suggestion "What's driving failures today?"; an `action` event renders a chip; clicking it opens a confirm dialog and only on confirm calls the action handler prop (never auto-executes; test asserts no request before confirm).
5. [browser] States: timeout/error → "The assistant didn't answer (timeout). Try again" with retry; SSE disconnect → disconnected state with retry; uses s31's `useEventStream` (POST body) — no direct `fetch` to the API.
6. [unit] The component is a client component that receives no tokens or secrets; it talks only to `web/app/api/stream/chat/stream` (s31 proxy).

## Out of scope

Placing it on pages (s19 does); new action endpoints (actions call existing endpoints such as requeue/lock through server actions passed as props).

## Deps

- s31-typed-web-api-client — `useEventStream(path, {body, onEvent})`, SSE proxy allow-list including `/chat/stream`, `api-mock.ts`, `sse-mock.ts`. plannable.
- s08-extraction-fan-out — `LlmClients.workhorse.stream_text(LlmRequest)`. plannable.
- s04-sign-in-authorization — `require_permission(CHAT_USE)`. plannable.
- s01-scaffold-monorepo — react-markdown, rehype-sanitize, sheet/dialog primitives. plannable.

## Assumptions

- s19 depends on this story (it imports the component), not the reverse. AC3/AC4 Playwright specs live in this story but drive s19's `/items/[id]` and `/flow` routes, so they run in the test cycle after s19 merges (tests are only run in step 5).
- Chat transcripts are not persisted (zero retention spirit); only usage rows (s36) are kept.
