# s19-ui-shell-flow-monitor: plan

Issue #19, wave 5. Paths: `cashapp/` = `api/src/cashapp/`. Merges after s13, s15, s16, s17, s22 and s35 in this wave, and before s20, s21 and s41, which consume its shared components, `useFlowStream` and the dto fixtures.

## Standards followed

- **CLAUDE.md:**
  - Layers depend only downward:
    - Routers do validation, `require_permission` and JSON shaping only.
    - `services/flow_query.py` computes everything.
    - `data/repositories/flow_query.py` is the only new code touching the ORM.
  - One status enum. The web never redeclares `ItemState`, `PaymentStatus`, `LineStatus` or `Stage`; it types them from `schema.d.ts`.
  - Money travels as `MoneyStr` strings with a currency.
  - One error shape (s01 `ApiError`).
  - No new poller. `/flow/stream` is a per-connection view of the database (story assumption).
  - The UI hides and the API enforces.
  - No PII in logs: part bytes and payload JSON are never logged.
- **python-web-app:** `Annotated` dependencies (`UowFactoryDep` from s04's `cashapp/api/deps.py`, `ObjectStoreDep`), routers auto-discovered (no `main.py` edit), sse-starlette `EventSourceResponse`, and services callable without `Request`.
- **nextjs-fullstack-standards:**
  - Server Components by default, with `"use client"` only on interactive leaves (stream provider, data-table, artifact-viewer, command palette, item view panes).
  - Zod at boundaries: route params, search params, SSE payloads and action input.
  - `Result` values with no throws across layers.
  - Named exports and kebab-case files.
  - shadcn primitives only from the CLI: add `dropdown-menu` and `avatar`, which s01 lacks.
- **BMN `references/nextjs.md` rule ids applied:**
  - NN1 / RT: await `params` and `searchParams`.
  - NN3 / SEC-3: auth is checked in every server action through `apiAction`; the API is the control.
  - NN4: no `route.ts` beside a `page.tsx`.
  - NN7 / TS: `PageProps<"/flow/[stage]">`, `LayoutProps`, `RouteContext<"/api/items/[id]/parts/[n]">`.
  - NN8: only `NEXT_PUBLIC_ENV_LABEL`, read through `@/lib/env.public`.
  - NN12: the part proxy passes the upstream `ReadableStream` to `new Response`.
  - NN13: no `'use cache'`, so live data stays uncached.
  - NN14: Zod-validated inputs.
  - SSE-24/25: s31 `useEventStream` with a schema per event.
  - RC: Suspense, plus `loading.tsx` skeletons per route.
  - TEST-9: route handlers are called as plain functions.
  - TEST-13: Playwright runs on the per-checkout port.
  - TEST-35: no message text in logs.
- **design.md** §2 tokens (already in s01 `globals.css`), §3 shell, §4 flow monitor, §9 shared components (one each), and §10 responsive.
- **research.md a3:** shadcn, Zod, openapi-typescript, and pdfjs-dist (already pinned by s01; no lockfile edits).

## Files to touch

### API (Python), all new unless noted

| Path | Content |
|---|---|
| `cashapp/api/routers/flow.py` | `router`: `GET /flow/summary`, `GET /flow/stream` (SSE), `GET /flow/stages/{tile}/items` |
| `cashapp/api/routers/items.py` | `router`: `GET /items/{item_id}`, `GET /items/{item_id}/history`, `GET /items/{item_id}/parts/{part_no}`, `GET /search` |
| `cashapp/api/schemas/flow.py` | Response models for the summary, tiles, stage items and stream frames, each with a `from_data()` builder |
| `cashapp/api/schemas/items.py` | Response models for item detail, history and search, each with a `from_data()` builder |
| `cashapp/api/storage_deps.py` | `get_object_store()` and `ObjectStoreDep`. **If s45 already shipped it, reuse it and don't create the file** (non-negotiable 7). |
| `cashapp/services/flow_query.py` | All read logic: summary, tiles, throughput, p95 dwell, aging, stage items, item detail, history, part open, search, changed-since, `FlowSummaryCache`, `CohereUtilisationSource` / `BacklogProgressSource` adapters |
| `cashapp/services/poller_heartbeat.py` | `record_poller_heartbeat`, `PollerHeartbeatHook` (s06 `CycleHook`) |
| `cashapp/data/repositories/flow_query.py` | `FlowQueryRepository` (every new query) |
| `cashapp/data/models/poller_heartbeat.py` | ORM `PollerHeartbeat` (`poller_heartbeat`), plus module-level `Index` objects on `work_item.updated_at`, `work_item.created_at` and `work_item_history(action, at)`, so s02's model file isn't edited |
| `cashapp/data/repositories/poller_heartbeat.py` | `PollerHeartbeatRepository` |
| `api/alembic/versions/s19_flow_monitor.py` | The one revision (see Migrations) |
| `cashapp/pollers/intake/hooks.py` | **Append only (s06 file):** guarded `CYCLE_HOOKS.append(PollerHeartbeatHook("intake-poller"))`, written the same way as s45 |
| s14's receipt-watcher cycle (`cashapp/pollers/receipt_watcher/…`, path confirmed at coding) | **One appended call (s14 file):** `await record_poller_heartbeat(uow, "receipt-watcher", now)` at the end of each cycle, in that cycle's UoW |
| `api/tests/support/flow.py` | Owned support: `seed_flow(uow, clock, …)`, which seeds items, transitions, lines and ledger rows for the summary tests |
| tests in the TEST PLAN | Written in step 5 only |

### Web, all new unless noted

| Path | Content |
|---|---|
| `web/app/(shell)/layout.tsx` | Server: `requireSession()` (s04), `getMe()`, then `<AppShell me envLabel>` |
| `web/app/(shell)/flow/page.tsx`, `loading.tsx`, `error.tsx` | Flow monitor. The server fetches the initial `/flow/summary` and `/me`; the client is `FlowMonitor`. |
| `web/app/(shell)/flow/actions.ts` | `"use server"`: `refreshFlowSummary()`, `pauseBacklogBatch(id)`, both through `apiAction` |
| `web/app/(shell)/flow/[stage]/page.tsx`, `loading.tsx` | Stage drill-down table |
| `web/app/(shell)/items/[id]/page.tsx`, `loading.tsx`, `not-found.tsx` | Three-pane item view |
| `web/app/signed-out/page.tsx` | No shell. "You've been signed out." plus a "Sign in again" link to `/auth/sign-in`. |
| `web/app/api/items/[id]/parts/[n]/route.ts` | `GET`: Zod params, then `apiRaw` passthrough (content-type and `Content-Disposition: inline` preserved, `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`) |
| `web/app/page.tsx` | **Edit (s01 placeholder, which s01 says s19 replaces):** `redirect("/flow")` |
| `web/app/layout.tsx` | **Edit (s01):** wrap children in a `ThemeProvider` (next-themes, `attribute="class"`, `defaultTheme="system"`) and add the sonner `<Toaster />`. `suppressHydrationWarning` on `<html>`. |
| `web/lib/api/client.ts` | **Append (s31 file):** `apiRaw()`, which reuses the internal `buildApiRequest` (DRY) and returns the upstream `Response` on 2xx and the same `ApiError` mapping otherwise |
| `web/lib/me.ts` | `server-only`: `getMe()` (React `cache`), `hasPermission`, `ROUTE_PERMISSIONS` |
| `web/lib/format.ts` | Client-safe: `formatMoney`, `formatWorkItemId`, `parseWorkItemId`, `humanizeEnum`, `formatDuration`, `formatRelative` |
| `web/lib/flow/stream-schemas.ts` | Zod `flowSummarySchema` and `itemChangedSchema`, typed `z.ZodType<Schemas[...]>` so that drift fails `tsc` |
| `web/components/common/status-badge.tsx` | `StatusBadge` + `STATUS_TOKENS` maps |
| `web/components/common/money.tsx` | `Money` |
| `web/components/common/data-table.tsx` | `DataTable<T>` (TanStack v9) |
| `web/components/common/kpi-card.tsx` | `KpiCard` |
| `web/components/common/empty-state.tsx` | `EmptyState` |
| `web/components/common/error-alert.tsx` | `ErrorAlert` |
| `web/components/common/history-timeline.tsx` | `HistoryTimeline` |
| `web/components/common/artifact-viewer.tsx` (+ `artifact-viewer/pdf-pages.tsx`, `artifact-viewer/highlight-layer.tsx`) | `ArtifactViewer` |
| `web/components/common/live-indicator.tsx` | `LiveIndicator` |
| `web/components/common/require-permission.tsx` | `RequirePermission`, `ForbiddenState` (the unauthorized state, reused by s20, s21 and s41) |
| `web/components/shell/app-shell.tsx` | `"use client"` sidebar, header, breadcrumb, env badge, user menu, `FlowStreamProvider` |
| `web/components/shell/nav.ts` | `NAV_ITEMS` (`href`, `label`, `icon`, `permission`) and `visibleNav(me)` |
| `web/components/shell/breadcrumbs.tsx` | Breadcrumb from the pathname, plus `?from=<STAGE>` for item pages |
| `web/components/shell/command-palette.tsx`, `web/components/shell/actions.ts` | ⌘K palette plus `"use server"` `searchItems(q)` |
| `web/components/shell/env-badge.tsx`, `user-menu.tsx` | Env badge and user menu |
| `web/components/shell/flow-stream.tsx` | `"use client"`: `FlowStreamProvider` and `useFlowStream()` (one SSE connection per tab) |
| `web/components/flow/flow-monitor.tsx`, `stage-tile.tsx`, `sparkline.tsx`, `backlog-bar.tsx`, `stage-items-table.tsx` | Flow screens |
| `web/components/items/item-view.tsx`, `item-header.tsx`, `extraction-tabs.tsx`, `lines-table.tsx`, `highlight-context.tsx` | Item view |
| `web/components/ui/dropdown-menu.tsx`, `avatar.tsx` | `npx shadcn@latest add dropdown-menu avatar` (CLI output only) |
| `web/lib/api/openapi.json`, `web/lib/api/schema.d.ts` | Regenerated by `npm run api:sync` (never hand-merged) |
| `web/tests/support/fixtures/dto.ts` | Owned test support (see Interfaces) |
| `web/tests/support/mock-api-server.ts`, `web/e2e/global-setup.ts` | Owned Playwright support: a programmable HTTP and SSE mock API |
| `web/playwright.config.ts` | **Append (s01 file):** `globalSetup: "./e2e/global-setup.ts"` and `webServer.env.API_BASE_URL = http://127.0.0.1:${MOCK_API_PORT ?? 3199}` |
| tests in the TEST PLAN | Written in step 5 only |

## Design

### API: tiles and the summary

`FlowTile` is a `StrEnum` in `services/flow_query.py`. It holds every `Stage` value in `PIPELINE_ORDER`, with `AWAITING_RECEIPT` inserted right after `MATCH_RECEIPT`. The order comes from s02's `PIPELINE_ORDER` once, and the web renders tiles in response order.

Per tile:

| Field | How it's computed |
|---|---|
| `in_queue` | PENDING count |
| `in_progress` | IN_PROGRESS count |
| `errors` | ESCALATED at the stage, plus PENDING/IN_PROGRESS rows with `last_error_code` set |
| `AWAITING_RECEIPT` tile | `in_queue` = AWAITING_RECEIPT count; `awaiting_buckets` comes from `awaiting_since` ages (0–2d / 3–7d / 8–30d / >30d, by whole days) |
| `DONE` tile | `in_queue` = DONE items whose `updated_at` falls today |

The stage and state counts come from s29's `collect_queue_stats(uow)`, which is reused, not re-queried.

**Throughput:** `throughput_per_min` is a 60-element list, oldest minute first, ending at the current minute. Each element counts the `STAGE_TRANSITION` history rows in the last 60 minutes where `from_stage = S` and (`to_stage != S`, or `to_state ∈ {DONE, AWAITING_RECEIPT, ESCALATED}`). The query uses `IX_WIH_ACTION_AT`.

**p95 dwell:** `p95_dwell_s` is nearest-rank p95 over those same leave rows. Each row's dwell is `leave.at − entry.at`, where the entry is the latest earlier `STAGE_TRANSITION` row of that item with `to_stage = S` and `from_stage != S` (INTAKE falls back to `created_at`). That's one batched query for the entries (chunks of 500 ids). `null` when there were no leaves.

**KPIs** (the day is the UTC calendar day; see Assumptions):

| KPI | Definition |
|---|---|
| `in_today` | Items created today that are not envelopes (no children) |
| `auto_applied_pct` | Numerator: DONE today with `payment_status ∈ SUCCESS_STATUSES` and no `HUMAN_ACTION` history. Denominator: DONE or ESCALATED today. 0 items gives `null`. Rounded to 1 dp. |
| `applied_by_currency` | Sum of s15 `APPLICATION_LEDGER.AMOUNT` with STATUS=APPLIED and `APPLIED_AT` today, joined to `WORK_ITEM.CURRENCY`. `MoneyStr`, sorted by currency. |
| `needs_person` | ESCALATED count |

**Other summary fields:**

- `pollers`: rows from `POLLER_HEARTBEAT` for `intake-poller` and `receipt-watcher`; `last_cycle_at` is `null` when a poller has never run.
- `cohere_utilisation_pct`: from `CohereUtilisationSource`. The default adapter calls s36's `cohere_utilisation(window_minutes=60)` and returns its `utilisation_pct`. It returns `null` on any exception (logged by type only) or when the cluster isn't configured.
- `backlog`: from `BacklogProgressSource`. The default adapter calls s35's service for RUNNING batches and maps them to `{id, name, processed, total, eta_minutes, status}`. The coder adapts both adapters to the merged s35 and s36 signatures. Each adapter is the one place that touches its source.

**`FlowSummaryCache`:** process-local, `SUMMARY_CACHE_SECONDS = 4.0`, and single-flight through an `asyncio.Lock`. So N stream connections plus the REST endpoint cost one computation per 4 s. Each computation runs in its own UoW, which is rolled back (read-only).

### API: `/flow/stream`

- `EventSourceResponse(gen(), ping=15)`, guarded by `require_permission(ITEMS_READ)`.
- **Start watermark:** a `Last-Event-ID` that parses as an ISO datetime within the last 10 minutes; otherwise `now`.
- **The loop runs until `await request.is_disconnected()`:**
  1. Open a short UoW.
  2. `summary = await cache.get(...)` and yield the `summary` frame.
  3. Query `changed = repo.changed_since(watermark - OVERLAP_SECONDS(10), limit=500)` (ordered `updated_at, id`, on `IX_WORK_ITEM_UPDATED_AT`; this is the one item query per tick).
  4. Yield `item_changed` for each row whose `(id, version)` hasn't been sent in the overlap window (a bounded dict). The overlap catches transactions that commit late.
  5. Set the event `id` to the new watermark (max `updated_at`) as ISO, and close the UoW.
  6. `await asyncio.sleep(STREAM_TICK_SECONDS = 5.0)`.

  No session is held across the sleep. Cancellation is clean.
- Frame data is the JSON of `FlowSummaryOut` or `ItemChangedOut`. The route declares `responses={200: {"model": FlowStreamFrameOut, "content": {"text/event-stream": {}}}}`, so both schemas land in OpenAPI and `schema.d.ts`.

### API: stage items, item detail, history, parts and search

- **`GET /flow/stages/{tile}/items?state=&page=`**
  - `tile: FlowTile` (an invalid value gives the framework's 422). `state: ItemState | None`. `page ≥ 1`, page size 50.
  - Ordered `priority DESC, created_at ASC, id`. `AWAITING_RECEIPT` filters on state.
  - `lock` = `LockInfoOut.from_info(lock_info_for(item, now))` (s40).
  - `received_at` is `WORK_ITEM.CREATED_AT`.
- **`GET /items/{item_id}`**: 404 `item_not_found`. Built from:
  - the item;
  - its lock;
  - s09 `AdjudicationRepository.latest_for`: `final`, `provenance` (`provenance_json()`), `disagreements`, `confidence` and `missing_reader`. A purged adjudication gives `final: null` and `purged: true`.
  - s08 `ExtractionReadingRepository.latest_for` for `reader_a`/`reader_b`: `{status, model_id, output, attempt, created_at}`.
  - s06 `ArtifactPartRepository.for_item`: `part_no`, `kind`, `media_type`, `purged`.
  - s15 `LineResultRepository.for_item` joined with `ApplicationLedgerRepository.for_item` by `line_no`: `fusion_balance` = `BALANCE_BEFORE`, `applied_amount`, `line_status`, `fusion_result_code` (the ledger's `ERROR_CODE`, or the first code in `RESPONSE_MESSAGES`, else `null`).
  - s11 `CustomerResolutionRepository.latest_for` for `resolution`: anchor, related, method, currency, flags.
  - `receipt`: s13 `ReservationRepository.active_for_item`, else the newest CHOSEN `MATCH_CANDIDATE`, giving `{receipt_id, receipt_number, decided_by, score, reservation_status}`, or `null`.
- **`GET /items/{item_id}/history?page=`** (size 200): s02 `HistoryRepository.for_item`, giving rows `{id, at, action, actor_kind, actor_id, actor_name, from_stage, to_stage, from_state, to_state, error_code, reasoning, payload, purged}`. A purged payload is `null`.
- **`GET /items/{item_id}/parts/{part_no}?variant=original|text`**
  - Looks up the part row.
  - `variant=text` reads `text_key_for(object_key)` as `text/plain; charset=utf-8`; 404 `part_text_not_found` when the part has no text object.
  - `ObjectStore.get` returns the bytes as `Response(data, media_type=row.media_type)` with `Content-Disposition: inline; filename="part-<n>.<ext>"` (no source filename, so no PII), `X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox` and `Cache-Control: private, no-store`.
  - Errors: 404 `part_not_found`, and 410 `artifact_purged` when `purged_at` is set or `ObjectNotFound` is raised (s45 note).
  - Bytes and keys are never logged.
- **`GET /search?q=`** (1–100 chars, stripped, limit 10, `items:read`):
  - `WI-<n>`, or digits only, matches the id.
  - Otherwise it's an exact match, then a prefix match, on s13 receipt numbers (reservation and chosen candidate) and s15 `LINE_RESULT.TRANSACTION_NUMBER`.
  - Returns hits `{item_id, kind: "item"|"receipt"|"invoice", match, stage, state}`, deduplicated by (item, kind).

### API: poller heartbeat

- `POLLER_HEARTBEAT` (`NAME` VARCHAR2(64) PK, `LAST_CYCLE_AT`, `LAST_STATUS` VARCHAR2(20), `UPDATED_AT`).
- `record_poller_heartbeat` upserts the row: select for update, then update or insert. It flushes and never commits.
- `PollerHeartbeatHook.on_cycle(container, now)` opens its own UoW, records the heartbeat and commits.
- This only writes state. It isn't a new loop (non-negotiable 5).

### Web: shell

- **`(shell)/layout.tsx`** (server):
  1. `await requireSession()`.
  2. `me = await getMe()`. An error renders `ErrorAlert` full-panel.
  3. Render `<AppShell me={me.value} envLabel={publicEnv.NEXT_PUBLIC_ENV_LABEL}>{children}</AppShell>`.
- **`AppShell`** (client):
  - shadcn `SidebarProvider`/`Sidebar` (`collapsible="icon"`), showing `visibleNav(me)`:
    - Flow (`items:read`)
    - Exceptions (`items:read`, count badge = live `summary.kpis.needs_person`)
    - Reports (`reports:read`)
    - Config (`config:read`)
  - `LiveIndicator` sits in the `SidebarFooter`.
  - The header holds the breadcrumb, the ⌘K button, the `EnvBadge` (PROD gets `border-status-error text-status-error`) and the `UserMenu`. The `UserMenu` is a `DropdownMenu` with the user's name and a sign-out `<form method="post" action="/auth/sign-out">`.
  - The page area has `min-w-0 overflow-x-hidden`, so tables scroll inside their cards.
- **`FlowStreamProvider`:**
  - Calls `useEventStream("/flow/stream", { schema: flowStreamDataSchema, onEvent })`.
  - `summary` frames go to state. `item_changed` frames go to subscribers (`Set` of callbacks).
  - It exposes `{status, retries, retry, summary, subscribeItemChanged}`.
  - It's the only `/flow/stream` consumer in `web/`.
- **`CommandPalette`:**
  - ⌘K / Ctrl+K opens a `CommandDialog`.
  - A 250 ms debounced `searchItems(q)` server action fills the hits.
  - Selecting a hit gives `router.push("/items/<id>")`.
  - When the input matches `WI-\d+`, it offers "Go to WI-n" immediately.
- **Unauthorized:** `<RequirePermission me permission role>` renders children, or `ForbiddenState` ("You don't have access to this page. Ask an administrator for the <role> role.") inside the shell. `/flow`, `/flow/[stage]` and `/items/[id]` wrap in it with `items:read`, and the role named is `VIEWER`.

### Web: flow monitor

- **`/flow` page** (server): `api("get","/flow/summary")` and `getMe()`, then `<FlowMonitor initial={Result} canPauseBacklog={hasPermission(me,"backlog:run")} />`.
- **`FlowMonitor`** (client) keeps `lastGood: FlowSummary | null` and `error: ApiError | null`. The live `summary` from `useFlowStream` replaces `lastGood` and clears `error`. The Retry button calls `refreshFlowSummary()`.
- **Render:**
  - An error shows `ErrorAlert` ("Couldn't load the flow") and, when `lastGood` exists, a "stale" tag above the dimmed content.
  - The KPI strip is 4 `KpiCard`s: In today · Auto-applied % · Applied (one `Money` per currency) · Needs a person.
  - Each backlog RUNNING batch gets a `BacklogBar` (`Progress`): "Backlog batch B-0007 · 2,140 / 5,000 items · ETA 41 min". Pause shows only with `canPauseBacklog`, calls `pauseBacklogBatch(id)`, and toasts on error.
  - Stage tiles come from `summary.stages`. A tile is a `Link` to `/flow/<tile lower>` and shows the label, a large `in_queue`, `in_progress`, a `Sparkline` (an inline SVG polyline, `aria-label` "Throughput last 60 minutes"), the p95 dwell via `formatDuration`, an error badge when `errors > 0`, and the aging buckets (AWAITING_RECEIPT) or `Cohere n%` (EXTRACT).
  - **Layout:** `md:` a horizontal flex row with `overflow-x-auto` inside its card; below `md` a vertical list.
  - The "Ask" button opens `<LlmChat context={{kind:"flow"}} systemPromptKey="flow" actions={FLOW_CHAT_ACTIONS} variant="sheet" />` from s22.
- **Empty day** (`in_today === 0`): `EmptyState` "Nothing has arrived yet today." plus "The intake poller last checked the mailbox N minutes ago." from `pollers` (or "hasn't run yet").
- **`loading.tsx`:** 4 KPI and 12 tile `Skeleton`s with shimmer.

### Web: stage table

- **`/flow/[stage]` page:** Zod-parse `stage` (`/^[a-z_]+$/`, upper-cased) and `searchParams` (`state?`, `page` ≥ 1).
- Then `api("get","/flow/stages/{tile}/items", …)`. A 422 or 404 calls `notFound()`; another error renders `ErrorAlert`.
- **`StageItemsTable`** (client) wraps `DataTable`. Columns:
  - WI id (mono)
  - Payer
  - Amount (`Money`)
  - Received (relative, with the absolute time in a tooltip)
  - Attempts
  - Status (`StatusBadge kind="item_state"`, plus the payment-status badge when set)
  - Lock (violet `Lock` icon and `owner_name`)
- A row links to `/items/<id>?from=<TILE>`. It subscribes to `item_changed` and patches the matching row's state, stage, lock and payment status in local state, with no reload. A row whose stage left this tile shows a muted "Moved to <stage>".
- Pagination is URL-driven (`hrefForPage`). `loading.tsx` renders a 10-row table skeleton.

### Web: item view

- **`/items/[id]` page:** Zod-parse `id` (accepts digits or `WI-n`), then fetch `/items/{id}` and `/items/{id}/history` in parallel. A 404 calls `notFound()`.
- **`ItemView`** (client) is a grid: `lg:grid-cols-[2fr_3fr_minmax(320px,1.4fr)]`, single column below `lg` (<1024 px stacks artifact, then extraction, then history).
- **Left:** `ArtifactViewer` with parts, a part selector when there's more than one part, and highlights derived from `extraction.final`. There's one highlight per `Extracted` field and line whose `source` has a `bbox`; its `id` is the field path (`"payer_name"`, `"lines[2]"`).
- **Middle:**
  - `ExtractionTabs`:
    - *Final*: rows of field label, value, an A / B / A+B / Human tag from `provenance`, and a confidence `Progress`.
    - *Reader A* and *Reader B*: same rows, from that reader's output. A failed reader shows its status.
    - *Disagreements*: a table.
  - Hovering a row sets `HighlightContext.active`, which the viewer's highlight layer uses to emphasise the box.
  - The `LinesTable` sits below the tabs: invoice #, stated, Fusion balance, applied (`Money`), `StatusBadge kind="line_status"`, Fusion result code (mono).
- **Right rail:** `Tabs` History | Chat.
  - History: `HistoryTimeline`.
  - Chat: `<LlmChat context={{kind:"item", id:String(item.id)}} systemPromptKey="item" actions={ITEM_CHAT_ACTIONS} variant="panel" />`.
- **`ItemHeader`:**
  - Shows the WI id, the stage, a `StatusBadge` per enum, `Money` and the payer.
  - When there's a lock: a violet `Lock` line, "Locked by <owner_name> since <time>" (the full `lock-banner` with actions is s20's).
  - It subscribes to `item_changed` for its id: it patches the header at once, then runs `router.refresh()` debounced 1 s to pull fresh history and lines.
- **Chat actions** (navigation only, never a mutation):
  - `ITEM_CHAT_ACTIONS = [{id:"open_in_workbench", label:"Open in exception workbench"}]`, handled by navigating to `/exceptions?item=WI-<id>`.
  - `FLOW_CHAT_ACTIONS = [{id:"open_stage", label:"Open stage"}]`, which uses the `args.stage` from the action.
  - The coder binds the handler to the prop name s22 merged with.

### Web: shared components (configured by props)

- **`ArtifactViewer`:**
  - Loads `/api/items/<id>/parts/<n>` (and `?variant=text` for TEXT, TABLE and DOCX).
  - PDF: `pdfjs-dist` is imported dynamically inside `useEffect`, with `GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString()`. Each page is rendered to a `<canvas>`, with an absolutely positioned highlight layer per page; boxes are percentages from `bbox` (0..1) and the `page` (default 1).
  - Image: `<img>` plus the layer.
  - Text: a `<pre>` with a quote highlight (each `source.quote` is wrapped in `<mark>` with the field id).
  - A 410 shows the `EmptyState` "This artifact was purged under the retention policy."
- **`ErrorAlert`:** a destructive `Alert`: "<title>. The API returned <status> (request id <first 8>…)." plus Retry. For `status 0` the message is "The API couldn't be reached." The full request id is in a `title` attribute and a copy button.
- **`StatusBadge`:**
  - Typed maps `Record<Schemas["ItemState"], StatusToken>`, `Record<Schemas["PaymentStatus"], StatusToken>` and `Record<Schemas["LineStatus"], StatusToken>`, so a missing key is a `tsc` error. `StatusToken` = `"success"|"progress"|"waiting"|"attention"|"error"|"locked"|"neutral"`.
  - The label is `humanizeEnum` (`payment-success` gives "Payment success").
  - **Mapping rule:** success or applied values map to success; `*-dry-run` and previously-applied to neutral; awaiting to waiting; short-pay, less-than-total and partial to attention; not-found, failed and zero values to error; IN_PROGRESS and PENDING to progress; ESCALATED to error; DONE to success; ARCHIVED to neutral. The coder lists every member explicitly.
- **`Money`:** `formatMoney(amount, currency)` works on the decimal *string* (no float). It groups the integer part with commas (Indian lakh grouping for INR, as in design.md's `1,92,400.00 INR`), keeps 2 dp, keeps the sign, and appends `" " + currency`. It renders `<span className="font-mono tabular-nums text-right">`. `null` renders "—". It never emits `$`.

## Interfaces provided (pinned)

```python
# cashapp/services/flow_query.py
class FlowTile(StrEnum): ...   # Stage values in PIPELINE_ORDER with AWAITING_RECEIPT after MATCH_RECEIPT
STREAM_TICK_SECONDS: Final = 5.0; SUMMARY_CACHE_SECONDS: Final = 4.0; OVERLAP_SECONDS: Final = 10.0
AGING_BUCKETS: Final = ("0-2d", "3-7d", "8-30d", ">30d")
@dataclass(frozen=True, slots=True)
class TileData: tile: FlowTile; in_queue: int; in_progress: int; errors: int; throughput_per_min: tuple[int, ...]  # len 60
    p95_dwell_s: float | None; awaiting_buckets: Mapping[str, int] | None
@dataclass(frozen=True, slots=True)
class KpiData: in_today: int; auto_applied_pct: float | None; applied_by_currency: tuple[Money, ...]; needs_person: int
@dataclass(frozen=True, slots=True)
class PollerData: name: str; last_cycle_at: datetime | None
@dataclass(frozen=True, slots=True)
class BacklogData: id: int; name: str; processed: int; total: int; eta_minutes: int | None; status: str
@dataclass(frozen=True, slots=True)
class FlowSummaryData: kpis: KpiData; stages: tuple[TileData, ...]; pollers: tuple[PollerData, ...]
    cohere_utilisation_pct: float | None; backlog: tuple[BacklogData, ...]; generated_at: datetime
class CohereUtilisationSource(Protocol):
    async def utilisation_pct(self, uow: UnitOfWork) -> float | None: ...
class BacklogProgressSource(Protocol):
    async def running(self, uow: UnitOfWork) -> list[BacklogData]: ...
def default_cohere_source() -> CohereUtilisationSource    # adapts s36; None-safe
def default_backlog_source() -> BacklogProgressSource     # adapts s35
async def flow_summary(uow: UnitOfWork, *, clock: Clock, cohere: CohereUtilisationSource,
                       backlog: BacklogProgressSource) -> FlowSummaryData
class FlowSummaryCache:
    def __init__(self, *, ttl_s: float = SUMMARY_CACHE_SECONDS, clock: Clock | None = None) -> None
    async def get(self, compute: Callable[[], Awaitable[FlowSummaryData]]) -> FlowSummaryData   # single-flight
@dataclass(frozen=True, slots=True)
class ItemChangedData: id: int; stage: Stage; state: ItemState; lock: LockInfo | None; payment_status: PaymentStatus | None
    updated_at: datetime; version: int
async def items_changed_since(uow: UnitOfWork, since: datetime, *, now: datetime, limit: int = 500) -> list[ItemChangedData]
async def stage_items(uow: UnitOfWork, tile: FlowTile, *, state: ItemState | None, page: int, page_size: int = 50,
                      now: datetime) -> tuple[list[tuple[WorkItem, LockInfo | None]], int]
@dataclass(frozen=True, slots=True)
class ItemDetailData: item: WorkItem; lock: LockInfo | None; adjudication: Adjudication | None
    readings: Mapping[ReaderSlot, ExtractionReading]; parts: list[ArtifactPart]
    lines: list[tuple[LineResult, ApplicationLedger | None]]; resolution: CustomerResolution | None; receipt: ReceiptRef | None
@dataclass(frozen=True, slots=True)
class ReceiptRef: receipt_id: int; receipt_number: str; decided_by: str; score: float | None; reservation_status: str | None
class ItemNotFound(LookupError): item_id: int     # router -> 404 item_not_found
class PartNotFound(LookupError): ...              # -> 404 part_not_found / part_text_not_found
class PartPurged(Exception): ...                  # -> 410 artifact_purged
async def item_detail(uow: UnitOfWork, item_id: int, *, now: datetime) -> ItemDetailData
async def item_history(uow: UnitOfWork, item_id: int, *, page: int, page_size: int = 200) -> Page[WorkItemHistory]
@dataclass(frozen=True, slots=True)
class PartContent: data: bytes; media_type: str; filename: str
async def open_part(uow: UnitOfWork, store: ObjectStore, item_id: int, part_no: int,
                    *, variant: Literal["original", "text"] = "original") -> PartContent
@dataclass(frozen=True, slots=True)
class SearchHit: item_id: int; kind: Literal["item", "receipt", "invoice"]; match: str; stage: Stage; state: ItemState
async def search_items(uow: UnitOfWork, q: str, *, limit: int = 10) -> list[SearchHit]
def parse_work_item_ref(q: str) -> int | None     # "WI-20481" / "20481" -> 20481

# cashapp/services/poller_heartbeat.py
POLLER_NAMES: Final = ("intake-poller", "receipt-watcher")
async def record_poller_heartbeat(uow: UnitOfWork, name: str, at: datetime, *, status: str = "ok") -> None  # flush only
class PollerHeartbeatHook:   # s06 CycleHook
    def __init__(self, name: str) -> None
    async def on_cycle(self, container: Container, now: datetime) -> None   # own UoW, commits

# cashapp/data/repositories/flow_query.py
class FlowQueryRepository(BaseRepository[WorkItem]):
    async def error_counts_by_stage(self) -> dict[Stage, int]
    async def awaiting_buckets(self, *, now: datetime) -> dict[str, int]
    async def leaves_since(self, since: datetime) -> list[tuple[int, Stage, datetime]]       # (item_id, from_stage, at)
    async def stage_entries(self, item_ids: Sequence[int], *, before: datetime) -> list[tuple[int, Stage, datetime]]
    async def created_count_since(self, since: datetime) -> int                              # envelopes excluded
    async def finished_since(self, since: datetime) -> list[tuple[int, ItemState, PaymentStatus | None, bool]]  # bool = had HUMAN_ACTION
    async def applied_by_currency_since(self, since: datetime) -> list[tuple[str, Decimal]]
    async def done_count_since(self, since: datetime) -> int
    async def escalated_count(self) -> int
    async def stage_items(self, tile: str, *, state: ItemState | None, offset: int, limit: int) -> Page[WorkItem]
    async def changed_since(self, since: datetime, *, limit: int) -> list[WorkItem]          # ORDER BY updated_at, id
    async def search_refs(self, q: str, *, limit: int) -> list[tuple[int, str, str]]         # (item_id, kind, match)
# cashapp/data/repositories/poller_heartbeat.py
class PollerHeartbeatRepository(BaseRepository[PollerHeartbeat]):
    async def upsert(self, name: str, *, at: datetime, status: str) -> PollerHeartbeat
    async def all(self) -> list[PollerHeartbeat]

# cashapp/api/storage_deps.py  (unless s45 already shipped it; then s45's is used)
def get_object_store() -> ObjectStore; ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]
# cashapp/api/routers/flow.py  (module-level deps tests override)
def get_flow_summary_cache() -> FlowSummaryCache; def get_cohere_source() -> CohereUtilisationSource
def get_backlog_source() -> BacklogProgressSource; def get_clock() -> Clock
```

HTTP and OpenAPI contract. Every route requires `items:read`, and every error uses s01's shape. Schema names are pinned because the web types against them.

| Route | Response model (OpenAPI name) |
|---|---|
| `GET /flow/summary` | `FlowSummaryOut {kpis: FlowKpisOut{in_today:int, auto_applied_pct:float\|null, applied_by_currency:[{currency, amount: MoneyStr}], needs_person:int}, stages:[FlowTileOut{stage: FlowTile, in_queue, in_progress, errors, throughput_per_min:int[60], p95_dwell_s: float\|null, awaiting_buckets: {"0-2d","3-7d","8-30d",">30d"}\|null}], pollers:[{name, last_cycle_at}], cohere_utilisation_pct: float\|null, backlog:[{id,name,processed,total,eta_minutes,status}], generated_at}` |
| `GET /flow/stream` | SSE; `event: summary` data `FlowSummaryOut`; `event: item_changed` data `ItemChangedOut{id, stage: Stage, state: ItemState, lock: LockInfoOut\|null, payment_status: PaymentStatus\|null, updated_at}`; `id:` = ISO watermark. Declared via `FlowStreamFrameOut{summary?: FlowSummaryOut, item_changed?: ItemChangedOut}`. |
| `GET /flow/stages/{tile}/items?state&page` | `StageItemsOut{items:[StageItemOut{id, payer_name, amount: MoneyStr\|null, currency, received_at, attempts, stage, state, payment_status, lock}], total, page, page_size}` |
| `GET /items/{item_id}` | `ItemDetailOut{item: ItemOut{id, stage, state, payment_status, payer_name, amount, currency, payment_date, customer_account_number, received_at, updated_at, attempts, last_error_code, escalation_summary, info_flags, version}, lock, extraction: ExtractionOut{final: RemittanceExtraction\|null, provenance: dict, disagreements: [Disagreement], confidence: float\|null, reader_a: ReadingOut\|null, reader_b: ReadingOut\|null, missing_reader: ReaderSlot\|null, purged: bool}, parts:[PartOut{part_no, kind, media_type, purged}], lines:[LineOut{line_no, transaction_number, stated_amount, fusion_balance, applied_amount, line_status: LineStatus\|null, fusion_result_code}], resolution: ResolutionOut\|null, receipt: ReceiptOut\|null}`. `ReadingOut{status, model_id, attempt, output: RemittanceExtraction\|null, created_at}`. |
| `GET /items/{item_id}/history?page` | `HistoryOut{items:[HistoryRowOut{id, at, action, actor_kind, actor_id, actor_name, from_stage, to_stage, from_state, to_state, error_code, reasoning, payload: dict\|null, purged: bool}], total}` |
| `GET /items/{item_id}/parts/{part_no}?variant` | Raw bytes (`200`, the part's media type); 404 `part_not_found` / `part_text_not_found`, 410 `artifact_purged` |
| `GET /search?q` | `SearchOut{hits:[SearchHitOut{item_id, kind, match, stage, state}]}` |

```ts
// web/lib/api/client.ts (appended)
export function apiRaw<P extends ApiPath>(path: P, options?: ApiRequestOptions<P, "get">): Promise<Result<Response, ApiError>>;
// web/lib/me.ts (server-only)
export type Me = Schemas["MeResponse"];
export const getMe: () => Promise<Result<Me, ApiError>>;            // React cache(): one /me per request
export function hasPermission(me: Me, permission: string): boolean;
// web/lib/format.ts (client-safe)
export function formatMoney(amount: string | null | undefined, currency: string | null | undefined): string; // "12,480.00 USD", INR lakh grouping, "—" for null
export function formatWorkItemId(id: number): string;                // "WI-20481"
export function parseWorkItemId(value: string): number | null;
export function humanizeEnum(value: string): string;                 // "AWAITING_RECEIPT" | "payment-success" -> "Awaiting receipt" | "Payment success"
export function formatDuration(seconds: number | null): string;      // "42s" "3m 10s" "2h 5m" "—"
export function formatRelative(iso: string, now?: Date): string;
// web/lib/flow/stream-schemas.ts
export const flowSummarySchema: z.ZodType<Schemas["FlowSummaryOut"]>;
export const itemChangedSchema: z.ZodType<Schemas["ItemChangedOut"]>;
// web/components/shell/flow-stream.tsx ("use client")
export function FlowStreamProvider(props: { children: React.ReactNode }): React.JSX.Element;
export function useFlowStream(): {
  status: StreamStatus; retries: number; retry: () => void;
  summary: Schemas["FlowSummaryOut"] | null;
  subscribeItemChanged: (cb: (e: Schemas["ItemChangedOut"]) => void) => () => void;
};
// web/components/common/*  (props pinned; s20, s21, s41 consume)
export type StatusToken = "success" | "progress" | "waiting" | "attention" | "error" | "locked" | "neutral";
export const STATUS_TOKENS: {
  item_state: Record<Schemas["ItemState"], StatusToken>;
  payment_status: Record<Schemas["PaymentStatus"], StatusToken>;
  line_status: Record<Schemas["LineStatus"], StatusToken>;
};
export function StatusBadge(p: { kind: keyof typeof STATUS_TOKENS; value: string; className?: string }): React.JSX.Element;
export function Money(p: { amount: string | null | undefined; currency: string | null | undefined; className?: string }): React.JSX.Element;
export type DataTableProps<T> = {
  columns: ColumnDef<T>[]; data: T[]; getRowId: (row: T) => string;
  rowHref?: (row: T) => string; onRowClick?: (row: T) => void;
  pagination?: { page: number; pageSize: number; total: number; hrefForPage?: (p: number) => string; onPageChange?: (p: number) => void };
  initialSorting?: SortingState; enableColumnVisibility?: boolean;   // default true
  density?: "compact" | "comfortable"; densityStorageKey?: string;   // persisted in localStorage (try/catch)
  emptyState?: React.ReactNode; loading?: boolean; caption?: string;
};
export function DataTable<T>(p: DataTableProps<T>): React.JSX.Element;   // scrolls horizontally inside its card
export function KpiCard(p: { label: string; value: React.ReactNode; hint?: React.ReactNode; loading?: boolean }): React.JSX.Element;
export function EmptyState(p: { title: string; description?: React.ReactNode; action?: React.ReactNode; icon?: LucideIcon }): React.JSX.Element;
export function ErrorAlert(p: { error: ApiError; title: string; onRetry?: () => void; retrying?: boolean }): React.JSX.Element;
export type HistoryEntryView = Schemas["HistoryRowOut"];
export function HistoryTimeline(p: { entries: HistoryEntryView[]; emptyLabel?: string; defaultExpandedId?: number }): React.JSX.Element;
export type ArtifactHighlight = { id: string; label: string; partNo: number; page: number | null;
  bbox: { x: number; y: number; w: number; h: number } | null; quote: string | null };
export function ArtifactViewer(p: { itemId: number; parts: Schemas["PartOut"][]; highlights: ArtifactHighlight[];
  activeHighlightId?: string | null; onHighlightHover?: (id: string | null) => void }): React.JSX.Element;
export function LiveIndicator(p: { status: StreamStatus; retries: number; onRetry: () => void }): React.JSX.Element;
export function RequirePermission(p: { me: Me; permission: string; role: string; children: React.ReactNode }): React.JSX.Element;
export function ForbiddenState(p: { role: string }): React.JSX.Element;
```

```ts
// web/tests/support/fixtures/dto.ts  (typed from schema.d.ts; consumed by s20, s21, s41)
export function buildFlowSummary(o?: DeepPartial<Schemas["FlowSummaryOut"]>): Schemas["FlowSummaryOut"];  // all tiles, 60-zero sparkline
export function buildTile(stage: Schemas["FlowTile"], o?: Partial<Schemas["FlowTileOut"]>): Schemas["FlowTileOut"];
export function buildStageItem(o?: Partial<Schemas["StageItemOut"]>): Schemas["StageItemOut"];
export function buildStageItems(n: number, o?: Partial<Schemas["StageItemOut"]>): Schemas["StageItemsOut"];
export function buildLock(o?: Partial<Schemas["LockInfoOut"]>): Schemas["LockInfoOut"];
export function buildItemDetail(o?: DeepPartial<Schemas["ItemDetailOut"]>): Schemas["ItemDetailOut"];   // A/B/both provenance, 2 lines, 1 PDF part with bboxes
export function buildHistoryRow(o?: Partial<Schemas["HistoryRowOut"]>): Schemas["HistoryRowOut"];
export function buildHistory(n: number): Schemas["HistoryOut"];
export function buildItemChanged(o?: Partial<Schemas["ItemChangedOut"]>): Schemas["ItemChangedOut"];
export function buildMe(roles?: ("ADMIN" | "OPERATOR" | "REVERSER" | "VIEWER")[]): Schemas["MeResponse"];  // permissions from roles (mirrors s04 table for tests only)
// web/tests/support/mock-api-server.ts  (Playwright)
export const MOCK_API_PORT: number;   // env MOCK_API_PORT ?? 3199
export function startMockApiServer(port?: number): Promise<{ close(): Promise<void> }>;
export async function setMockRoute(method: string, path: string, response: { status?: number; body?: unknown; headers?: Record<string, string> }): Promise<void>;
export async function setMockStream(path: string, steps: readonly SseStep[]): Promise<void>;  // reuses s31's SseStep type
export async function resetMock(): Promise<void>;   // via POST /__mock/* control endpoints on the mock server
```

## Migrations

There is one hand-written revision: `api/alembic/versions/s19_flow_monitor.py`, with `revision = "s19_flow_monitor"`.

- **Expected parent:** the single head when this story merges. In wave 5, that's the last of s13, s15, s17, s16 or s35 to merge before it (all add revisions). The merger re-points `down_revision` and checks that `alembic heads` returns exactly one head.
- **`upgrade`:**
  - create `POLLER_HEARTBEAT` (`NAME` VARCHAR2(64) `PK_POLLER_HEARTBEAT`, `LAST_CYCLE_AT` TIMESTAMP WITH TIME ZONE null, `LAST_STATUS` VARCHAR2(20) not null, `UPDATED_AT` not null);
  - `IX_WORK_ITEM_UPDATED_AT` (`UPDATED_AT`);
  - `IX_WORK_ITEM_CREATED_AT` (`CREATED_AT`);
  - `IX_WIH_ACTION_AT` (`ACTION`, `AT`).
- **`downgrade`** reverses it.
- The ORM declares the same indexes in `models/poller_heartbeat.py`, so `create_all` in SQLite tests matches.
- Apply it to DEV ATP only.

## TEST PLAN (written and run in step 5 only)

API tests use s02 `uow` on SQLite, `FrozenClock`, s04 `override_principal`, and `httpx.AsyncClient(ASGITransport)`. Web unit tests use Vitest with s31's `api-mock`/`sse-mock`. Browser tests use Playwright with `withSession` (s04) and `mock-api-server`.

| AC | Test | Asserts |
|---|---|---|
| 1 | `api/tests/unit/services/test_flow_query.py::test_summary_kpis_today` | `in_today` excludes envelopes and yesterday's items; `auto_applied_pct` excludes items with HUMAN_ACTION; `applied_by_currency` sums APPLIED ledger rows per currency as `"0.00"` strings; `needs_person` = ESCALATED |
| 1 | `…::test_tiles_in_pipeline_order_with_awaiting_after_match_receipt` | |
| 1 | `…::test_tile_counts_errors_and_awaiting_buckets` | 1d/5d/20d/40d gives one item in each bucket |
| 1 | `…::test_throughput_is_60_minutes_and_p95_dwell` | leave rows at known minutes; the list has length 60 with correct counts; nearest-rank p95 is correct; no leaves gives `None` |
| 1 | `…::test_pollers_from_heartbeat_and_null_when_never_run` | |
| 1 | `…::test_cohere_and_backlog_sources_failures_are_null_and_empty` | |
| 1 | `…::test_summary_cache_single_flight` | 5 concurrent `get` calls make 1 compute; after the TTL it recomputes |
| 1 | `…::test_items_changed_since_uses_overlap_and_returns_lock` | |
| 1 | `api/tests/api/test_flow_router.py::test_summary_requires_items_read` | no principal gives 401; a principal without the permission gives 403 `forbidden` |
| 1 | `…::test_summary_shape_matches_contract` | the JSON validates against `FlowSummaryOut`; money is strings |
| 1 | `api/tests/api/test_flow_stream.py::test_stream_emits_summary_then_item_changed_for_updated_rows` | the tick sleep is patched; after an item is updated (s40 `write_lock`), the next tick yields `item_changed` with `lock.owner_name`; an unchanged item yields nothing |
| 1 | `…::test_stream_resumes_from_last_event_id_and_dedupes_overlap` | |
| 1 | `…::test_stream_one_item_query_per_tick` | a SQLAlchemy `before_cursor_execute` counter: exactly 1 WORK_ITEM changed-since statement per tick (the summary is cached) |
| 1 | `…::test_openapi_declares_stream_frame_schemas` | |
| 1 | `api/tests/unit/services/test_poller_heartbeat.py::test_hook_upserts_and_registered_once` | |
| 2 | `api/tests/api/test_items_router.py::test_stage_items_paged_with_lock_and_state_filter` | |
| 2 | `…::test_stage_items_invalid_tile_422` | |
| 2 | `…::test_item_detail_assembles_extraction_lines_resolution_receipt` | seeds s08, s09, s11, s13 and s15 rows; checks `fusion_result_code`, `missing_reader` and the provenance sources |
| 2 | `…::test_item_detail_404_and_purged_adjudication` | |
| 2 | `…::test_history_ordered_with_actor_names` | |
| 2 | `…::test_part_streams_bytes_inline_with_media_type_and_is_not_logged` | `LocalFolderObjectStore`; checks the headers; `capture_logs` has no key or bytes |
| 2 | `…::test_part_text_variant_purged_410_missing_404` | |
| 2 | `…::test_search_by_wi_id_receipt_and_invoice` | |
| 3 | `web/e2e/shell.spec.ts` › `sidebar shows Flow, Exceptions with count, Reports and Config for ADMIN` | |
| 3 | › `VIEWER sees no Config` | |
| 3 | › `PROD env badge has red outline` | build-time env via `NEXT_PUBLIC_ENV_LABEL=PROD` in the webServer env, read from computed style |
| 3 | › `⌘K jumps to an item by WI id, receipt and invoice` | |
| 3 | › `user menu signs out to /signed-out without shell` | |
| 3 | › `unauthorized route shows ask-an-administrator state` | |
| 3 | `web/tests/unit/shell/nav.test.ts` › `visibleNav filters by permission` | |
| 3 | `web/tests/unit/shell/breadcrumbs.test.tsx` › `builds Flow / Match receipt / WI-n from pathname and from` | |
| 4 | `web/tests/unit/common/live-indicator.test.tsx` › `Live when connected, Reconnecting with retry count, Disconnected with Retry` | `FlowStreamProvider` driven by `sse-mock` (connect, `{error:true}` drops, then a 4xx); clicking Retry calls `retry` |
| 5 | `web/e2e/flow.spec.ts` › `KPI strip shows 4 cards with formatted values` | |
| 5 | › `stage tiles in pipeline order with sparkline, p95 and error badge` | |
| 5 | › `awaiting tile shows aging buckets and extract tile shows Cohere %` | |
| 5 | › `running backlog batch shows progress text and Pause posts to /backlog/batches/{id}/pause` | the mock records the POST |
| 5 | › `Pause hidden without backlog:run` | |
| 6 | `web/e2e/flow.spec.ts` › `clicking a tile opens /flow/[stage] table with money, status badge and lock owner` | |
| 6 | `web/e2e/item-view.spec.ts` › `row opens three-pane view with PDF highlight boxes` | |
| 6 | › `hovering a Final field highlights its box` | |
| 6 | › `tabs Final, Reader A, Reader B, Disagreements with A/B/A+B tags and confidence` | |
| 6 | › `lines table shows Fusion outcome` | |
| 6 | › `history entry expands to payload JSON with copy` | |
| 6 | › `chat tab and flow Ask render LlmChat panel and sheet` | |
| 6 | `web/tests/unit/common/artifact-viewer.test.tsx` › `maps bbox to percentage boxes per page and marks quotes in text parts` | |
| 6 | › `410 shows purged state` | |
| 6 | `web/tests/unit/api/parts-route.test.ts` › `proxies bytes with content-type, inline disposition and nosniff; validates params` | |
| 7 | `web/e2e/item-view.spec.ts` › `item_changed lock taken updates stage row and item header without reload` | `setMockStream` pushes `item_changed`; `page.on("load")` count stays 1 |
| 7 | `web/tests/unit/flow/stage-items-table.test.tsx` › `patches row lock and state on item_changed` | |
| 8 | `web/e2e/flow.spec.ts` › `loading shows skeletons` | the mock delays the response |
| 8 | › `empty day shows poller last-checked minutes` | |
| 8 | › `503 shows error-alert with request id and Retry; stale data tagged` | |
| 8 | `web/tests/unit/common/error-alert.test.tsx` › `renders status, short request id and retry` | |
| 9 | `web/tests/unit/common/status-badge.test.tsx` › `every ItemState, PaymentStatus and LineStatus value in openapi.json is mapped` | reads `lib/api/openapi.json` `components.schemas.*.enum`; fails on any unmapped value |
| 9 | › `labels are Title case and tokens use status classes` | |
| 9 | `web/tests/unit/common/money.test.tsx` › `renders 12480.00 USD as 12,480.00 USD right-aligned tabular-nums` | |
| 9 | › `never renders a bare $` | |
| 9 | › `INR uses lakh grouping` | |
| 9 | › `negative and null` | |
| 10 | `web/e2e/responsive.spec.ts` › `<1024px item view stacks artifact, extraction, history` | |
| 10 | › `375px stages render as a vertical list` | |
| 10 | › `375px tables scroll inside card with no page horizontal scroll` | `document.documentElement.scrollWidth <= clientWidth` |

## Assumptions and deviations

1. **"Today" is the UTC calendar day.** No tenant timezone setting exists. s41 can share a helper later.
2. **Poller last-cycle times come from a new `POLLER_HEARTBEAT` table.**
   - Intake writes it through a `CycleHook` appended to s06's `hooks.py`. The receipt watcher gets one appended call in s14's cycle.
   - Neither adds a loop.
   - Before s14's edit lands, `last_cycle_at` is `null`.
3. **Throughput is measured as leaves per minute, and dwell as time since stage entry.** Both come from `STAGE_TRANSITION` history, because no event store exists. Retries inside a stage don't reset dwell.
4. **`auto_applied_pct` is defined as** DONE + success with no human action, over DONE + ESCALATED today.
5. **The summary is cached for 4 s per process.** That keeps "one indexed query per tick" true for the item query: the summary's grouped counts run at most once per 4 s, whatever the number of connections.
6. **`apiRaw` is appended to s31's `client.ts`**, because binary passthrough can't use `api()`, and `API_BASE_URL` is lint-restricted to `lib/api`.
7. **`web/app/api/items/[id]/parts/[n]/route.ts`** is added (not in the story's owned list) so the browser fetches parts with the session cookie.
8. **The status-enum test reads the generated `openapi.json`.** The maps are typed `Record<Schemas[...]>`, so `tsc` also fails on any gap. openapi-typescript emits types only, and s31's generator options are untouched.
9. **INR uses Indian digit grouping**, following design.md's `1,92,400.00 INR`. Other currencies use 3-digit grouping.
10. **Chat actions are navigation-only** (open in workbench, open stage). Mutating actions belong to s20, through s22's handler prop.
11. **`dropdown-menu` and `avatar` are added via the shadcn CLI.** s01's set lacks a user-menu primitive.
12. **Playwright gets a programmable mock API server**, wired through an append to s01's `playwright.config.ts`. The Next server's API calls are server-side, so browser routing can't intercept them. Specs live in `web/e2e/` (s01's `testDir`).
13. **Item pages link with `?from=<TILE>`** so the breadcrumb can show the stage. A direct link shows "Flow / WI-n".

## Risks

- **Unmerged dependency signatures:** s13, s15, s35 and s36 are planned in parallel. The repository, adapter and model names used here (`LineResult`, `ApplicationLedger`, `ReservationRepository.active_for_item`, `MatchCandidate`, s35's running-batch query, s36's `cohere_utilisation`) are adapted by the coder to what merged. The adapters keep each adaptation to a single place.
- **Shared-file edits:** s06 `hooks.py` (append), the s14 poller (one call), s31 `client.ts` (append), s01 `app/layout.tsx`, `app/page.tsx` and `playwright.config.ts`, and the generated `openapi.json` and `schema.d.ts` (regenerated, never hand-merged). `storage_deps.py` may already exist from s45; reuse it if so.
- **Oracle SQL portability:** the minute bucketing and the age buckets are done in Python over fetched timestamps (bounded to 60 minutes of leave rows), not with dialect date functions. The aging counts use bound cut-off datetimes in `CASE`/`SUM`, which works on Oracle and SQLite.
- **Clock skew in `UPDATED_AT`:** this is covered by the 10 s overlap and the `(id, version)` dedupe.
- **pdfjs-dist 6 worker under Turbopack:** if `new URL(..., import.meta.url)` doesn't resolve, copy the worker to `public/` in a `postinstall`-free way (a static import of `?url`). The coder records the choice.
- **SSE under the jsdom/msw streaming caveats from s31:** the live-indicator test may need `// @vitest-environment node` with a minimal DOM, as s31 records.
- **Load:** each open tab keeps one SSE connection, with one indexed query per 5 s plus the shared cached summary. This is fine for an ops team. Throttling isn't needed now.
