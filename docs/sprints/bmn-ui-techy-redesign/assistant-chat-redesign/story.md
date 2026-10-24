# assistant-chat-redesign: One assistant chat in the payroll-compare look: dock, full screen and compact

- Issue: #48 (AC 4, item 6)
- breaking: false (moves the web client to the new chat SSE contract in the same run; the breaking API change is chat-agent-tool-registry's)
- Design screen owned: **Assistant** (`design/project/glass/Chat.dc.html`, design.md §3.5, §6; also the dock as drawn on the Shell board)

## Story

As any user, I want one assistant that floats at the bottom of every screen and opens full screen, styled like the aix-payroll-compare chat, showing what tools it runs, asking me to confirm every change and showing results as cards, so that I can do anything in the app by talking to it.

## Context

research.md a3: keep the ONE `components/common/llm-chat` component; port visuals, not code, from `D:\AIX-Payroll-Compare\webapp` (composer box, bubbles, start cards, activity rows). Existing parts: `common/llm-chat.tsx`, `llm-chat/{composer,message-list,action-chips,suggestions,assistant-markdown,chat-status,chat-reducer,chat-schemas,use-chat,defaults}`. New parts: `tool-activity.tsx`, `confirm-card.tsx`, `result-cards.tsx`, `live-context.tsx`, `dock.tsx`. Configured by props `context`, `systemPromptKey`, `tools`, `chips`, `variant: dock | page | compact`.

## Acceptance criteria

1. [unit] `LlmChat` stays the single chat component (a test asserts no other component in `web/` calls `/chat/stream`); `variant` selects dock, page or compact layout; `use-chat`/`chat-reducer`/`chat-schemas` (Zod) handle every SSE event of chat-agent-tool-registry (`text_delta`, `tool_started`, `tool_progress`, `tool_finished`, `confirm_required`, `error`, `done`) and the old action-block handling is removed.
2. [browser] Assistant board (dock, also on the Shell board): `(shell)/layout.tsx` mounts `<AssistantDock>` once; on every screen a centered `min(880px,100%)` dock shows route-aware suggestion chips, the composer (`--s2`, 16px radius, halo, "ASSISTANT" mono label, single-line input "Ask or tell CashApp to do something…", "Full screen" link, 32px send) and the hint "Acts with your permissions · every change asks you to confirm · ⌘K"; below 1024 px it pins to the viewport bottom with horizontally scrolling chips. "Full screen" opens `/assistant?thread=<id>` with the same thread.
3. [browser] Assistant board: `/assistant` full screen with the 40px mono header (Assistant, Connected dot, "Haiku 5.5 · zero retention", "Acting as <name> · <role>"), centered thread max 880 (user bubble `--s3` right-aligned max 78% 15.5px; assistant markdown 14px/1.7 with mono inline code).
4. [browser] Assistant board: tool-activity rows grouped in the bordered strip (icon, mono tool name, one-line description, mono duration); a running tool shows the pulsing dot and live "N of M"; a tool waiting reads "waiting for your confirmation".
5. [browser] Assistant board: a mutating tool shows the confirm card (warn border + glow, "CONFIRM A CHANGE" + Audited pill, What / Before / After / Who / Reason grid with a required reason, warn-filled Confirm and Cancel); Confirm calls `POST /chat/tool-calls/{id}/confirm`, Cancel calls `/cancel`; nothing runs before Confirm.
6. [browser] Assistant board: result cards render for `state_card` (title, status pill, mini-stats grid, history id), `replay_card` (Changed, Newly matched, Newly failed, currency affected; Promote…, Discard, Open in Lab), `export_card` (file chip, filename, size "self-contained", Preview, Download).
7. [browser] Assistant board: composer with chips row, textarea (min 48px, 15px), toolbar (`+` attach images using `DropZone`, staged through `POST /review/uploads?stage_only=true`; muted pill listing tool groups; send), hint row with kbd chips (↵ Send, Ctrl+↵ New line, / Prompts, + Images, "Changes run only after you confirm"); `/` opens the prompt list.
8. [browser] Assistant board: the live-context panel (automation 7d, open exceptions, bus lag, apply status, Fusion reads status) and "Your tools" with Allowed/Denied pills from `GET /chat/tools`, footnote "The assistant can never do more than your role allows."; it drops under the thread on narrow screens.
9. [browser] Assistant board states: empty welcome ("What should CashApp do?" + Show live progress / Pause a station / Submit failed receipts), tool running, tool failed ("<tool> returned 409 … Nothing changed."), denied ("Settings changes need config write. You're an operator. The assistant can draft the change for an admin.").
10. [unit] `compact` variant (header line, one tool-group chip, hints row) renders inside a parent panel without the live-context panel; it is what matching-lab-ui embeds. Every variant accepts `onToolResult?(card)` so a host page can react to result cards (the Lab follows `replay_card`).
11. [unit] Assistant markdown rendering is sanitized (no raw HTML from model output); tool output text is rendered as text.

## Out of scope

- Tool implementations (their stories). Lab results column (matching-lab-ui).

## Deps

- glass-theme-shell: `Pill`, `SuggestionChip`, `GlassPanel`, `StateCard`, tokens, `(shell)/layout.tsx` structure. plannable: true.
- chat-agent-tool-registry: `POST /chat/stream` SSE events, `POST /chat/tool-calls/{id}/confirm|cancel`, `GET /chat/tools`, `GET /chat/threads/{id}`, result-card schemas. plannable: true.
- failed-receipt-review: `DropZone{accept, maxBytes, maxFiles, onFiles}`, `POST /review/uploads?stage_only=true` -> `{upload_ids}`. plannable: true.
- live-progress-dashboard: `GET /metrics/summary` for the live-context panel, `useEventStream`. plannable: true.
- engine-control-api: `GET /engine/status` for bus lag and apply status in the live-context panel. plannable: true.

## Assumptions

- Route-aware chips are a static map per route in `llm-chat/defaults.ts` (one place).
