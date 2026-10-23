# Plan: live-progress-dashboard

Story: [story.md](story.md) (issue #48, AC 2, scope item 4). Board: `design/project/glass/Dashboard.dc.html`, design.md §3.1, §4, §5, §7.
Skills applied: python-web-app:building-python-web-apps (routes → services → repositories), python-llm-features:reporting-derived-metrics (undefined metric is `None`, never `0`; every figure names its window and `n`), nextjs-fullstack-standards, BMN `nextjs.md` + topic files typescript, sse-and-streaming, rendering-and-caching, data-fetching-and-mutations, testing-and-observability.

## 1 Approach

- research.md a1 ("Theme and dashboard"): a dedicated `/dashboard` built from `KpiCard` and `ui/chart.tsx`, fed by **one new auto-discovered aggregate router** that reads only through repositories. It also follows a1's metric-honesty rules: money per currency as Decimal strings and never summed across currencies; no accuracy without ground truth; cost shown with its null-cost share; every tile states its window.
- **One owner of aggregates.** `MetricsService` (`services/metrics/service.py`) is the only code that computes progress figures. html-progress-reports and the chat tool `metrics.read` call it. It reads through a new `MetricsQueryRepository`, a plain query repository over the UoW session, shaped like `ReportQueryRepository`. The definitions are pinned in docstrings (§4).
- **Live updates use the flow SSE's mechanism** (`api/routers/flow.py`), as the story's Assumption says. That is a per-connection view of the database that adds no bus traffic, no scheduler and no third poller. The cursor is the monotonic `WORK_ITEM_HISTORY.ID`, carried as the SSE `id:` so a reconnect resumes from it (SSE-20). One process-wide single-flight `MetricsChangeFeed` lets N open connections share one history read per tick.
  - `activity` is sent once per new history row.
  - `summary` is sent only when the recomputed summary differs from the last one sent.
  - The heartbeat is `ping=15`, sent with `X-Accel-Buffering: no` (research.md risk: buffering in the OCI load balancer).
  - Deviation (Assumption A1): the story's "no polling loop" is read as "no poller of an external source". The outbox signal can't be shared because the relay consumes it (it clears its flag), and it is in-process only, while history writes happen in worker processes.
- **The web page is server-first** (DF-1, DF-3, RC-5).
  - `app/(shell)/dashboard/page.tsx` awaits `searchParams.window` and fetches the six `/metrics/*` endpoints plus `/llm-usage/cohere-utilisation` in parallel (DF-4) through `api()`.
  - The `Segmented` control changes `?window=`, so every tile is fetched again on the server.
  - One client leaf, `DashboardLive`, subscribes to `/metrics/stream?window=` through the single `useEventStream`. It keeps the last good values so an error marks tiles stale and shows their time.
- **`useEventStream` moves** from `web/lib/api/use-event-stream.ts` to `web/hooks/use-event-stream.ts` with its signature unchanged (this story owns it, per split.md). `stream-paths.ts` gains `:param` patterns so later streams such as `/lab/replays/:id/stream` can register.

## 2 Files to create / change

### API (`api/src/cashapp/`)

| File | New / change | Purpose |
|---|---|---|
| `domain/metrics.py` | new | `MetricsWindow` StrEnum (`24h`, `7d`, `30d`, `mtd`), `ThroughputBucket` (`hour`, `day`), `ActivityKind` (`APPLIED`, `RECEIPT_ARRIVED`, `AUTOFIX`, `ESCALATED`), `MetricName` (`summary`, `money_by_currency`, `throughput`, `autofix`, `models`, `activity`), `CostBasis` (`PER_CALL`, `CLUSTER`), and `window_bounds(window, now) -> tuple[datetime, datetime]` (half-open `[start, end)`; `mtd` starts on the 1st of the month UTC). `default_bucket(window)`: 24h gives hour, otherwise day. |
| `services/metrics/__init__.py` | new | Package docstring: the one owner of progress aggregates. |
| `services/metrics/models.py` | new | Frozen Pydantic models, the contracts of §7: `ProgressSummary`, `AwaitingReceipt`, `OpenExceptions`, `CurrencyTotal`, `ThroughputPoint`, `AutofixOutcome`, `ModelEfficiencyRow`, `ActivityEvent`. Money is `MoneyStr` + `CurrencyCode`; no model has a cross-currency money field. |
| `services/metrics/accuracy.py` | new | Pure functions: `compared_fields(extraction: Mapping) -> dict[str, str]` (normalised header fields `payer_name`, `remittance_reference`, `payment_date`, `amount`, `currency`, plus `line:<invoice_number>:amount_paid` per line), `field_agreement(reading, human_final) -> tuple[int, int]` (matched, total), `differs(reading, human_final) -> bool`. |
| `services/metrics/rates.py` | new | `rate(numerator, denominator) -> float | None` (None when the denominator is 0, never 0.0). `money(d: Decimal) -> Decimal` wraps `to_money` (2 dp ROUND_HALF_UP). |
| `services/metrics/activity.py` | new | `to_activity(rows: Sequence[HistoryActivityRow]) -> list[ActivityEvent]`: maps history rows to kinds and builds `text` from structured fields only. No payer names or free text. Consecutive `RECEIPT_ARRIVED` rows with the same receipt number merge into "RCPT-x woke N waiting items". |
| `services/metrics/service.py` | new | `MetricsService(uow: UnitOfWork, *, clock: Clock, config: RuntimeConfig | ConfigSnapshot)` with the six methods of §7. `summary` reads `aging.awaiting_receipt_max_days` through the config (it becomes `RuntimeSettings` when db-stored-settings lands; the accessor `config.aging().awaiting_receipt_max_days` keeps working). |
| `services/metrics/feed.py` | new | `MetricsChangeFeed`: process-wide, single-flight, `async def since(uow_factory, after_id: int, limit) -> list[HistoryActivityRow]`, cached per tick (`STREAM_TICK_SECONDS` from `flow_query`). `latest_id(uow_factory) -> int`. |
| `data/repositories/metrics.py` | new | `MetricsQueryRepository(session)`, the only SQL for the methods above (§4). Never commits. Returns plain rows (NamedTuples): `HistoryActivityRow`, `UsageAggRow`, `AdjudicationPairRow`, and so on. |
| `api/schemas/metrics.py` | new | `MetricsEnvelope[T]` generic `{window: MetricsWindow, as_of: datetime, data: T}`, plus concrete aliases `SummaryOut`, `MoneyByCurrencyOut`, `ThroughputOut`, `AutofixOut`, `ModelsOut`, `ActivityOut`, and the SSE frame models `MetricsSummaryFrame`, `MetricsActivityFrame` (OpenAPI docs only). |
| `api/routers/metrics.py` | new (auto-discovered) | `router = APIRouter(prefix="/metrics", tags=["metrics"])` with REPORTS_READ on every route. Routes: `/summary`, `/money-by-currency`, `/throughput` (`bucket` optional), `/autofix`, `/models`, `/activity` (`limit` 1..200, default 50), `/stream`. Uses `UowFactoryDep`, `RuntimeConfigDep` and a `ClockDep` (`get_clock`, as in flow.py), plus `get_metrics_feed()` with `@lru_cache`. |
| `services/chat/tools/metrics.py` | new | `TOOLS = [ToolSpec(name="metrics.read", group=ToolGroup.METRICS, permission=Permission.REPORTS_READ, mutating=False, confirm_required=False, audit_label="Read progress metrics", input_model=MetricsReadIn, output_model=MetricsReadOut, handler=read_metrics, preview=None)]`. The handler opens `ctx.uow_factory()`, builds `MetricsService(uow, clock=ctx.clock, config=...)` and dispatches on `metric`. The config source is the `ToolContext` service container entry pinned by chat-agent-tool-registry. If that has no config entry, the handler uses `get_runtime_config()` (recorded as Assumption A6). |

No `main.py` edit (routers are auto-discovered) and no ORM model (read-only story).

### Web (`web/`)

| File | New / change | Purpose |
|---|---|---|
| `hooks/use-event-stream.ts` | **git mv** from `lib/api/use-event-stream.ts` | The one SSE hook. Signature unchanged. Imports `../lib/api/sse-parser` and `../lib/api/stream-paths` via `@/lib/api/*`. |
| `lib/api/use-event-stream.ts` | delete (moved) | No re-export, so there is one path. |
| `components/common/live-indicator.tsx`, `components/common/llm-chat/use-chat.ts`, `components/shell/flow-stream.tsx`, `tests/support/sse-mock.ts` | change (import path only) | Import `@/hooks/use-event-stream`. |
| `lib/api/stream-paths.ts` | change | `STREAM_PATHS` becomes an append-only `as const` list that also accepts `:param` segments (`"/flow/stream"`, `"/chat/stream"`, `"/metrics/stream"`). It gains a type `StreamPath = ExpandParams<(typeof STREAM_PATHS)[number]>` (each `:x` becomes `${string}`), and `isStreamPath(p)` matches segment by segment with a `:x` matching exactly one non-empty segment of `[A-Za-z0-9_-]+`. |
| `app/(shell)/dashboard/page.tsx` | new | Server Component. `requireSession("/dashboard")` and `getMe()` with a REPORTS_READ check (`ForbiddenState`). Parses `window` with Zod (`lib/metrics/schemas.ts`), defaulting to `7d` and allowing only `24h`, `7d` and `30d` in the UI. `Promise.all` over the seven calls, then renders `TopBar` with the `Segmented` slot and `DashboardBoard`. `export const metadata = { title: "Progress" }`. |
| `app/(shell)/dashboard/loading.tsx` | new | KPI skeletons (`SkeletonRows` + 4 `KpiCard` skeletons), caption "Reading aggregates…". |
| `app/(shell)/dashboard/error.tsx` | new | `'use client'` (TEST-20). `StateCard kind="error"` "Couldn't load the aggregates" with Retry → `retry()`. Generic message (TEST-21). |
| `lib/metrics/schemas.ts` | new | Zod: `MetricsWindowSchema`, `DashboardSearchParams`, and the SSE frame schemas `SummaryFrameSchema`, `ActivityFrameSchema` (TS-19, TS-20). Types come from `Schemas[...]` of the OpenAPI types. |
| `lib/metrics/format.ts` | new | `formatPct(rate: number | null)` gives `—` for null; `formatAccuracy(acc, n)` gives `"96.8% · n 212"` or `—`; `formatAge(days, limit)` gives "Oldest 11d of 30d aging"; `windowLabel(w)`; `secondsAgo(at, now)`. Money goes through `common/money.tsx` (`CCY 1,234.00`). |
| `components/dashboard/dashboard-board.tsx` | new | Server-safe composition: KPI row, money, two-up (throughput + auto-fix), activity, model efficiency. It decides the empty state: when `summary.done_items === 0`, `StateCard kind="empty"`. |
| `components/dashboard/kpi-row.tsx` | new | 4 `KpiCard`s: Receipts matched (mono 30px, "Reserved and at least one line applied"), Automation (`variant="ring"` 72px, "no human touch"), Awaiting receipt (accent, age line), Open exceptions (warn, "N locked · N dead-lettered"). Each label carries its window ("· 7d"; "now" for the two current-state tiles). |
| `components/dashboard/money-by-currency.tsx` | new | One tile per `CurrencyTotal` in a grid `minmax(170px,1fr)`. Header "Money applied by currency" and "<window> · never summed across currencies". No total. |
| `components/dashboard/throughput-chart.tsx` | new, `'use client'` | `ChartContainer` + recharts `AreaChart`. `applied` uses `var(--chart-1)` (`--acc-hi`) with a 13% fill. `escalated` uses `var(--chart-3)` (`--warn`) dashed, with no fill. Legend, "peak N/h" (or "peak N/d"), and header "items done per hour · <window>". |
| `components/dashboard/autofix-table.tsx` | new | `DataTable` with columns error code (mono), count, and a `Meter` 6px with `tone = rate > 0.6 ? "ok" : "warn"` plus "N% fixed" (`—` when null). Header "<window> · by error code". |
| `components/dashboard/model-efficiency-table.tsx` | new | `DataTable` with columns Role, Model (mono accent), Calls, Cost (`$x.xx`, "cluster" when `cost_basis=CLUSTER`), Cost unknown (`n/a` for CLUSTER), Agreement, Human corr., Accuracy (`formatAccuracy`, only when `accuracy_n > 0`). Footer `Pill`s: "Auto-fix rate X%" (ok), "Human-correction rate X%" (warn), "Cohere cluster utilisation X%" (accent; "—" when null). Header "<window> · accuracy only where people corrected". |
| `components/dashboard/activity-feed.tsx` | new | Timestamped rows (mono `HH:MM:SS` UTC). The `Pill` per kind is Applied ok, Receipt arrived accent, Auto-fix warn, Escalated err, followed by the text with an item link `/items/[id]`. Header pill "Streaming · N s ago" (ok); "Reconnecting…" (warn) or "Stream paused" (muted) by `StreamStatus`. |
| `components/dashboard/dashboard-live.tsx` | new, `'use client'` | Holds `summary` and `activity` state, seeded from server props. `useEventStream("/metrics/stream?…")`: the path stays `"/metrics/stream"` and `window` goes in the query through a new optional `query` option (see §7), which keeps the hook generic. `summary` replaces the KPI and footer values; `activity` prepends and is capped at 50. It tracks `lastEventAt` for "N s ago" (1 s ticker, reduced-motion safe). On `stream-error` or `disconnected` it marks tiles stale with the last good `as_of`. Renders `kpi-row` and `activity-feed`, and passes the rest through as `children` (RC-8). |
| `components/dashboard/window-control.tsx` | new, `'use client'` | `Segmented` with options `24h`, `7d` and `30d`. `onChange` calls `router.replace("?window=…", { scroll: false })` inside `startTransition`, and the pending state dims the tiles. |
| `components/dashboard/stale-banner.tsx` | new | The error state when last good data exists: `StateCard kind="error"` "Couldn't load the aggregates", "Tiles show values from HH:MM UTC and are marked stale.", Retry (`router.refresh()`). Tiles get `data-stale="true"` and the err-tinted border. |
| `components/dashboard/dashboard-empty.tsx` | new | `StateCard kind="empty"` "Nothing completed in this window", "No item reached done in the last <window>. Try 30 days or open the Flow monitor.", actions "Show 30 days" (`?window=30d`) and "Open Flow" (`/flow`). |
| `lib/permissions.ts` | change (append-only) | Adds `"/dashboard": "reports:read"` to `ROUTE_PERMISSIONS` only if glass-theme-shell hasn't added it (the merger dedupes). |
| `lib/api/openapi.json`, `lib/api/schema.d.ts` | regenerated | `npm run api:sync` after the router lands. |

The nav entry and the `/` → `/dashboard` redirect are glass-theme-shell's (its AC5), not this story's.

## 3 Test plan

Nobody writes or runs these until step 5. API tests go under `api/tests/` (pytest; the DB tests use the existing `tests/support/db.py` SQLite/async fixture and `factories.py`). Web unit tests sit next to their files (`*.test.ts(x)`, vitest + jsdom). E2E goes in `web/e2e/` (Playwright with the `tests/support/mock-api-server.ts` HTTP+SSE mock, TEST-12, TEST-14).

| AC | Test (path::name) | Type |
|---|---|---|
| 1 | `api/tests/test_metrics_window.py::test_window_bounds_half_open_24h_7d_30d` | unit |
| 1 | `api/tests/test_metrics_window.py::test_mtd_starts_first_of_month_utc` | unit |
| 1 | `api/tests/test_metrics_service.py::test_summary_returns_progress_summary_with_window` | unit (db) |
| 1 | `api/tests/test_metrics_service.py::test_money_by_currency_rows_per_currency_with_receipts_and_residual` | unit (db) |
| 1 | `api/tests/test_metrics_service.py::test_throughput_hour_buckets_for_24h_and_day_for_7d` | unit (db) |
| 1 | `api/tests/test_metrics_service.py::test_throughput_fills_empty_buckets_with_zero_counts` | unit (db) |
| 1 | `api/tests/test_metrics_service.py::test_autofix_outcomes_count_fixed_rate_per_code` | unit (db) |
| 1 | `api/tests/test_metrics_service.py::test_model_efficiency_rows_per_role_and_model` | unit (db) |
| 1 | `api/tests/test_metrics_service.py::test_recent_activity_kinds_and_limit_newest_first` | unit (db) |
| 1 | `api/tests/test_metrics_activity.py::test_receipt_arrived_rows_merge_per_receipt` | unit |
| 1 | `api/tests/test_metrics_activity.py::test_activity_text_has_no_payer_name` | unit |
| 1 | `api/tests/test_metrics_layering.py::test_metrics_service_has_no_sqlalchemy_import` (static: no `sqlalchemy` import in `services/metrics/*`, so SQL stays in `MetricsQueryRepository`) | unit |
| 2 | `api/tests/test_metrics_definitions.py::test_receipts_matched_needs_reservation_and_applied_line_in_window` (fixtures: reserved + no line → 0; line applied outside window → 0; RELEASED reservation → 0) | unit (db) |
| 2 | `api/tests/test_metrics_definitions.py::test_automation_rate_excludes_done_items_with_user_history` | unit (db) |
| 2 | `api/tests/test_metrics_definitions.py::test_automation_rate_is_none_when_no_done_items` (asserts `None`, not 0.0) | unit (db) |
| 2 | `api/tests/test_metrics_definitions.py::test_awaiting_receipt_count_oldest_age_and_aging_limit_from_config` | unit (db) |
| 2 | `api/tests/test_metrics_definitions.py::test_open_exceptions_locked_and_dead_lettered_subcounts` (expired lock is not locked) | unit (db) |
| 2 | `api/tests/test_metrics_definitions.py::test_accuracy_only_from_human_corrected_extractions_with_n` | unit (db) |
| 2 | `api/tests/test_metrics_definitions.py::test_accuracy_none_and_n_zero_without_human_corrections` | unit (db) |
| 2 | `api/tests/test_metrics_definitions.py::test_cost_unknown_share_counts_null_cost_rows_never_imputed` (2 of 4 null → 0.5; total cost sums only non-null) | unit (db) |
| 2 | `api/tests/test_metrics_definitions.py::test_cluster_cost_basis_for_oci_provider_has_no_cost_and_no_unknown_share` | unit (db) |
| 2 | `api/tests/test_metrics_definitions.py::test_agreement_rate_from_two_reader_adjudications_without_disagreements` | unit (db) |
| 2 | `api/tests/test_metrics_rates.py::test_rate_none_on_zero_denominator` | unit |
| 2 | `api/tests/test_metrics_accuracy.py::test_field_agreement_counts_header_and_line_fields` | unit |
| 2 | `api/tests/test_metrics_accuracy.py::test_invoice_numbers_compared_as_strings_with_suffix` | unit |
| 2 | `api/tests/test_metrics_docstrings.py::test_each_pinned_definition_is_in_a_docstring` (asserts the definition sentences in `MetricsService` method docstrings) | unit |
| 3 | `api/tests/test_metrics_money.py::test_money_never_summed_across_currencies_in_models` (walks every model in `services/metrics/models.py`: a `MoneyStr` field must have a sibling `currency`, or live on a model holding `currency`, or be USD cost on `ModelEfficiencyRow`; no list-level total field) | unit |
| 3 | `api/tests/test_metrics_money.py::test_amounts_two_dp_round_half_up_strings_in_json` (`0.125` → `"0.13"`, `2.675` → `"2.68"`) | unit |
| 3 | `api/tests/test_metrics_money.py::test_money_by_currency_two_currencies_have_no_combined_amount` | unit (db) |
| 4 | `api/tests/test_metrics_router.py::test_each_endpoint_returns_window_as_of_data` (parametrised over the 6 GET routes) | api |
| 4 | `api/tests/test_metrics_router.py::test_endpoints_require_reports_read` (403 without; viewer allowed) | api |
| 4 | `api/tests/test_metrics_router.py::test_invalid_window_is_422_in_single_error_shape` | api |
| 4 | `api/tests/test_metrics_router.py::test_router_auto_discovered_without_main_edit` | api |
| 4 | `api/tests/test_metrics_stream.py::test_stream_emits_activity_per_new_history_row_with_history_id` | api |
| 4 | `api/tests/test_metrics_stream.py::test_stream_emits_summary_only_when_changed` | api |
| 4 | `api/tests/test_metrics_stream.py::test_stream_resumes_after_last_event_id` | api |
| 4 | `api/tests/test_metrics_stream.py::test_stream_headers_event_stream_and_no_accel_buffering_and_ping_15` | api |
| 4 | `api/tests/test_metrics_stream.py::test_stream_publishes_nothing_to_outbox` (outbox row count unchanged) | api |
| 4 | `api/tests/test_metrics_feed.py::test_feed_single_flight_shares_one_query_per_tick` | unit |
| 4 | `api/tests/test_openapi_metrics.py::test_openapi_contains_metrics_paths_and_web_snapshot_is_current` (compares `web/lib/api/openapi.json` to `app.openapi()` for `/metrics/*`) | api |
| 5 | `api/tests/test_chat_tool_metrics.py::test_metrics_read_registered_in_metrics_group_read_only` | unit |
| 5 | `api/tests/test_chat_tool_metrics.py::test_metrics_read_dispatches_each_metric_to_service` | unit |
| 5 | `api/tests/test_chat_tool_metrics.py::test_metrics_read_not_offered_without_reports_read` | unit |
| 6 | `web/e2e/dashboard.spec.ts › "top bar shows Progress, env, Live, Sample data and the window control"` (Dashboard board) | browser |
| 6 | `web/e2e/dashboard.spec.ts › "KPI row shows receipts matched, automation ring, awaiting receipt and open exceptions"` (Dashboard board) | browser |
| 7 | `web/e2e/dashboard.spec.ts › "one money tile per currency and no cross-currency total"` (Dashboard board) | browser |
| 7 | `web/e2e/dashboard.spec.ts › "throughput chart, auto-fix meters and model efficiency footer pills"` (Dashboard board) | browser |
| 8 | `web/e2e/dashboard.spec.ts › "activity feed updates over the metrics stream without reload"` (mock SSE pushes an `activity` frame) | browser |
| 8 | `web/e2e/dashboard.spec.ts › "switching the window refetches every tile and labels it"` (records 6 `/metrics/*?window=30d` requests) | browser |
| 9 | `web/e2e/dashboard.spec.ts › "loading state shows KPI skeletons"` (mock `delayMs`) | browser |
| 9 | `web/e2e/dashboard.spec.ts › "empty state offers Show 30 days and Open Flow"` | browser |
| 9 | `web/e2e/dashboard.spec.ts › "error state marks tiles stale with last-good time and Retry recovers"` (TEST-17) | browser |
| 9 | `web/e2e/dashboard.spec.ts › "dashboard at 375px has no horizontal scroll"` (design.md §7) | browser |
| 10 | `web/components/dashboard/money-by-currency.test.tsx › renders one tile per currency, no total` | unit |
| 10 | `web/components/dashboard/autofix-table.test.tsx › meter tone ok above 60% else warn, dash for null rate` | unit |
| 10 | `web/components/dashboard/model-efficiency-table.test.tsx › accuracy only with n, cluster cost, footer pills` | unit |
| 10 | `web/components/dashboard/activity-feed.test.tsx › kind pills and streaming age label` | unit |
| 10 | `web/components/dashboard/throughput-chart.test.tsx › series use --chart-1 and --chart-3, escalated dashed` | unit |
| 10 | `web/components/dashboard/dashboard-live.test.tsx › applies summary and activity frames; marks stale on stream-error` (uses `tests/support/sse-mock.ts`) | unit |
| 10 | `web/components/dashboard/imports.test.ts › dashboard components import only common/*, shell/*, ui/chart and ui/* primitives` (static) | unit |
| 10 | `web/hooks/use-event-stream.test.ts › one hook: no other module under web/ calls fetch on /api/stream` (static) plus the existing reconnect behaviour (backoff cap, Last-Event-ID, fatal 4xx) | unit |
| 10 | `web/lib/api/stream-paths.test.ts › param patterns match one segment and reject traversal` | unit |
| 10 | `web/lib/metrics/format.test.ts › pct, accuracy, age and window labels` | unit |

Total: **63 tests** (43 api, 10 web unit, 10 e2e; the parametrised ones count once).

**Board checklist** (lesson L-admin-act-for-absent-owner-1). The coder ticks each item in validation.md.

- **Top bar** (glass-theme-shell `TopBar`):
  - [ ] title "Progress"
  - [ ] env pill (warn, mono)
  - [ ] Live pill (ok with dot)
  - [ ] "Sample data" pill (muted, only when `/me.sample_data`)
  - [ ] `Segmented` `24h | 7d | 30d` (mono 11px, active `#4f7cff2e`)
- **KPI row** (`KpiCard`, grid `auto-fit minmax(200px,1fr)`):
  - [ ] "Receipts matched · <w>" with a 30px mono value and "Reserved and at least one line applied"
  - [ ] "Automation · <w>" as a 72px ring (stroke `--acc-hi`, track `#ffffff14`) with "%" and "no human touch"
  - [ ] "Awaiting receipt" in accent with "Oldest Nd of Nd aging"
  - [ ] "Open exceptions" in warn with "N locked · N dead-lettered"
- **Money:**
  - [ ] header "Money applied by currency" and "<w> · never summed across currencies"
  - [ ] each tile has its label, a 20px mono amount and "N receipts · residual X"
  - [ ] no total
- **Throughput:**
  - [ ] header "Throughput" and "items done per hour · <w>"
  - [ ] Applied line on `--chart-1` with a 13% fill
  - [ ] Escalated on `--chart-3`, dashed
  - [ ] legend "Applied" / "Escalated"
  - [ ] "peak N/h"
- **Auto-fix:**
  - [ ] header "Auto-fix outcomes" and "<w> · by error code"
  - [ ] mono code, count
  - [ ] 6px `Meter`: ok when > 60%, else warn
  - [ ] "N% fixed"
- **Live activity:**
  - [ ] header "Live activity" with the pill "Streaming · N s ago"
  - [ ] mono timestamp on each row
  - [ ] pills Applied (ok), Receipt arrived (accent), Auto-fix (warn), Escalated (err)
- **Model efficiency:**
  - [ ] header "Model efficiency" and "<w> · accuracy only where people corrected"
  - [ ] columns Role, Model, Calls, Cost, Cost unknown, Agreement, Human corr., Accuracy
  - [ ] "—" where a value is unmeasured; "cluster" and "n/a" for Cohere
  - [ ] footer pills "Auto-fix rate" (ok), "Human-correction rate" (warn), "Cohere cluster utilisation" (accent)
- **States:**
  - [ ] Loading: KPI skeletons + block (shimmer, reduced-motion)
  - [ ] Empty: "Nothing completed in this window", "No item reached done in the last 7 days. Try 30 days or open the Flow monitor.", Show 30 days, Open Flow
  - [ ] Error: err border, "Couldn't load the aggregates", "Tiles show values from HH:MM UTC and are marked stale.", Retry
- **Shared components only** (glass-theme-shell): `GlassPanel/PanelHeader/PanelBody`, `KpiCard` ring, `Pill`, `Meter`, `Segmented`, `StateCard`, `SkeletonRows`, `DataTable`, `MonoLabel`, `TopBar`; `ui/chart.tsx`; `common/money.tsx`.
- **Not here:** the assistant dock on the board belongs to assistant-chat-redesign.

## 4 Data

- **No ORM model and no Alembic migration.** This story is read-only, and split.md lists no revision for it. If index tuning is found to be needed, it is a follow-up story, not an ad-hoc DDL.
- **Pinned definitions** (docstrings on `MetricsService`, SQL in `MetricsQueryRepository`). The window `[start, end)` comes from `window_bounds`.
  - **receipts matched**: distinct `WORK_ITEM` ids with a `RECEIPT_RESERVATION` in status ACTIVE or CONSUMED **and** at least one `APPLICATION_LEDGER` row with status APPLIED and `applied_at` in the window. `RELEASED` and `REVERSED` don't count.
  - **money by currency**: per `WORK_ITEM.currency`:
    - `amount` = the sum of the signed `APPLICATION_LEDGER.amount` for APPLIED rows in the window (credit memos net the total)
    - `receipts` = the count of distinct `receipt_id`
    - `residual` = the sum of the non-null `LINE_RESULT.residual` for those items' applied lines

    Each figure is quantised by `to_money`. Rows are sorted by currency, and a currency is never mixed into another.
  - **automation rate**: items with a history row `to_state = DONE` in the window and **no** history row with `actor_kind = USER` (ever), divided by all items with `to_state = DONE` in the window. It is `None` when there are none.
  - **awaiting receipt** (now, not windowed):
    - count = items in state `AWAITING_RECEIPT`
    - `oldest_age_days` = whole days since `min(awaiting_since)`, or `None` when the count is 0
    - `aging_limit_days` = `aging.awaiting_receipt_max_days`
  - **open exceptions** (now):
    - total = items in state `ESCALATED`
    - `locked` = those with `lock_owner` set and `lock_expires_at > now`
    - `dead_lettered` = those with `last_error_code = SYSTEM_DEAD_LETTER`
  - **throughput**: per bucket (hour or day, UTC, every bucket present):
    - `applied` = items reaching DONE with a success payment status
    - `escalated` = history rows with `to_state = ESCALATED`
  - **auto-fix outcomes**: per `error_code` of the `AUTOFIX_ATTEMPT` history rows in the window:
    - `count` = distinct items attempted
    - `fixed` = those items that are not `ESCALATED` now and whose `last_error_code` is not that code
    - `rate` = fixed / count, or `None` when count is 0
    - The summary's `autofix_rate` = the sum of fixed / the sum of count.
  - **model efficiency**: per `(LLM_USAGE.role, model_id)` in the window:
    - `calls` = the number of rows
    - `cost_usd` = the sum of the non-null `cost_usd` (USD, 2 dp)
    - `cost_unknown_share` = null-cost rows / all rows, never imputed
    - `cost_basis` = `CLUSTER` when `provider = "oci"` (dedicated cluster), and then `cost_usd` and `cost_unknown_share` are `None`

    The quality columns:
    - **agreement_rate** (adjudicator row only): MODEL-origin `ADJUDICATION` rows in the window with both readings present (`missing_reader IS NULL`) and empty `disagreements`, divided by MODEL-origin rows with both readings present. `None` on the other rows.
    - **human-corrected extraction**: a HUMAN-origin `ADJUDICATION` row created in the window. Within that, take the item's latest reading per slot.
    - **accuracy** (reader rows): the sum of matched fields / the sum of compared fields (`accuracy.field_agreement`) over the human-corrected extractions. `accuracy_n` = how many there are. It is `None` with `n = 0` when there are none, and `None` on the adjudicator and workhorse rows.
    - **human_correction_rate** (reader rows): human-corrected extractions whose final differs from that reader's reading, divided by the reader's OK readings in the window.
    - The summary's `human_correction_rate` = HUMAN adjudications / MODEL adjudications in the window.
  - **activity**: `WORK_ITEM_HISTORY` rows, newest first by `id`, mapped as follows:
    - `FUSION_WRITE` with outcome applied → APPLIED ("WI-n · CCY amount to RCPT-x")
    - `from_state = AWAITING_RECEIPT` and `to_state != AWAITING_RECEIPT` → RECEIPT_ARRIVED
    - `AUTOFIX_ATTEMPT` → AUTOFIX ("WI-n <error code label>")
    - `to_state = ESCALATED` → ESCALATED ("WI-n <error code label>")
    - Other rows are skipped. Labels come from the existing `error_codes` descriptions. No payer name or reasoning text goes in.
- **Repository methods** (`MetricsQueryRepository`):
  - `receipts_matched(start, end) -> int`
  - `applied_by_currency(start, end) -> list[CurrencyAggRow]`
  - `done_counts(start, end) -> tuple[int, int]` (all, untouched)
  - `awaiting(now) -> tuple[int, datetime | None]`
  - `open_exceptions(now) -> tuple[int, int, int]`
  - `throughput(start, end, bucket) -> list[BucketRow]`
  - `autofix_by_code(start, end) -> list[AutofixAggRow]`
  - `usage_by_role_model(start, end) -> list[UsageAggRow]`
  - `adjudication_agreement(start, end) -> tuple[int, int]`
  - `adjudication_origin_counts(start, end) -> tuple[int, int]`
  - `human_corrected_pairs(start, end) -> list[AdjudicationPairRow]` (human final + reading outputs A/B)
  - `reader_ok_counts(start, end) -> dict[ReaderSlot, int]`
  - `activity(limit, after_id: int | None = None) -> list[HistoryActivityRow]`
  - `latest_history_id() -> int`

  Buckets are truncated in Python from the timestamps returned by an indexed range query (no dialect-specific `TRUNC`), so the same code runs on ATP and on SQLite in tests.

## 5 Config / env

- Env: **none new** (input.md item 3: every setting except DB connection lives in the DB).
- DB settings read: `aging.awaiting_receipt_max_days` (existing).
- No new config keys. The stream tick reuses `flow_query.STREAM_TICK_SECONDS` and the heartbeat `PING_SECONDS = 15`; both are code constants shared with the flow SSE, not settings.
- Web: none new (`API_BASE_URL` is existing).

## 6 Risks and gates

Risks:
1. **Heavy aggregates on ATP.** The windows read history and ledger ranges.
   - Every query is a bounded range on a timestamp, and the summary is single-flight per process.
   - The SSE recomputes the summary only after new history rows.
   - If a query plan is poor, record it for an index follow-up rather than adding DDL.
2. **SSE through the OCI load balancer** (research.md). Mitigations are `ping=15`, `X-Accel-Buffering: no` and `Cache-Control: no-cache, no-transform` on the API, and the Next proxy already passes the body untouched (SSE-3, SSE-4, SSE-13).
3. **The moved hook breaks imports** in four existing files and in other stories' plans that cite `lib/api/use-event-stream`. §7 pins the new path, and the merger greps for the old path.
4. **Same-wave deps.**
   - **glass-theme-shell**: the coder uses the props it pins in its plan's §7. Where that plan differs from the names here, the dep's plan wins, and this plan's components adapt. They never stub or copy them (lesson L-comparison-wizard-from-fusion-2).
   - **chat-agent-tool-registry**: `ToolSpec`, `ToolGroup.METRICS` and `TOOLS` discovery.
5. **Definitions differ from `ReportQueryRepository.completions`** (which uses HUMAN_ACTION, not USER actor). The story pins USER. html-progress-reports takes figures only from `MetricsService`, so the two never disagree on one screen.

Coder gates (lint + type-check only; no tests written or run):
- api: `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`
- web: `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`
- After the router: `cd web && npm run api:sync` (regenerates `openapi.json` / `schema.d.ts`).

Rule ids applied:
- **TS**: TS-1, TS-5, TS-10, TS-13, TS-16, TS-17, TS-19, TS-20, TS-23, TS-28, TS-30, TS-31, TS-32, TS-34
- **SSE**: SSE-3, SSE-4, SSE-6, SSE-10, SSE-13, SSE-14, SSE-15, SSE-20, SSE-23, SSE-24, SSE-25, SSE-26, SSE-27
- **RC**: RC-5, RC-6, RC-7, RC-8, RC-13, RC-38, RC-44
- **DF**: DF-1, DF-3, DF-4, DF-22
- **TEST**: TEST-1, TEST-2, TEST-12, TEST-14, TEST-17, TEST-20, TEST-21, TEST-25, TEST-37
- **nextjs.md non-negotiables**: 1, 7, 12, 14

## 7 Interfaces provided

All are plannable now (same wave). Consumers import these paths and never create placeholders at them.

**A. `useEventStream`.** Consumers: engine-control-panel-ui, failed-receipt-review, matching-lab-ui, assistant-chat-redesign, and glass-theme-shell's footer and `flow-stream`.
- Path: `web/hooks/use-event-stream.ts` (`import { useEventStream } from "@/hooks/use-event-stream"`).
- Signature:
  ```ts
  export type StreamStatus = "live" | "reconnecting" | "disconnected";
  export type StreamEvent<T> = { id: string | null; event: string; data: T };
  export type UseEventStreamOptions<T> = {
    onEvent: (e: StreamEvent<T>) => void;
    body?: unknown;                 // present => POST JSON (never re-posted unless reconnect: true)
    query?: Readonly<Record<string, string>>; // NEW, appended to the URL, part of the connection key
    schema?: z.ZodType<T>;          // invalid frames dropped
    onStreamError?: (data: unknown) => void;  // `event: stream-error`
    enabled?: boolean;
    reconnect?: boolean;            // default body === undefined
    maxRetries?: number;            // default 8; backoff 1s doubling, cap 30s; server retry: honoured
  };
  export function useEventStream<T>(path: StreamPath, options: UseEventStreamOptions<T>):
    { status: StreamStatus; retries: number; retry: () => void };
  ```
- `StreamPath` comes from `web/lib/api/stream-paths.ts`. `STREAM_PATHS` is append-only, and each consumer adds its own entry in its own story:
  - engine: `"/engine/stream"`
  - lab: `"/lab/replays/:id/stream"`
  - chat confirm: `"/chat/tool-calls/:id/confirm"`

  A `:x` matches one `[A-Za-z0-9_-]+` segment. The proxy `web/app/api/stream/[...path]/route.ts` is unchanged and forwards the query and `Last-Event-ID`.

**B. `MetricsService`.** Consumers: html-progress-reports and the chat tool.
- Module `cashapp.services.metrics.service`:
  ```python
  class MetricsService:
      def __init__(self, uow: UnitOfWork, *, clock: Clock, config: RuntimeConfig | ConfigSnapshot) -> None
      async def summary(self, window: MetricsWindow) -> ProgressSummary
      async def money_by_currency(self, window: MetricsWindow) -> list[CurrencyTotal]
      async def throughput(self, window: MetricsWindow, bucket: ThroughputBucket | None = None) -> list[ThroughputPoint]
      async def autofix_outcomes(self, window: MetricsWindow) -> list[AutofixOutcome]
      async def model_efficiency(self, window: MetricsWindow) -> list[ModelEfficiencyRow]
      async def recent_activity(self, limit: int = 50, *, after_id: int | None = None) -> list[ActivityEvent]
  ```
- Models in `cashapp.services.metrics.models` are frozen Pydantic. The enums are in `cashapp.domain.metrics`.
  ```python
  class AwaitingReceipt:  count: int; oldest_age_days: int | None; aging_limit_days: int
  class OpenExceptions:   total: int; locked: int; dead_lettered: int
  class ProgressSummary:  window: MetricsWindow; start: datetime; end: datetime
                          receipts_matched: int; done_items: int
                          automation_rate: float | None          # 0..1
                          awaiting_receipt: AwaitingReceipt; open_exceptions: OpenExceptions
                          autofix_rate: float | None; human_correction_rate: float | None
  class CurrencyTotal:    currency: CurrencyCode; amount: MoneyStr; receipts: int; residual: MoneyStr
  class ThroughputPoint:  at: datetime; applied: int; escalated: int      # bucket start, UTC
  class AutofixOutcome:   error_code: ErrorCode; count: int; fixed: int; rate: float | None
  class ModelEfficiencyRow: role: LlmRole; model_id: str; calls: int
                          cost_basis: CostBasis                      # PER_CALL | CLUSTER
                          cost_usd: MoneyStr | None; cost_unknown_share: float | None
                          agreement_rate: float | None; human_correction_rate: float | None
                          accuracy: float | None; accuracy_n: int
  class ActivityEvent:    id: int; at: datetime; kind: ActivityKind; item_id: int | None; text: str
  ```
- Rates are floats from 0 to 1, and `None` means unmeasured. `MetricsWindow` is `"24h" | "7d" | "30d" | "mtd"`.

**C. HTTP and SSE.** Consumers: assistant-chat-redesign's live-context panel (`/metrics/summary`), html-progress-reports' preview and the web client.
- Routes, all `REPORTS_READ`, with `window` defaulting to `7d`:
  - `GET /metrics/summary?window=` returns `{window, as_of, data: ProgressSummary}`
  - `GET /metrics/money-by-currency?window=` returns `data: CurrencyTotal[]`
  - `GET /metrics/throughput?window=&bucket=hour|day` returns `data: ThroughputPoint[]`
  - `GET /metrics/autofix?window=` returns `data: AutofixOutcome[]`
  - `GET /metrics/models?window=` returns `data: ModelEfficiencyRow[]`
  - `GET /metrics/activity?window=&limit=1..200` returns `data: ActivityEvent[]`
- In JSON, money is a `"^-?\d+\.\d{2}$"` string and times are ISO-8601 UTC.
- `GET /metrics/stream?window=` (`text/event-stream`):
  - frame `event: summary`, `data: {window, as_of, data: ProgressSummary}`, sent on connect and then only when changed
  - frame `event: activity`, `data: ActivityEvent`, one per new history row
  - `id:` is the latest history id, and `Last-Event-ID` resumes after it
  - `: ping` every 15 s
  - header `X-Accel-Buffering: no`
  - a failure after start is `event: stream-error`, `data: {code, message}`

**D. Chat tool `metrics.read`.** Consumer: assistant-chat-redesign, which renders it.
- Input `MetricsReadIn{metric: MetricName, window: MetricsWindow = "7d"}`.
- Output `MetricsReadOut{metric, window, as_of, data: <the matching model or list above>}`.
- Group `METRICS`, `REPORTS_READ`, read-only, no confirm.
- `tool_finished.result_card` is a `table_card` (registry schema) for the list metrics, and a `state_card` for `summary`.

## Assumptions

- A1: The SSE is a per-connection DB read on the flow stream's tick, with a history-id cursor and a single-flight feed. "No polling loop" is read as no external poller and no bus emission. The outbox signal isn't reusable: the relay consumes it and it doesn't cross processes.
- A2: `cost_basis = CLUSTER` for `provider = "oci"` rows (Cohere on a dedicated cluster has no per-call cost). The board shows "cluster" and "n/a", and nothing is imputed. This is an additive field to the story's `ModelEfficiencyRow`.
- A3: Accuracy, human correction and agreement follow §4. Agreement is on the adjudicator row only, and accuracy and human correction are on the reader rows only, matching the board's sample table.
- A4: The dashboard window is in `?window=` and is fetched on the server (no new Next proxy route). `mtd` exists in the API for html-progress-reports, but the UI shows only `24h | 7d | 30d`.
- A5: `useEventStream` gains an optional `query` option so the path stays a registered literal. Otherwise the signature is the existing hook's, moved to `web/hooks/` with no re-export.
- A6: If chat-agent-tool-registry's `ToolContext.services` carries no runtime config, the tool reads `get_runtime_config()`.
- A7: Activity text is built from structured fields only (item id, currency amount, receipt number, error-code label), never from payer names or reasoning, because those stay out of a broadcast feed.
