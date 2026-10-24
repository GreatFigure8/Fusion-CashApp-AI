# Plan: matching-lab-ui (the Matching Lab screen)

Story: [story.md](story.md). Board: `design/project/glass/Lab.dc.html`, design.md §3.7, §5, §6 (compact), §7. web/ only; no API, no migration.

## 1. Approach

- research.md runner-up a5 (shadow-replay lab), adopted by input.md scope item 2, with a3's propose-and-confirm pattern for the mutation: the page never decides anything; the replay, staleness and promote rules live in matching-lab-replay-api, and promote is the same audited config write as Settings.
- `/lab` is a Server Component (RC-5, DF-1/DF-3): it awaits `searchParams` (TS-16), reads `/me`, `GET /lab/candidates` and the selected replay in parallel (DF-4) and passes plain DTOs (RC-7) to one client leaf `LabWorkspace`.
- Left column: the shared `LlmChat variant="compact" systemPromptKey="matching"` with the LAB tool group (no second chat, non-negotiable 7). `onToolResult(card)`: on a `replay_card` the page does `router.replace("/lab?candidate=<id>&replay=<id>")`, so the results column follows the replay the chat started; the server re-reads the data (no client fetching through Server Functions, DF-10).
- A RUNNING replay is followed with the one `useEventStream` hook over `/lab/replays/{id}/stream` (SSE-23..25); on the terminal event the page calls `router.refresh()`.
- Mutations (Replay again, Promote, Discard) are Server Actions in `app/(shell)/lab/actions.ts` wrapped in `apiAction` with Zod (DF-11..15, DF-22); Promote opens glass-theme-shell's `ConfirmDialog` first and sends `expected_version` and the reason.
- Everything visual is built from glass-theme-shell's shared components; no new tokens, no per-page CSS (research.md a1).

## 2. Files

Create:

| File | Purpose |
|---|---|
| `web/app/(shell)/lab/page.tsx` | Server Component. `requireSession("/lab")`; `getMe()`; no `lab:run` → `ForbiddenState`. Parses `searchParams` with `labSearchParams`; `Promise.all` of `GET /lab/candidates?limit=20` and (when a replay is selected or the default candidate has `latest_replay_id`) `GET /lab/replays/{id}`. Renders `TopBar` (title "Matching Lab", env pill, `Read-only replay` locked pill, Sample data, muted caption "Replays never write to Fusion") and `LabWorkspace`. `export const metadata = { title: "Matching Lab" }` (TS-18). |
| `web/app/(shell)/lab/loading.tsx` | Skeleton split: compact chat frame + `SkeletonRows` for the results column. |
| `web/app/(shell)/lab/error.tsx` | `'use client'` boundary (TEST-19..21): `StateCard kind="error"` "Couldn't load the lab", generic message + digest, Retry (`reset`). |
| `web/app/(shell)/lab/actions.ts` | `"use server"`: `replayAgainAction({candidateId, windowDays})` → `POST /lab/candidates/{id}/replays`; `promoteAction({candidateId, replayId, reason, expectedVersion})` → `POST /lab/candidates/{id}/promote`; `discardAction({candidateId})` → `POST /lab/candidates/{id}/discard`. Each `apiAction(schema, …)`, session checked first (DF-12, SEC), returns `Result` DTOs only (DF-15), `refresh()` after success (RC-36). |
| `web/app/api/lab/replays/[id]/items.csv/route.ts` | Thin GET proxy for the CSV export (API-1/2/4/8/10/13): `getSession()` → 401; Zod-validate `id` (`^rp_\d+$`) → 422; `apiRaw` `GET /lab/replays/{id}/items.csv`; pass through body, `Content-Type`, `Content-Disposition`, `Cache-Control: private, no-store` (mirrors `app/api/reports/[report]/export/route.ts`). |
| `web/lib/lab/schemas.ts` | Zod: `labSearchParams {candidate?: /^p_\d+$/, replay?: /^rp_\d+$/}`; `replayProgressEvent`; `replayCardSchema` (the fields this page reads from a `replay_card`); action input schemas (`reason` trimmed, min 1, max 500; `windowDays` int 1..90 default 30). |
| `web/lib/lab/view.ts` | Pure, client-safe: `labViewState(candidate, replay, me) -> "empty" | "loading" | "done" | "stale" | "failed" | "promoted" | "discarded"`; `canPromote(me, candidate, replay)` (CONFIG_WRITE, DONE, `replay.base_version === candidate.live_version`, candidate OPEN); `diffLines(config_diff) -> DiffBlock lines` (`-` before, `+` after, one key header line); `auditCaption(me, replayId, version)` → "Records <display_name> · replay rp_NNNN · expected version N"; `formatDuration(ms)` → "42 s". |
| `web/components/lab/lab-workspace.tsx` | `'use client'`. The split (`flex flex-wrap gap-4`; chat `flex-[1_1_380px] min-w-0`, results `flex-[999_1_520px] min-w-0`). Mounts `LlmChat` compact (props in §7) and the results column; `onToolResult` handler; picks the state component. |
| `web/components/lab/candidate-card.tsx` | `GlassPanel`: header "Candidate p_NNNN vs live vN", mono label "Replay complete · N s", `Pill muted` "N items · 30 days"; body `DiffBlock` (red/green tinted lines from `diffLines`); `Promoted` / `Discarded` pill when not OPEN. |
| `web/components/lab/comparison-tiles.tsx` | Grid `repeat(auto-fit,minmax(150px,1fr))` of four `KpiCard`s: Match differently N, Newly matched +N (ok), Newly failed +N (err/warn), Newly ambiguous N. |
| `web/components/lab/money-affected-table.tsx` | `GlassPanel` "Money affected" + label "by currency"; `DataTable` cols Currency, Newly matched, Newly unmatched, Items (numeric right, mono, `Money` per row with its own currency). One row per currency from the API; no total row, no summing. |
| `web/components/lab/changed-items-table.tsx` | `GlassPanel` "Items that change" + "Export CSV" link to `/api/lab/replays/{id}/items.csv`; `DataTable` cols Item (link to `/items/[id]`), Amount (currency-prefixed mono), Before `StatusBadge`/`Pill`, After `StatusBadge`/`Pill`; horizontal scroll inside the card. |
| `web/components/lab/promote-panel.tsx` | `'use client'`. "Promote to live" + `Audited` locked pill; pills "Replay ran on current vN" (ok) and "You can write config" (ok) or "Replay only" (muted); required "Reason · required" input; primary `Promote p_NNNN` (disabled until reason and `canPromote`), `Discard` outline; caption from `auditCaption`. Promote opens `ConfirmDialog` (title "Promote p_NNNN to live?", body = config diff summary, reason prefilled, "Recorded as …", expected version) → `promoteAction` in `startTransition`; errors kept in state (TEST-25); a 409 STALE re-renders as the stale state. |
| `web/components/lab/replay-progress.tsx` | `'use client'`. `StateCard kind="loading"` label "Loading · replay", `Meter` + mono "N of M items"; `useEventStream("/lab/replays/{id}/stream", {schema: replayProgressEvent})`; on `status !== "RUNNING"` → `router.refresh()`; stream down → "Reconnecting…" and last known count. |
| `web/components/lab/lab-states.tsx` | `LabEmptyState` ("Empty", "No candidate yet", "Ask the assistant for a change, or pick a matching key to try."), `LabStaleState` ("Error · stale replay", "Live config moved to vN", "Promote is blocked until you replay against the new version.", button "Replay again" → `replayAgainAction`), `LabReplayFailed` ("Error · replay", "The replay didn't finish. Nothing changed.", Replay again), `LabNoPermissionNote` ("No permission", "Replay only", "Operators can replay and read results. Promote needs config write."). All `StateCard`. |
| `web/tests/lab/*.test.ts(x)`, `web/e2e/lab.spec.ts`, `web/tests/support/fixtures/lab.ts` | Written by the tester in step 5 (see §3). |

Change:

| File | Change |
|---|---|
| `web/components/shell/nav.ts` (owner glass-theme-shell) | Wire the Lab entry's count source only, through the owner's count-source API: open candidates = `open_count` of `GET /lab/candidates?limit=1`. Entry, code `LB`, permission `lab:run` are the owner's. |
| `web/lib/permissions.ts` | `ROUTE_PERMISSIONS["/lab"] = { permission: "lab:run", role: "OPERATOR" }` (append). |
| `web/lib/api/stream-paths.ts` (owner of the hook: live-progress-dashboard) | Append-only: allow the dynamic path `/lab/replays/rp_<n>/stream` (a regex in a `STREAM_PATTERNS` list next to `STREAM_PATHS`; `StreamPath` gains `` `/lab/replays/${string}/stream` ``). If live-progress-dashboard's plan already adds pattern support, only add the pattern. |
| `web/components/common/llm-chat/defaults.ts` (owner assistant-chat-redesign) | Append the `/lab` entry to the route chip map: "Try a ±3 day window for INR only", "Why do INR items go ambiguous?", "Replay my last candidate on 7 days". |
| `web/lib/api/openapi.json`, `schema.d.ts` | Not edited by hand: regenerated by `npm run api:sync` once matching-lab-replay-api is merged. |

### Board checklist (lesson L-admin-act-for-absent-owner-1; coder ticks each in validation.md)

Top bar: [ ] "Matching Lab" · [ ] env pill (DEV warn) · [ ] `Read-only replay` locked pill · [ ] `Sample data` muted pill (only when API says sample) · [ ] "Replays never write to Fusion" caption.
Chat (compact): [ ] header "Lab assistant · Connected · Haiku 5.5" (mono uppercase 11.75px, live dot) · [ ] one tool chip `matching.*` · [ ] hints `↵ Send`, `/ Prompts` with kbd chips · [ ] solid `--s1` panel, radius 16, no blur.
Candidate card: [ ] "Candidate p_NNNN vs live vN" · [ ] "Replay complete · N s" · [ ] pill "N items · 30 days" · [ ] `DiffBlock` key line + `− old` red-tint (`bg-err-soft text-err-ink`) + `+ new` green-tint (`bg-ok-soft text-ok-ink`), mono 13px.
Tiles: [ ] Match differently · [ ] Newly matched +N · [ ] Newly failed +N · [ ] Newly ambiguous N · [ ] mono 26px values, min 150px grid.
Money: [ ] title "Money affected" + label "by currency" · [ ] cols Currency / Newly matched / Newly unmatched / Items · [ ] numbers right-aligned mono · [ ] no cross-currency total.
Items: [ ] "Items that change" · [ ] "Export CSV" link · [ ] cols Item / Amount / Before / After · [ ] Before/After as pills.
Promote: [ ] "Promote to live" + `Audited` pill · [ ] "Replay ran on current vN" · [ ] "You can write config" · [ ] "Reason · required" · [ ] primary `Promote p_NNNN` with glow · [ ] `Discard` · [ ] caption "Records <name> · replay rp_NNNN · expected version N" · [ ] `ConfirmDialog` · [ ] post-promote `Promoted` pill and "live vN+1".
States: [ ] Empty "No candidate yet" + body copy · [ ] Loading · replay "N of M items" meter · [ ] Error · stale replay copy + "Replay again" · [ ] No permission "Replay only" copy, promote disabled · [ ] error border `#f8717155` on error kind.
Layout: [ ] split wraps chat first, results below · [ ] no horizontal page scroll at 375 · [ ] tables scroll inside the card.

## 3. Test plan

Unit = Vitest (jsdom) under `web/tests/lab/`; browser = Playwright `web/e2e/lab.spec.ts` against the production build and the mock API (`tests/support/mock-api-server.ts`, `sse-mock.ts`), fixtures in `web/tests/support/fixtures/lab.ts` (candidate p_0192, live v41, replay rp_3381 DONE 1,912 items, INR row, a RUNNING replay, a STALE candidate). All browser tests: design screen **Lab** (`design/project/glass/Lab.dc.html`), at 1440×1000 unless named.

| AC | Test (path :: name) | Type |
|---|---|---|
| 1 | `e2e/lab.spec.ts` :: `lab top bar shows title, env, read-only replay, sample data and the never-write caption` | browser |
| 2 | `e2e/lab.spec.ts` :: `lab assistant renders compact chat header, one matching tool chip and hints` | browser |
| 2 | `e2e/lab.spec.ts` :: `asking the lab assistant to try a change follows the replay it started` (SSE mock emits `tool_finished` with a `replay_card` for p_0193/rp_3382; URL becomes `?candidate=p_0193&replay=rp_3382`; candidate card shows p_0193) | browser |
| 2 | `tests/lab/lab-workspace.test.tsx` :: `onToolResult navigates on replay_card and ignores other cards` | unit |
| 3 | `e2e/lab.spec.ts` :: `candidate card shows id vs live version, duration, items pill and tinted diff` | browser |
| 3 | `e2e/lab.spec.ts` :: `four comparison tiles show match differently, newly matched, newly failed, newly ambiguous` | browser |
| 3 | `tests/lab/view.test.ts` :: `diffLines maps config_diff to minus/plus lines per key` | unit |
| 3 | `tests/lab/view.test.ts` :: `formatDuration renders whole seconds` | unit |
| 4 | `e2e/lab.spec.ts` :: `money affected table lists one row per currency with no total` | browser |
| 4 | `e2e/lab.spec.ts` :: `items that change table shows before and after pills and an Export CSV link` | browser |
| 4 | `tests/lab/money-affected-table.test.tsx` :: `never sums amounts across currencies` | unit |
| 4 | `tests/lab/items-csv-route.test.ts` :: `csv proxy returns 401 without session, 422 on bad id, passes file headers` (TEST-9) | unit |
| 5 | `e2e/lab.spec.ts` :: `promote requires a reason and confirms through the dialog` | browser |
| 5 | `e2e/lab.spec.ts` :: `after promote the live version increments and the candidate shows Promoted` | browser |
| 5 | `e2e/lab.spec.ts` :: `discard marks the candidate discarded` | browser |
| 5 | `tests/lab/promote-panel.test.tsx` :: `audit caption names the user, replay and expected version` | unit |
| 5 | `tests/lab/actions.test.ts` :: `promoteAction rejects empty reason and sends expected_version` (TEST-10) | unit |
| 6 | `e2e/lab.spec.ts` :: `empty state says no candidate yet` | browser |
| 6 | `e2e/lab.spec.ts` :: `running replay shows N of M items over the stream and refreshes on done` | browser |
| 6 | `e2e/lab.spec.ts` :: `stale replay blocks promote and offers replay again` | browser |
| 6 | `e2e/lab.spec.ts` :: `operator without config write sees replay only and a disabled promote` | browser |
| 6 | `tests/lab/view.test.ts` :: `labViewState covers empty, loading, done, stale, failed, promoted` | unit |
| 6 | `tests/lab/view.test.ts` :: `canPromote needs config write, a done replay and the current version` | unit |
| 6 | `e2e/lab.spec.ts` :: `lab page error boundary shows retry when candidates fail` (TEST-17) | browser |
| 7 | `tests/lab/nav-lab-entry.test.ts` :: `lab nav entry is visible only with lab:run` | unit |
| 7 | `tests/lab/nav-lab-entry.test.ts` :: `lab nav count shows open candidates from GET /lab/candidates` | unit |
| 8 | `e2e/lab.spec.ts` :: `at 375px the lab split wraps chat first with no horizontal scroll` (asserts `scrollWidth <= clientWidth`, chat box above results box) | browser |

Totals: 27 tests (16 browser, 11 unit). Locators by role/label (TEST-14); port from `PLAYWRIGHT_PORT` (TEST-13).

## 4. Data

None. No ORM model, no Alembic revision (the `LAB_*` tables are matching-lab-replay-api's single revision).

## 5. Config / env

No new env variable and no new DB key. Reads only: `lab.max_items` is shown indirectly through `total`; window default 30 days comes from the API (`window_days` on the replay). Existing web env (`API_BASE_URL`, session secrets) unchanged.

## 6. Risks and gates

- Contract drift with matching-lab-replay-api (same wave): the page codes against the shapes pinned in §7 and the regenerated `openapi.json`; the coder starts only after that API is merged to the sprint tip (lesson L-comparison-wizard-from-fusion-2) and runs `npm run api:sync`. Field names that differ are fixed in the plan's consumer, never by stubbing the API.
- `onToolResult` and the compact variant are assistant-chat-redesign's; `ConfirmDialog`, `DiffBlock`, count-source API are glass-theme-shell's; `useEventStream` + dynamic stream paths are live-progress-dashboard's. Never copy them here.
- `stream-paths.ts` and `defaults.ts` are edited by several stories: append-only edits, merged in split.md order.
- `items.csv` as a folder name under `app/api/lab/replays/[id]/` is a static segment; the coder confirms against `node_modules/next/dist/docs` (web/AGENTS.md) and falls back to `.../items-csv/route.ts` if dots are refused (record it).
- `apiFile` takes a typed `ApiPath` without path params; use `apiRaw` with the substituted path (or extend `apiFile` with path params once, in `lib/api/file.ts`).
- Money stays per currency (`Money` component), Decimal strings from the API, never parsed to float for sums.
- Gates (coder, lint + type-check only): `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`. No api/ changes, so no ruff/pyright run needed; if any api file is touched: `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`.

Rule ids applied: TS-1, TS-5, TS-10, TS-13, TS-15, TS-16, TS-17, TS-18, TS-19, TS-20; RC-5, RC-6, RC-7, RC-36, RC-38; DF-1, DF-3, DF-4, DF-10, DF-11, DF-12, DF-13, DF-14, DF-15, DF-22; API-1, API-2, API-4, API-8, API-10, API-12, API-13; SSE-23, SSE-24, SSE-25, SSE-26; SEC (nextjs.md non-negotiable 3); TEST-1, TEST-2, TEST-9, TEST-10, TEST-12, TEST-13, TEST-14, TEST-17, TEST-19, TEST-20, TEST-21, TEST-25; nextjs-fullstack-standards: Server Components by default, Zod at boundaries, `Result` errors, shadcn primitives from the CLI only.

## 7. Interfaces

### Provided

No story lists `matching-lab-ui` in its deps (split.md: it is last). Nothing to provide.

### Consumed (pinned here so the owners' plans can match; consistent with split.md and the dep stories)

- **matching-lab-replay-api**
  - `GET /lab/candidates?limit=` → `{items: CandidateOut[], open_count: int}`; `CandidateOut {id: "p_NNNN", status: "OPEN"|"PROMOTED"|"DISCARDED", base_version: int, live_version: int, changes: dict, config_diff: [{key, before, after}], rationale, created_by, created_at, latest_replay_id: "rp_NNNN" | null, promoted_version: int | null}`. Ordered newest first; the current user's latest first when no `?candidate=` (story Assumption). `?candidate=` not in the list → page shows it via `items` filter; if absent, empty state.
  - `GET /lab/replays/{id}` → `ReplayResult` exactly as its AC 2, plus `candidate_id`, `base_version`, `window_days`.
  - `GET /lab/replays/{id}/stream` SSE: `event: progress` `{replay_id, status, done, total}` per step; terminal `event: progress` with `status` DONE|FAILED|STALE; heartbeat comment 15 s.
  - `GET /lab/replays/{id}/items.csv` (`text/csv`, `Content-Disposition`).
  - `POST /lab/candidates/{id}/replays {window_days}` → `{id: "rp_NNNN"}`; `POST /lab/candidates/{id}/promote {replay_id, reason, expected_version}` → `{config_version: int}`; 409 `STALE` (message "Live config moved to vN", `details[0].live_version`), 403 without CONFIG_WRITE; `POST /lab/candidates/{id}/discard` → 204.
  - `Permission.LAB_RUN = "lab:run"` in `/me` permissions.
- **assistant-chat-redesign**: `<LlmChat variant="compact" systemPromptKey="matching" context={{kind: "lab", candidate_id?: string}} tools={["LAB"]} chips={LAB_CHIPS} title="Lab assistant" onToolResult={(card: ResultCard) => void} />`; `ResultCard` discriminated on `kind`; `replay_card` carries at least `{kind: "replay_card", candidate_id, replay_id}`.
- **glass-theme-shell**: `TopBar {title, children}` slot, `GlassPanel/PanelHeader/PanelBody`, `Pill {tone, dot, mono}`, `MonoLabel`, `Meter {value, max, tone}`, `DiffBlock {lines: {op, text}[]}`, `ConfirmDialog {title, body, version, onConfirm({reason})}`, `KpiCard`, `DataTable`, `StateCard {kind, label, headline, body, actions}`, `SkeletonRows`, `StatusBadge`, nav count-source API.
- **live-progress-dashboard**: `useEventStream(path, {schema, onEvent, enabled})` → `{status, retry}` (today `web/lib/api/use-event-stream.ts`; moves to `web/hooks/use-event-stream.ts` per split.md) and dynamic stream-path support.

## Assumptions

- The board's "Replays never call Fusion" is rendered as "Replays never write to Fusion" (split.md, story AC 1).
- The browser's Export CSV link is the Next proxy `/api/lab/replays/{id}/items.csv`, which forwards to the API path `/lab/replays/{id}/items.csv` named in AC 4.
- The empty-state copy "or pick a matching key to try" is kept as text; a key picker is not built (not in the ACs); the chat is the way in.
- Promote sets `expected_version = candidate.live_version`; the "current vN" pill shows `replay.base_version` and is ok-toned only when it equals `live_version`; otherwise the stale state replaces the promote panel.
- After promote, `router.refresh()` re-reads the candidate (status PROMOTED, `live_version` N+1), which is what AC 5's "live version increments" checks.
- Window is fixed at 30 days in the UI (pill "N items · 30 days" uses `window_days`); changing it is a chat request.
