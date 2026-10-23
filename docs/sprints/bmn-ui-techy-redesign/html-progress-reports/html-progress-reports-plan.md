# Plan: html-progress-reports

Story: [story.md](story.md). Board: `design/project/glass/Reports.dc.html` (design.md §3.8). Skills applied: python-web-app:building-python-web-apps (routes → services → repositories), python-web-app:rendering-untrusted-content (autoescape, no trust bypass, assert escaped form present), python-llm-features:reporting-derived-metrics (None never rendered as 0, footnote names only measured values), nextjs-fullstack-standards + bmn `references/nextjs.md`.

## 1 Approach

- research.md a1 "metric honesty": every figure comes from live-progress-dashboard's `MetricsService` (the one aggregate owner) plus the existing aging query; money per currency as strings, never summed; accuracy only with n; cost-unknown share stated, never imputed.
- One server-side renderer: Jinja2 (`autoescape=True`, `StrictUndefined`, no `|safe`/`Markup` anywhere) renders a light, print-safe document with inline `<style>`, system font stacks, an inline SVG throughput line and a `Content-Security-Policy` meta (`default-src 'none'; style-src 'unsafe-inline'`). The preview and the export are the same bytes (one code path), so "what you see is what you email".
- Transmission: a new auto-discovered router `reports_html.py` (`/reports/html/*`, REPORTS_READ). The export records a `REPORT_EXPORT` log row in the same transaction after a successful render; the HTML itself is not stored (story assumption) and re-download regenerates it.
- Chat: `reports.export` registers through chat-agent-tool-registry's `TOOLS` discovery and calls the same `HtmlReportService.export` as the router (research.md Amendment: one action path), returning an `export_card`.
- Web: `/reports` keeps being a Server Component; one client leaf (`ReportBuilder`) holds the form, fetches the preview through a thin route handler and shows it in `<iframe sandbox srcdoc>` (scripts disabled). Existing report panels stay below, restyled through glass-theme-shell components only (non-negotiable 7).

## 2 Files to create / change

### API (`api/`)

| File | New/Change | Purpose |
|---|---|---|
| `pyproject.toml`, `uv.lock` | change | add `jinja2>=3.1` (`uv add jinja2`); not a dependency today. |
| `src/cashapp/domain/reports.py` | change (append) | `HtmlReportKind(StrEnum)`: `PROGRESS_SUMMARY`, `EXCEPTIONS_AGING`, `MODEL_EFFICIENCY` (value = name, like `ReportKind`). `ReportWindow(StrEnum)`: `D7="7d"`, `D30="30d"`, `MTD="mtd"` (a subset of the dashboard's window; maps 1:1 to its window enum). `ReportSection(StrEnum)`: `HEADLINE`, `MONEY_BY_CURRENCY`, `THROUGHPUT`, `EXCEPTIONS_BY_REASON`, `MODEL_EFFICIENCY`. `DEFAULT_SECTIONS: Final[Mapping[HtmlReportKind, frozenset[ReportSection]]]` (progress: headline, money, throughput; exceptions: headline, exceptions; models: headline, models). `FILENAME_PREFIX` (`progress`, `exceptions`, `models`). `report_filename(kind, window, day) -> str` = `"{prefix}_{window}_{YYYY-MM-DD}.html"`. Pure. |
| `src/cashapp/services/reports/daily_summary.py` | change | extract the existing aging bucketing into `async def aging_counts(uow, as_of: datetime) -> tuple[AgingBucketCount, ...]` (same `ReportQueryRepository.open_item_ages` query); `daily_summary` calls it. No new query (AC2). |
| `src/cashapp/services/reports/html_figures.py` | new | `ReportFigures` frozen dataclass (kind, window, sections, start, end, as_of, env, summary, money, throughput, exceptions_by_reason, aging, oldest_exceptions, models, caveats). `async gather_figures(uow, metrics: MetricsService, exceptions: ExceptionsQueryService, kind, window, sections, now) -> ReportFigures`: calls only the methods its sections need: `summary` (HEADLINE), `money_by_currency` (MONEY_BY_CURRENCY), `throughput(window, "day")` (THROUGHPUT), `autofix_outcomes` (EXCEPTIONS_BY_REASON, plus `aging_counts` and the 5 oldest rows from `ExceptionsQueryService.list` sorted by age when kind is EXCEPTIONS_AGING), `model_efficiency` (MODEL_EFFICIENCY and the caveat). `Caveats{accuracy_n: int, cost_unknown_share: Decimal \| None}`: `accuracy_n` = sum of rows' `accuracy_n`; `cost_unknown_share` = calls-weighted mean of the rows' shares, `None` when total calls is 0. `has_data` = summary shows any completed item or any throughput point > 0. Imports no SQLAlchemy. |
| `src/cashapp/services/reports/html_export.py` | new | `RenderedReport` frozen dataclass `{filename: str, html: str, bytes: int, generated_at: datetime, has_data: bool}`. `HtmlReportRenderer(metrics, exceptions, clock, env_label)` with `async render(uow, kind: HtmlReportKind, window: ReportWindow, sections: frozenset[ReportSection]) -> RenderedReport` (AC1 signature plus the unit of work), and the pure `render_document(figures) -> str`. Module-level Jinja `Environment(loader=PackageLoader("cashapp.services.reports", "templates"), autoescape=True, undefined=StrictUndefined, trim_blocks=True)`. Pure helpers: `throughput_path(points, width=400, height=100) -> str` (SVG path; flat baseline when all zero or one point), `format_range(start, end)` ("16 – 23 October 2026"), `as_of_stamp(dt)` ("As of 14:02 UTC"), `generated_stamp(dt)` ("Generated 23 Oct 2026, 14:02 UTC"), money via `cashapp.domain.money` (`CCY 1,234.00`, 2 dp ROUND_HALF_UP). `bytes` = `len(html.encode("utf-8"))`. |
| `src/cashapp/services/reports/templates/progress_report.html.j2` | new | The export document, matching the board's `article.doc`: `<!doctype html>`, `<meta charset>`, CSP meta, `<title>Cash application progress</title>`, one inline `<style>` (light paper: `#fbfbfd` ground, `#151922` text, `#5d6778` labels, `#eef1f5` tiles, `#d6dbe3` rules, `#2f5bdb` line; `@media print`), system stacks only (`ui-sans-serif, system-ui, …` and `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`). Each section wrapped in `<section data-section="{{ name }}">`; only included sections are emitted. Header: mono label "Cash application progress", h1 range, generated stamp; "As of HH:MM UTC". Headline tiles: Receipts matched, Automation rate, Open exceptions, Awaiting receipt (unmeasured → "—" with "not measured", never 0). Money table: Currency / Applied / Receipts / Residual, one row per currency, no total row. Throughput `<svg role="img" aria-label="Items done per day, …">` with the path. Exceptions by reason table (error code, count, fixed %) plus, for EXCEPTIONS_AGING, the aging buckets and the oldest 5 (item, payer as the workbench shows it, amount, age). Model efficiency table (Role, Model, Calls, Cost, Cost unknown, Agreement, Human corr., Accuracy "x% · n N" or "—"). Footnote always present: "Accuracy appears only for the N items people corrected." / "No items were corrected by people in this window, so accuracy is not shown." and "Model cost excludes X% of calls with no recorded cost." / "No model calls in this window." No `<script>`, no `<link>`, no `@import`, no `http` URL, no `on*` attribute. |
| `src/cashapp/services/reports/html_service.py` | new | `HtmlReportService(renderer)`: `preview(uow, kind, window, sections) -> RenderedReport`; `export(uow, principal, kind, window, sections) -> tuple[RenderedReport, ReportExportInfo]` (raises `NothingToReport` when `has_data` is false; renders first, then adds the row; the caller commits); `recent(uow, limit) -> list[ReportExportInfo]`; `redownload(uow, export_id) -> RenderedReport` (re-renders the stored kind/window/sections now, keeps the stored filename; `ExportNotFound`). `ReportExportInfo` frozen dataclass (id, kind, window, sections, filename, bytes, actor, actor_name, at). Takes the `Principal` as a plain argument; no Request/Response. |
| `src/cashapp/services/reports/__init__.py` | change | re-export the new public names. |
| `src/cashapp/data/models/report_export.py` | new | `ReportExport` ORM model, table `report_export` (section 4). Auto-imported by `alembic/env.py`. |
| `src/cashapp/data/repositories/report_exports.py` | new | `ReportExportRepository(BaseRepository[ReportExport])` + `recent(limit) -> list[ReportExport]` ordered by `at desc, id desc`. Flushes, never commits. |
| `alembic/versions/s48_report_export.py` | new | the one migration (section 4). |
| `src/cashapp/api/schemas/reports.py` | change (append) | `HtmlExportRequest{kind: HtmlReportKind, window: ReportWindow, sections: list[ReportSection]}` (min 1, de-duplicated; extra forbidden), `ReportExportOut{id, kind, window, sections, filename, bytes, actor_name, at}`, `ReportExportsResponse{data: list[ReportExportOut]}`. |
| `src/cashapp/api/routers/reports_html.py` | new | auto-discovered `router = APIRouter(prefix="/reports/html", tags=["reports"])`; endpoints in section 7. Builds the service from the dashboard's `MetricsService` dependency and `ExceptionsQueryService(runtime)`. Maps `NothingToReport` → 422 `nothing_to_report`, `ExportNotFound` → 404 `not_found`, a render/aggregate failure (timeout, `SQLAlchemyError`) → 503 `report_failed` "The export didn't finish. No file was created." with nothing committed. HTML responses carry `Content-Type: text/html; charset=utf-8`, `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox`, `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`, `X-Report-Has-Data: true\|false`. `main.py` untouched. |
| `src/cashapp/services/chat/tools/reports.py` | new | `TOOLS = [ToolSpec(name="reports.export", group=ToolGroup.REPORTS, permission=Permission.REPORTS_READ, mutating=False, confirm_required=False, audit_label="Export HTML report", input_model=ReportsExportInput, output_model=ExportCard, handler=export_report, preview=None)]`. Handler opens a unit of work from `ToolContext.uow_factory`, calls `HtmlReportService.export` with `ctx.principal`, commits, returns the registry's `export_card` (section 7). |
| `web/lib/api/openapi.json` (+ generated types) | change | regenerated with `npm run api:sync` after the API is in (the OpenAPI half of AC3). |

### Web (`web/`)

| File | New/Change | Purpose |
|---|---|---|
| `components/ui/checkbox.tsx` | new (CLI) | `npx shadcn@latest add checkbox` (not hand-written). `select` already exists. |
| `lib/reports/schemas.ts` | change (append) | Zod: `htmlReportKind` enum, `htmlWindow` enum `7d\|30d\|mtd`, `htmlSection` enum, `htmlReportParams = z.object({kind, window, sections: z.array(htmlSection).min(1)})`, `parseBuilderSearchParams(sp)` (defaults Progress summary / 7d / the kind's default sections; lets the chat's preview link pre-fill the form), `reportExportOut`, `DEFAULT_SECTIONS` mirror typed `satisfies Record<…>` (labels only; the API is the authority). |
| `lib/reports/html.ts` | new | pure: `previewUrl(params)` (`/api/reports/html/preview?kind=&window=&sections=&sections=`), `filenameFromDisposition(header) -> string \| null`, `SECTION_LABELS`, `KIND_LABELS`, `WINDOW_LABELS` (`Last 7 days`, `Last 30 days`, `Month to date`). |
| `app/api/reports/[report]/preview/route.ts` | new | `GET`: `getSession()` → 401; `report !== "html"` → 404; Zod-validate query → 422 envelope; proxy to `GET /reports/html/preview` via `apiFile`; pass through only `Content-Type`, `X-Report-Has-Data`, set `Cache-Control: private, no-store` and the CSP header. `RouteContext<"/api/reports/[report]/preview">`. (Kept under `[report]` so a static `html/` segment never shadows `[report]/export`.) |
| `app/api/reports/[report]/export/route.ts` | change | existing `GET` (CSV/XLSX) unchanged; add `POST` for `report === "html"`: session → 401, `Origin` must equal the app origin → 403 (API-17), `Content-Type: application/json` → else 415, Zod body → 422, proxy to `POST /reports/html/export`, pass through `Content-Type` + `Content-Disposition` only. |
| `app/api/reports/[report]/exports/[id]/route.ts` | new | `GET` (report `html`, numeric id) → `GET /reports/html/exports/{id}/file` attachment; the chat card's Download link. |
| `lib/api/file.ts` | change only if needed | add a `method`/`body` option for the POST proxy if `apiFile` is GET-only today; no second fetch helper. |
| `app/(shell)/reports/page.tsx` | change | Server Component: `TopBar` title "Reports" with env pill, Sample data pill (from the shell's `/me` flags) and an ok `Pill` with dot "Preview updates live"; split row (form column `flex 1 1 300px`, preview `flex 999 1 560px`, wraps on narrow): `<ReportBuilder initial={…} recent={…}/>`; fetches `GET /reports/html/exports?limit=10` with `Promise.all` alongside the existing tab data (DF-4); 403 → `ForbiddenState`. Below the builder, the existing `ReportsTabs` (daily / partial) panels. |
| `components/reports/report-builder.tsx` | new (`"use client"`) | Form state (kind, window, sections) in `GlassPanel` "Build a report": `MonoLabel` "Report" + `ui/select` (Progress summary \| Exceptions aging \| Model efficiency), "Window" select (Last 7 days \| Last 30 days \| Month to date), "Sections" `ui/checkbox` list (Headline numbers, Money by currency, Throughput, Exceptions by reason, Model efficiency; changing Report resets to its defaults), primary `Button` "Export HTML" (glow), caption "A single self-contained file with inline styles and no scripts. Safe to email."; renders `<ReportPreview>` and `<RecentExports>`. Export: `fetch` POST, blob → object URL download with the filename from `Content-Disposition`, then `router.refresh()` so Recent exports shows the new row; failures kept in state (TEST-25). Export disabled when no section is ticked, while exporting, or when the preview says no data. |
| `components/reports/report-preview.tsx` | new (`"use client"`) | Preview `GlassPanel`: header `MonoLabel` "Preview · what you export" + mono "As of HH:MM UTC" (from the document's `data-as-of`); body `<iframe title="Report preview" sandbox="" srcDoc={html}>` (no `allow-scripts`, no `allow-same-origin`). Refetches on every param change (250 ms debounce, `AbortController` cancels the stale request), no reload. States through `StateCard`/`SkeletonRows`: loading "Loading · preview" (skeletons), empty "Nothing to report yet" / "No item finished in this window. Export unlocks when there is data.", error "Error · export" "The export didn't finish" / "The report query timed out. No file was created." + "Try again" (re-runs the failed preview or export). Reports `hasData` up to the builder. |
| `components/reports/recent-exports.tsx` | new | `GlassPanel` "Recent exports": rows of mono filename (12.5px) and "who · when" (`J. Stevenson · 13:40` today, `20 Oct` otherwise) in `--soft`; empty "No exports yet". |
| `components/reports/{aging-table,failures-by-code-chart,daily-summary-view,daily-summary-actions,export-buttons,partially-paid-table,partially-paid-view,report-date-picker,report-load-error,reports-tabs}.tsx` | change (restyle) | Wrap in `GlassPanel`/`PanelHeader`/`PanelBody`, tables through extended `DataTable` (mono uppercase headers, right-aligned mono numbers), statuses through `Pill`/`status-badge`, errors through `StateCard` error; no per-page CSS, no colour literals. CSV/XLSX links and their route unchanged (AC8). |
| `app/(shell)/reports/loading.tsx`, `error.tsx` | change | `StateCard` loading / error (error.tsx stays `"use client"`, generic message + digest, TEST-20/21). |

Shared components used, never redefined (owner glass-theme-shell): `TopBar`, `GlassPanel`, `PanelHeader`, `PanelBody`, `Pill`, `MonoLabel`, `StateCard`, `SkeletonRows`, `DataTable`, `Button`. `Segmented` is not used: the board draws Window as a select.

### UI checklist (lesson L-admin-act-for-absent-owner-1; coder ticks each in validation.md)

Reports board, design.md §3.8:
- [ ] Top bar: "Reports" (18/600), `DEV`/`PROD` warn mono pill, muted "Sample data" pill (only when API reports sample data), ok pill with glowing dot "Preview updates live" pushed right.
- [ ] Form panel header "Build a report"; labels `REPORT`, `WINDOW`, `SECTIONS` in `MonoLabel`.
- [ ] Report options: Progress summary, Exceptions aging, Model efficiency. Window options: Last 7 days, Last 30 days, Month to date.
- [ ] Section checkboxes in order: Headline numbers, Money by currency, Throughput, Exceptions by reason, Model efficiency; accent `--acc-hi`, 16px, rows min-height 32.
- [ ] Primary "Export HTML" (`--acc` fill, `--acc-hi` border, glow `0 0 24px -8px`); caption "A single self-contained file with inline styles and no scripts. Safe to email." 12.5px `--soft`.
- [ ] Recent exports panel: mono filename 12.5px, "who · when" in `--soft`, hairline row dividers, last row no border.
- [ ] Preview glass panel: label "Preview · what you export", mono "As of HH:MM UTC" right, 16px padding; document in light paper style inside a sandboxed iframe.
- [ ] Document: mono uppercase label "Cash application progress", 28px/600 range h1, "Generated <d Mon yyyy>, HH:MM UTC" 12px; 4 headline tiles (`#eef1f5`, radius 10, 24px mono numbers); "Money applied by currency" table (Currency, Applied, Receipts; mono right-aligned amounts; no total); "Daily throughput" SVG (stroke `#2f5bdb` 2.5, baseline `#d6dbe3`); footnote 12px `#5d6778`.
- [ ] States: Loading · preview (3 skeleton bars 30/12/70px), Empty "Nothing to report yet" + "No item finished in this window. Export unlocks when there is data." (Export disabled), Error · export (err border `#f8717155`, label `--err-ink`) "The export didn't finish" + "The report query timed out. No file was created." + "Try again".
- [ ] Existing panels (daily summary with aging table and failures-by-code chart, partially paid) below the builder in glass panels; CSV/XLSX buttons as outline buttons.
- [ ] Assistant dock chip "Export this week's report" is the dock's (assistant-chat-redesign); nothing mounted here.
- [ ] Responsive: form column first, preview below when narrow; no horizontal page scroll at 375 px; tables scroll inside their card.

Next.js rule ids applied: non-negotiables 1, 3, 4, 7, 14; TS-5, TS-13, TS-15, TS-16, TS-17, TS-19, TS-20, TS-23, TS-28, TS-30, TS-31, TS-32, TS-34; API-1, API-2, API-3, API-4, API-5, API-8, API-9, API-10, API-12, API-13, API-14, API-17, API-20, API-23, API-29; DF-3, DF-4, DF-9 (no SWR), DF-10, DF-22; RC-5, RC-6, RC-7, RC-8, RC-13; SEC-5, SEC-16, SEC-18, SEC-30; TEST-1, TEST-2, TEST-9, TEST-14, TEST-15, TEST-17, TEST-20, TEST-21, TEST-25.

## 3 Test plan

Nobody writes or runs these until step 5. API tests use the repo's pytest fixtures (sqlite unit of work, fake clock, auth overrides); `MetricsService` is replaced with a recording fake that returns typed dashboard models.

| AC | Test | Path | Type |
|---|---|---|---|
| 1 | `test_render_has_no_script_tag` | `api/tests/services/reports/test_html_export.py` | unit |
| 1 | `test_render_has_no_http_url_link_or_import` (no `http`, `<link`, `@import`; CSP meta present) | same | unit |
| 1 | `test_payer_name_img_onerror_is_escaped` (payer `<img src=x onerror=alert(1)>` in the oldest-exceptions row: raw absent, `&lt;img src=x onerror=alert(1)&gt;` present inside that `<section>`) | same | unit |
| 1 | `test_no_event_handler_attributes` (regex `\son\w+=` finds none) | same | unit |
| 1 | `test_section_toggled_off_is_absent[<each ReportSection>]` (no `data-section` and no heading for that section) | same | unit |
| 1 | `test_money_rows_per_currency_without_total` | same | unit |
| 1 | `test_title_range_and_as_of_stamp` (frozen 2026-10-23 14:02Z, 7d → "16 – 23 October 2026", "As of 14:02 UTC", "Generated 23 Oct 2026, 14:02 UTC") | same | unit |
| 1 | `test_mtd_and_30d_ranges` | same | unit |
| 1 | `test_throughput_svg_inline_path` and `test_throughput_flat_when_all_zero_or_single_point` | same | unit |
| 1 | `test_caveat_footnote_names_measured_values` (n 212, 0.4%) | same | unit |
| 1 | `test_caveat_footnote_when_unmeasured` (n 0 and zero calls → the explicit sentences; no "0.0%") | same | unit |
| 1 | `test_unmeasured_headline_renders_dash_not_zero` | same | unit |
| 1 | `test_rendered_report_filename_bytes_generated_at` | same | unit |
| 1 | `test_templates_contain_no_trust_bypass` (no `\|safe`, `Markup(`, `autoescape false` in templates and module) | same | unit |
| 1 | `test_report_filename_per_kind` | `api/tests/domain/test_reports_html_vocab.py` | unit |
| 2 | `test_gather_calls_only_metrics_methods_for_selected_sections` | `api/tests/services/reports/test_html_figures.py` | unit |
| 2 | `test_html_report_modules_import_no_sqlalchemy` (html_export, html_figures, html_service) | same | unit |
| 2 | `test_aging_counts_matches_daily_summary_buckets` | same | unit |
| 2 | `test_cost_unknown_share_is_calls_weighted_and_none_without_calls` | same | unit |
| 3 | `test_preview_returns_text_html_with_csp_and_has_data_header` | `api/tests/api/test_reports_html.py` | api |
| 3 | `test_preview_requires_reports_read` (403) | same | api |
| 3 | `test_preview_rejects_unknown_kind_window_or_no_sections` (422) | same | api |
| 3 | `test_export_returns_attachment_and_records_row` (Content-Disposition filename, row fields kind/window/sections/filename/bytes/actor/at) | same | api |
| 3 | `test_export_body_equals_preview_body` | same | api |
| 3 | `test_export_failure_records_no_row` (aggregate raises → 503 `report_failed`, zero rows) | same | api |
| 3 | `test_export_empty_window_is_422_nothing_to_report` | same | api |
| 3 | `test_exports_list_recent_first_and_limit_bounded` (default 10, max 50, 422 above) | same | api |
| 3 | `test_export_file_redownload_and_404` | same | api |
| 3 | `test_openapi_lists_html_report_routes` | same | api |
| 3 | `test_report_export_migration_single_head` (`alembic heads` = 1; table and index exist) | `api/tests/data/test_report_export_migration.py` | unit (+ `atp` marker variant `test_report_export_upgrade_on_atp`) |
| 3 | `GET /api/reports/html/preview`: 401 no session, 404 report≠html, 422 bad query, passes text/html + CSP only | `web/tests/app/api/reports/html-preview-route.test.ts` | unit (route as plain function, TEST-9) |
| 3 | `POST /api/reports/html/export`: 403 foreign Origin, 415 non-JSON, 422 bad body, attachment passthrough, error envelope | `web/tests/app/api/reports/html-export-route.test.ts` | unit |
| 3 | existing `GET` CSV/XLSX export still proxies | same | unit |
| 3 | `GET /api/reports/html/exports/[id]` proxies attachment, 422 non-numeric id | `web/tests/app/api/reports/html-export-file-route.test.ts` | unit |
| 4 | `test_reports_export_tool_spec` (group REPORTS, REPORTS_READ, mutating False, confirm_required False, in `TOOLS`) | `api/tests/services/chat/tools/test_reports_tool.py` | unit |
| 4 | `test_reports_export_returns_export_card` (filename, bytes, preview_url, download_url) | same | unit |
| 4 | `test_reports_export_records_same_row_as_router` | same | unit |
| 4 | `test_reports_export_not_offered_without_reports_read` | same | unit |
| 5 | `previewUrl`, `filenameFromDisposition`, `parseBuilderSearchParams` defaults and chat pre-fill | `web/tests/lib/reports/html.test.ts` | unit |
| 5 | `ReportBuilder` renders labels, options, five sections, primary button and caption; changing Report resets sections | `web/tests/components/reports/report-builder.test.tsx` | unit |
| 5 | `RecentExports` mono filename and "who · when", empty copy | `web/tests/components/reports/recent-exports.test.tsx` | unit |
| 6 | `ReportPreview` iframe has `sandbox=""` and `srcdoc`, refetches on param change, aborts stale request | `web/tests/components/reports/report-preview.test.tsx` | unit |
| 7 | `ReportPreview` loading, empty (export disabled), error copy and Try again | same | unit |
| 5 | `reports board shows top bar, build-a-report form and recent exports` (Reports board) | `web/e2e/reports.spec.ts` | browser |
| 6 | `reports board preview updates live without a reload` (change Window, then Sections; iframe content changes; `page` never navigates) | same | browser |
| 6 | `reports board preview iframe is sandboxed with scripts disabled` | same | browser |
| 6 | `reports board export downloads the same html as the preview` (download event; bytes equal preview srcdoc; filename `progress_7d_<date>.html`; Recent exports gains the row) | same | browser |
| 7 | `reports board loading state shows preview skeletons` | same | browser |
| 7 | `reports board empty window shows nothing to report and disables export` | same | browser |
| 7 | `reports board export error shows try again and creates no file` | same | browser |
| 8 | `reports board keeps restyled report panels with working csv and xlsx exports` | same | browser |
| 5 | `reports board has no horizontal scroll at 375px` | same | browser |

Totals: 52 named test rows (43 unit/api, 9 browser); parametrised families count once. Mock API fixtures for e2e go in `web/tests/support/fixtures/reports-html.ts` (preview HTML, empty, 503).

## 4 Data

- Model `ReportExport` (`data/models/report_export.py`), table `REPORT_EXPORT`:
  - `id` identity PK (`identity_pk()`), `kind` `StrEnumType(HtmlReportKind)` not null, `window` `String(8)` not null, `sections` `JsonDoc()` (list of section names) not null, `filename` `String(120)` not null, `bytes` `Integer` not null, `actor` `String(255)` (principal subject) not null, `actor_name` `String(255)` not null, `at` `UtcDateTime()` not null.
  - `PK_REPORT_EXPORT`, index `IX_REPORT_EXPORT_AT` on (`at`).
  - The HTML is not stored; no remittance content in the row.
- One Alembic revision: `api/alembic/versions/s48_report_export.py`, `revision = "s48_report_export"`, `down_revision` = the head when coded (`s45_retention_purge` today). split.md migration order is chat-agent-tool-registry → db-stored-settings → engine-control-api → **html-progress-reports** → matching-lab-replay-api: the merger re-points `down_revision` to engine-control-api's revision and matching-lab-replay-api's onto `s48_report_export`, keeping one head. Style follows `s45_retention_purge.py` (BigInteger identity with sqlite variant, named constraints, `downgrade` drops index then table). DEV ATP only; never run by the planner or coder.

## 5 Config / env

- No new env variables. No new DB config keys required.
- Reads existing settings only: env label (`cashapp.settings` env, as `ReportService._env_label`) and the dashboard's window handling. Export list limit (default 10, max 50) and preview debounce (250 ms) are constants, not settings (UI tuning, not business rules).
- Web: no new `NEXT_PUBLIC_*`; app origin for the Origin check from the existing server env module.

## 6 Risks and coder gates

- **Dep contracts not merged yet** (lesson L-comparison-wizard-from-fusion-2): the coder starts from the sprint tip after live-progress-dashboard, glass-theme-shell and chat-agent-tool-registry are merged; never stubs `services/metrics/*`, `components/common/*` or `services/chat/tools/registry.py`. Names it relies on are pinned in their stories; any rename there is followed here, not shimmed.
- **Window bounds**: the range line needs the window's start/end. Use the bound helper the dashboard exposes with its window enum; do not re-derive window maths here (one owner). If the dashboard has none at merge time, raise it to the dashboard's owner instead of copying.
- **PII in an emailed file**: payer names appear only in the EXCEPTIONS_AGING oldest-rows table and only as the exceptions workbench shows them (masked if it masks). Everything untrusted is autoescaped; CSP meta and iframe sandbox are defence in depth.
- **Iframe**: `sandbox=""` without `allow-same-origin` means the preview cannot read app cookies; `srcdoc` avoids a second authenticated URL.
- **Download via blob**: large reports are small (tens of KB); no streaming needed. Re-download regenerates with current figures (stored filename kept) because the HTML is not stored.
- **Slow aggregates**: a timeout surfaces as 503 `report_failed` with no row written; the UI shows the board's error copy.
- **Next 16 APIs** (`RouteContext`, async `params`): read `web/node_modules/next/dist/docs` route handler pages before coding (web/AGENTS.md).
- Gates (coder runs these only, no tests):
  - api: `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`
  - web: `cd web && npx eslint . && npx next typegen && npx tsc --noEmit` (run `npm ci` first in a fresh worktree; `npm run api:sync` after the API change).

## 7 Interfaces provided

No story lists `html-progress-reports` in its deps. Contracts other stories touch, pinned so they can build in the same wave:

1. **assistant-chat-redesign** (renders `export_card`; schema owned by chat-agent-tool-registry in `api/schemas/chat.py`). plannable: true. This story fills it as:
   `export_card {type: "export_card", filename: str ("progress_7d_2026-10-23.html"), bytes: int, self_contained: true, preview_url: "/reports?kind=<KIND>&window=<w>&sections=<S>&sections=<S>", download_url: "/api/reports/html/exports/<id>"}`. If the registry pins other field names, the registry's names win and this tool maps onto them.
2. **Chat tool** (via chat-agent-tool-registry `TOOLS` discovery): `reports.export`, group `REPORTS`, permission `REPORTS_READ`, `mutating=False`, `confirm_required=False`, input `ReportsExportInput{kind: HtmlReportKind = PROGRESS_SUMMARY, window: ReportWindow = "7d", sections: list[ReportSection] | None (None → kind defaults)}`, output `ExportCard`. plannable: true.
3. **HTTP** (OpenAPI, tag `reports`, all `REPORTS_READ`, errors in the one error shape):
   - `GET /reports/html/preview?kind=<HtmlReportKind>&window=7d|30d|mtd&sections=<ReportSection>` (repeatable) → `200 text/html`, headers `X-Report-Has-Data`, CSP.
   - `POST /reports/html/export` body `{kind, window, sections}` → `200 text/html` + `Content-Disposition: attachment; filename="<file>"`; `422 nothing_to_report`; `503 report_failed`.
   - `GET /reports/html/exports?limit=1..50 (default 10)` → `ReportExportsResponse{data: [ReportExportOut{id: int, kind, window, sections: [..], filename, bytes: int, actor_name, at: datetime}]}`.
   - `GET /reports/html/exports/{id}/file` → attachment; `404 not_found`.
   - Web proxies: `GET /api/reports/html/preview`, `POST /api/reports/html/export`, `GET /api/reports/html/exports/[id]`.
4. **Python service** for any later consumer: `HtmlReportService.export(uow, principal, kind, window, sections) -> tuple[RenderedReport, ReportExportInfo]`, `HtmlReportRenderer.render(uow, kind, window, sections) -> RenderedReport`. plannable: true.

## Assumptions

- `HtmlReportRenderer.render` takes the unit of work as its first argument (the AC lists only kind/window/sections; figures must be read inside a session).
- "Exceptions by reason" uses `MetricsService.autofix_outcomes(window)` (error code counts in the window); the EXCEPTIONS_AGING kind adds the existing aging buckets (`aging_counts`, extracted from `daily_summary`, same query) and the 5 oldest open exceptions from the existing `ExceptionsQueryService.list`. This is where a payer name can appear, which is what AC1's escaping test exercises.
- Report kinds are presets of sections (story assumption); the title stays "Cash application progress" for every kind.
- Enum values are upper-case names (like `ReportKind`), windows `7d|30d|mtd`.
- Empty = no completed item and no throughput in the window: preview still renders (with `X-Report-Has-Data: false`) so the UI can show the empty state; export refuses with 422.
- Story said export rows follow history-payload retention. Rows hold no remittance content (only kind, window, sections, filename, size, actor), so this story does not add them to the retention purge; deviation recorded, follow-up if Jonathan wants it.
- A `GET /reports/html/exports/{id}/file` endpoint and its web proxy are added beyond AC3, because AC4's export card needs a plain download link.
- The preview is fetched client-side through a route handler (not a Server Action: DF-10, actions never fetch data).
- No rate limit on export: it is a read with a tiny log row, gated by REPORTS_READ.
