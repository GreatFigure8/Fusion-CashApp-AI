# Plan: engine-control-panel-ui

Story: [story.md](story.md). Design screen: **Engine** (`design/project/glass/Engine.dc.html`, design.md §3.3, §5). web/ only; no API, no migration.

## 1. Approach

- research.md a10 (extends a1 + a3): the board is a thin view over engine-control-api's `EngineService` endpoints; no business rule lives in web/ (CLAUDE.md "Ownership"). Reads REPORTS_READ, mutations ENGINE_CONTROL, both enforced by the API; the UI only disables.
- `app/(shell)/engine/page.tsx` is an async Server Component: `Promise.all` of `/engine/status`, `/engine/dead-letters`, `/engine/audit`, `/integrations/mcp/status`, `getMe()` (DF-4), each a `Result` passed down as props (RC-7, TS-30 discriminated states).
- One client leaf `EngineBoard` holds the live `EngineStatusOut`, fed by `useEventStream("/engine/stream")` (live-progress-dashboard's hook, SSE-24/25/26) through the existing `/api/stream/[...path]` proxy; `"/engine/stream"` is appended to `STREAM_PATHS`.
- Mutations: repo convention is Server Actions via `apiAction` (`app/(shell)/exceptions/_lib/actions.ts`), not route handlers. Story said "thin Next proxy route handlers"; nextjs.md API-5 / DF-11 say the app's own UI mutations are Server Actions. Deviation recorded under Assumptions.
- Every control (Pause, Resume, Drain, Throttle save, Replay) goes through glass-theme-shell's single `ConfirmDialog`; on success `router.refresh()` inside `startTransition` re-reads audit + DLQ (DF-22); a 409 keeps the dialog open with the reason (TEST-18, TEST-25).
- Built only from glass-theme-shell's `GlassPanel/PanelHeader/PanelBody`, `Pill`, `MonoLabel`, `Meter`, `DataTable`, `StateCard`, `SkeletonRows`, `TopBar`, `Button` warn variant (non-negotiable 7). No per-page copies, no `components/ui` edits.
- Next 16: read `web/node_modules/next/dist/docs` (research.md dissent, web/AGENTS.md) before coding; `PageProps`-free page (no params), `error.tsx` per TEST-20.

Rule ids applied: TS-1, TS-5, TS-10, TS-19, TS-20, TS-23, TS-28, TS-30, TS-31, TS-32, TS-34; RC-5, RC-6, RC-7, RC-38; DF-3, DF-4, DF-10, DF-11, DF-12, DF-13, DF-14, DF-15, DF-22; API-5, API-8, API-10, API-12; SSE-7, SSE-23, SSE-24, SSE-25, SSE-26; SEC-5, SEC-16, SEC-17, SEC-21, SEC-22; RT-8, RT-9, RT-22; TEST-1, TEST-2, TEST-12, TEST-14, TEST-17, TEST-18, TEST-20, TEST-21, TEST-25, TEST-37.

## 2. Files

Create (web/):

| Path | Purpose |
|---|---|
| `app/(shell)/engine/page.tsx` | Async Server Component. `getMe()`, then `RequirePermission permission="reports:read" role="VIEWER"`; `Promise.all` of the four API reads; passes `{status, deadLetters, audit, mcp, canControl, actor}` (narrow DTOs, SEC-16) to `EngineBoard`. `export const metadata: Metadata = { title: "Engine" }`. |
| `app/(shell)/engine/loading.tsx` | Station-grid skeleton: 12 `SkeletonRows` card skeletons + caption "Reading consumer lag…" (`StateCard kind="loading"`). |
| `app/(shell)/engine/error.tsx` | `'use client'` boundary (TEST-20/21): generic message, `retry()`. |
| `app/(shell)/engine/_lib/actions.ts` | `"use server"`. `pauseStationAction`, `resumeStationAction`, `drainStationAction` (`{station, reason, expectedVersion}`), `setThrottleAction` (`{perStage 1..32, applyPerReceipt 1..8, reason, expectedVersion}`), `replayDeadLettersAction` (`{eventIds 1..100, reason}`); each `apiAction(schema, …)` calling the API (which authorizes with the user's token, DF-12/SEC-21). |
| `lib/engine/schemas.ts` | Zod: `stationName` (`/^[a-z_.]{1,40}$/`), `reason` (trim, 1..500), `expectedVersion` (int ≥ 0), throttle bounds (`THROTTLE_BOUNDS = {perStage:{min:1,max:32}, applyPerReceipt:{min:1,max:8}} as const`), `engineStatusEventSchema` (validates SSE `status` frames; type from `Schemas["EngineStatusOut"]` via `z.custom` guard on the keys the board reads, like `lib/flow/stream-schemas.ts`). |
| `lib/engine/view.ts` | Pure helpers (unit-testable): `stateCounts(stations) -> {running, paused, draining}` (PAUSED+DRAINED count as paused), `stateTone(state) -> PillTone` (RUNNING ok, PAUSED/DRAINED warn, DRAINING accent), `isSaturated(s)` (`limit > 0 && in_flight >= limit`), `inFlightLabel(s)` (`"in-flight 7 / 16"`, `"n/a"` when limit 0), `primaryControl(state) -> "pause"|"resume"`, `canDrain(state)`, `controlsEnabled({canControl, busHealthy})`, `secondsAgo(lastAt, now)`, `CONFLICT_MESSAGE`, `copyFor(action, station, status)` (dialog title/body/confirmLabel). |
| `components/engine/engine-board.tsx` | `"use client"`. Holds status state (initial from props, replaced on each SSE `status` frame), a 1 s ticker for "updated N s ago", selection, pending action; renders `TopBar` + panels; `useEventStream`'s `retry` and `router.refresh()` drive Retry. |
| `components/engine/engine-top-pills.tsx` | The TopBar slot content: env/Live come from TopBar; adds "Lag streamed · updated N s ago", `Admin only · audited` (locked), "Fusion reads · MCP healthy N ms" (ok) or "MCP unreachable" (err), right slot "OCI Streaming · group <consumer_group>". |
| `components/engine/stations-panel.tsx` | `GlassPanel` "Stations", header pills `N running · N paused · N draining`, grid `repeat(auto-fill,minmax(210px,1fr))`, 12 `StationCard`s in API order. |
| `components/engine/station-card.tsx` | Mono name + state `Pill`; `lag N · N/min · dlq N`; 5px `Meter` (tone warn when saturated); "in-flight N / M"; `Pause`/`Resume` (`Button` warn) and `Drain`; paused/drained card gets warn border (`border-warn/40`); disabled + "· needs admin" suffix when `!canControl`. |
| `components/engine/throttle-panel.tsx` | `GlassPanel` "Throttle" + `config vN` pill; two native range inputs (`concurrency.per_stage` 1-32, `concurrency.apply_per_receipt` 1-8, accent-hi `accent-color`), mono value readouts, helper "Fusion applies take about 6 s a line; this is the back-pressure.", `Save throttle…` (disabled until changed or `!canControl`). Initial values from `EngineStatusOut` throttle fields (see §7 note). |
| `components/engine/audit-list.tsx` | `GlassPanel` "Audit" + label "who · when · why"; rows: mono time (44px col), name (500), action text, reason quoted in `--soft`. Empty: "No engine changes recorded yet." |
| `components/engine/dlq-table.tsx` | `GlassPanel` "Dead-letter queue", header pill "N events" (`dlq_total`) and primary "Replay N selected…"; `DataTable` cols Select (checkbox, aria-label "Select <event_id>"), Event (mono), Stage (mono), Item (`<Link href={/items/${id}}>` with `formatWorkItemId`), Error (`Pill` err mono), Attempts (right/mono), Dead since (`formatLockTime`/`formatDateTime`). Empty: `StateCard kind="empty"` "No dead letters" / "Every event is inside its retry budget." |
| `components/engine/replay-result.tsx` | After replay: "Replayed N" list of event ids (ok) and "Skipped N" list `event_id — why` (muted/warn). |
| `components/engine/engine-action-dialog.tsx` | `"use client"`. Maps a pending `EngineAction` (`{kind:"pause"|"resume"|"drain", station} | {kind:"throttle", perStage, applyPerReceipt} | {kind:"replay", eventIds}`) to `ConfirmDialog` props (`title`, `body`, `confirmLabel`, `tone="warn"`, `expectedVersion`, actor), calls the matching action; on `!ok && status===409` keeps open with `CONFLICT_MESSAGE` and the reason; other errors show `ErrorAlert` text inside the dialog, kept open. |
| `components/engine/engine-states.tsx` | `BusUnavailable` (`StateCard kind="error"` "Bus health unavailable", "Controls are disabled until lag can be read.", Retry) and the operator banner ("Read-only · Pause, drain, throttle and replay need admin."). |

Change (web/):

| Path | Change |
|---|---|
| `lib/api/stream-paths.ts` | Append `"/engine/stream"` to `STREAM_PATHS` (no-op if glass-theme-shell already appended it for the footer; merger keeps one entry). |
| `lib/permissions.ts` | Add `"/engine": { permission: "reports:read", role: "VIEWER" }` to `ROUTE_PERMISSIONS`; add `export const ENGINE_CONTROL = "engine:control" as const` (string must equal the API enum; type-checked against `Schemas["Permission"]` with `satisfies`). |
| `tests/support/fixtures/dto.ts` (tester, step 5) | Engine fixtures (12 stations, DLQ rows, audit rows, MCP status). |

Not changed: `components/shell/nav.ts` (glass-theme-shell owns the Engine entry `EN`, `reports:read`), `components/common/*`, `components/ui/*`, any `api/` file, `app/(shell)/layout.tsx`.

## 3. Test plan (written and run only at step 5)

Unit (Vitest, jsdom, `web/tests/engine/`; Client Components and pure modules only, TEST-2):

| AC | Test file | Tests |
|---|---|---|
| 2 | `tests/engine/view.test.ts` | `stateCounts counts PAUSED and DRAINED as paused and DRAINING as draining`; `isSaturated is true only when limit>0 and in_flight>=limit`; `inFlightLabel renders n/a when limit is 0`; `stateTone maps RUNNING ok PAUSED warn DRAINING accent` |
| 2 | `tests/engine/station-card.test.tsx` | `renders mono name, state pill and lag · N/min · dlq line`; `meter tone is warn when saturated`; `paused card shows Resume in warn style and the warn border`; `running card shows Pause and Drain` |
| 3 | `tests/engine/engine-action-dialog.test.tsx` | `pause dialog names the station and says in-flight finish, nothing is lost`; `confirm calls pauseStationAction with reason and expected version`; `cancel calls no action` |
| 4 | `tests/engine/throttle-panel.test.tsx` | `sliders are bounded 1-32 and 1-8`; `shows the back-pressure helper`; `Save throttle… is disabled until a value changes` |
| 5 | `tests/engine/dlq-table.test.tsx` | `item column links to /items/[id]`; `Replay N selected… counts checked rows and is disabled at 0`; `replay result lists replayed and skipped events with reasons` |
| 6 | `tests/engine/engine-states.test.tsx` | `empty DLQ shows No dead letters and the retry-budget body`; `bus unavailable shows Retry and disables every control`; `operator view renders controls disabled with needs admin` |
| 7 | `tests/engine/engine-action-dialog.test.tsx` | `409 keeps the dialog open, keeps the reason and shows the conflict message` |
| 3,4,5 | `tests/engine/actions.test.ts` | `action schemas reject an empty reason`; `setThrottle schema rejects per_stage 33 and apply_per_receipt 0`; `replay schema rejects an empty event id list` (TEST-10: schemas tested as plain functions) |
| 2 | `tests/engine/schemas.test.ts` | `engineStatusEventSchema accepts an EngineStatusOut frame and drops one missing stations` |
| 8 | `tests/engine/nav-permissions.test.ts` | `Engine nav entry is visible with reports:read and hidden without it` (over glass-theme-shell's `visibleNav`); `ROUTE_PERMISSIONS["/engine"] needs reports:read`; `controlsEnabled is true only with engine:control and a healthy bus` |

E2E (Playwright, `web/e2e/engine.spec.ts`, production build, mock API in `tests/support/mock-api-server.ts` programs `/me`, `/engine/*`, `/integrations/mcp/status` and the `/engine/stream` SSE; checked against the **Engine** board at 1440 wide; visibility-aware locators, TEST-14):

| AC | Test name |
|---|---|
| 1 | `engine top bar shows Engine, env, Live, lag streamed, Admin only audited, MCP healthy and the consumer group` |
| 1 | `engine top bar shows MCP unreachable when the MCP status call fails` |
| 2 | `engine shows 12 station cards with state pills, lag line, in-flight meter and header counts` |
| 2 | `engine station values update from the stream without a reload` |
| 3 | `pausing a station asks for a reason, then shows PAUSED and a new audit row` |
| 3 | `drain asks for a reason through the confirm dialog` |
| 4 | `throttle sliders save through the confirm dialog with the config version` |
| 5 | `dead-letter replay of selected events lists replayed and skipped events` |
| 6 | `engine shows the station skeleton while consumer lag is read` |
| 6 | `engine shows No dead letters when the queue is empty` |
| 6 | `engine shows Bus health unavailable with controls disabled and Retry recovers` (TEST-17) |
| 6 | `operator sees every control disabled with needs admin` |
| 7 | `a 409 on pause keeps the dialog and reason open with the conflict message` |

Total: 28 unit + 13 e2e = 41 tests.

### Design checklist (Engine board; coder ticks each in validation.md, lesson L-admin-act-for-absent-owner-1)

- [ ] Top bar: title "Engine"; env pill (warn, from TopBar); Live pill with glowing dot; "Lag streamed · updated N s ago"; `Admin only · audited` (locked tone); "Fusion reads · MCP healthy N ms" (ok) / "MCP unreachable" (err); right "OCI Streaming · group <consumer_group>".
- [ ] Stations `GlassPanel` header "Stations" + pills "N running" (ok) · "N paused" (warn) · "N draining" (accent).
- [ ] Grid `auto-fill minmax(210px,1fr)`, gap 12; card border `--line`, radius 12, bg white/2, padding 12x14.
- [ ] Card: mono name; state pill Running ok / Paused warn / Draining accent / Drained warn; `lag N · N/min · dlq N`; 5px `Meter` accent-hi, warn when saturated; "in-flight N / M" ("n/a" when no limit); `Pause|Resume` warn-style `Button`, `Drain` outline; paused border `#ffc96b66`.
- [ ] Throttle `GlassPanel` "Throttle" + "config vN"; mono keys `concurrency.per_stage` and `concurrency.apply_per_receipt`; range accent `--acc-hi`; helper copy exact; "Save throttle…".
- [ ] Audit `GlassPanel` "Audit" + "who · when · why"; mono time 44px column; name weight 500; reason in curly quotes, `--soft`.
- [ ] DLQ `GlassPanel` "Dead-letter queue" + pill "N events" + primary "Replay N selected…"; header cols Select, Event, Stage, Item, Error, Attempts, Dead since (mono uppercase, `DataTable`); error `Pill` err mono; horizontal scroll on narrow.
- [ ] `ConfirmDialog` (scrim `#05060ab3` + 2px blur, from shared component): title "Pause the <station> station?", "audited" label, body "New deliveries stay uncommitted on the bus, so nothing is lost. The N <station>s in flight finish first.", "Reason · required" textarea, "Recorded as <name · role> · <date> UTC · expected version N", Cancel + warn-filled "Pause <station>". Same pattern for Resume ("Resume <station>"), Drain ("Drain <station>"), Throttle ("Save throttle"), Replay ("Replay N events").
- [ ] Conflict copy: "Someone changed the engine first; review and try again."
- [ ] Loading: card skeletons + "Reading consumer lag…". Empty DLQ: label "Empty · DLQ", "No dead letters", "Every event is inside its retry budget.". Error: label "Error · bus", "Bus health unavailable", "Controls are disabled until lag can be read.", Retry. Operator: label "Operator view", "Read-only", buttons "Pause · needs admin" etc., disabled.
- [ ] Two-up cards (Throttle/Audit) `auto-fit minmax(340px,1fr)`; no horizontal page scroll at 375 px.
- [ ] Shared components only: `GlassPanel`, `PanelHeader`, `PanelBody`, `Pill`, `MonoLabel`, `Meter`, `DataTable`, `StateCard`, `SkeletonRows`, `ConfirmDialog`, `TopBar`, `Button` warn, `ErrorAlert`.

## 4. Data

None. No ORM model, no Alembic migration (split.md lists none for this story). All data comes from engine-control-api (`ENGINE_AUDIT`, `engine.paused_stations`) and fusion-mcp-transport.

## 5. Config / env

- No new env vars; uses existing `API_BASE_URL` (server-only, `lib/env.ts`).
- DB-stored keys read (through the API, never directly): `concurrency.per_stage`, `concurrency.apply_per_receipt`, `engine.paused_stations` (engine-control-api), `mcp.*` (status only). None owned here.

## 6. Risks and gates

- **Shared contract drift.** Pinned names below come from dep stories; no dep plan existed when this was written. The coder types every payload from `Schemas[...]` in the regenerated `lib/api/schema.d.ts`; if a field name differs, follow the generated schema and record it in validation.md. The coder starts only from the sprint tip after wave deps merge (L-comparison-wizard-from-fusion-2) and never stubs a dep's file.
- **ConfirmDialog needs**: an `open`/`onOpenChange` pair, an actor `{name, role}` for the "Recorded as" line, an inline error slot, and an `onConfirm` that can resolve without closing (to keep the dialog open on 409). If glass-theme-shell's dialog closes unconditionally, raise it to that owner; do not fork the component.
- **Throttle initial values**: `EngineStatusOut` as pinned lists `config_version` and per-station `limit` but no explicit throttle pair. Read `per_stage` from the API if exposed (expected `throttle: {per_stage, apply_per_receipt}`); otherwise derive per_stage from a non-apply station's `limit`, and flag the missing apply_per_receipt value to engine-control-api's owner (never read config from the web directly). Recorded as an Assumption.
- **Operators and MCP status**: `GET /integrations/mcp/status` needs CONFIG_READ; OPERATOR and VIEWER hold it today. A 403 renders the pill as "MCP status unavailable" (muted), never an error page.
- **SSE**: one stream per tab; the footer (glass-theme-shell) also opens `/engine/stream`. Accept two connections for now (HTTP/2 behind OCI LB); note in validation.md.
- Coder gates (lint + type-check only, no tests): `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`. No api/ change, so no ruff/pyright run needed; if the coder touches api/ anyway: `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`.

## 7. Interfaces provided

No story lists `engine-control-panel-ui` in its deps (engine-control-api names it only as out of scope). Nothing to pin for consumers.

Interfaces this story consumes (pinned as used, from split.md and dep stories):

- glass-theme-shell: `ConfirmDialog{title, body, confirmLabel, tone, expectedVersion, onConfirm({reason})}`, `Pill{tone: ok|accent|warn|err|locked|muted, dot?, mono?}`, `Meter{value, max, tone, size: 5|6}`, `GlassPanel/PanelHeader/PanelBody`, `DataTable`, `StateCard{kind: loading|empty|error|denied, label, headline, body, actions}`, `SkeletonRows`, `TopBar` (title + slot props), `Button variant="warn"`, `visibleNav(me)` with an Engine entry on `reports:read`.
- engine-control-api: `GET /engine/status -> EngineStatusOut{stations: [{name, state: RUNNING|PAUSED|DRAINING|DRAINED, lag, throughput_per_min, dlq_depth, in_flight, limit}], bus_healthy, total_lag, dlq_total, pollers, region, consumer_group, config_version}`; SSE `GET /engine/stream` event `status` (same shape) + 15 s heartbeat; `POST /engine/stations/{station}/pause|resume|drain {reason, expected_version}` (409 on version conflict); `PUT /engine/throttle {per_stage, apply_per_receipt, reason, expected_version}`; `GET /engine/dead-letters?station=&offset=&limit= -> [{event_id, stage, item_id, error_code, attempts, dead_since}]`; `POST /engine/dead-letters/replay {event_ids, reason} -> {replayed, skipped: [{event_id, why}]}`; `GET /engine/audit -> [{at, actor_name, actor_role, action, stations, before, after, reason, config_version}]` (field names per its `ENGINE_AUDIT` columns); Permission `engine:control`.
- fusion-mcp-transport: `GET /integrations/mcp/status -> McpStatusOut{healthy, latency_ms, server_url, client_id, source, secret_in_vault, last_call}`.
- live-progress-dashboard: `useEventStream<T>(path: StreamPath, {onEvent, schema?, onStreamError?, enabled?}) -> {status, retries, retry}` at `web/hooks/use-event-stream.ts` (same signature as today's `lib/api/use-event-stream.ts`).

## Assumptions

- Mutations are Server Actions in `app/(shell)/engine/_lib/actions.ts` (repo convention, nextjs.md API-5/DF-11), not route handlers; the story's "thin Next proxy route handlers" is satisfied by the existing `/api/stream/[...path]` proxy for SSE.
- Header counts: PAUSED and DRAINED count as paused; DRAINING as draining (the board's sample counts don't sum to 12).
- Drain is offered on RUNNING and PAUSED stations; hidden-disabled on DRAINING/DRAINED. Resume replaces Pause on PAUSED and DRAINED.
- "updated N s ago" counts from the last SSE `status` frame (or the server read on first render).
- Throttle initial values come from an EngineStatusOut throttle field if present; see Risks.
- The board's 1-32 / 1-8 slider bounds are the API's validation bounds (story assumption); the web schema repeats them only for early feedback, the API remains the control.
