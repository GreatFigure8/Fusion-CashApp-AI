# html-progress-reports: Exportable, self-contained HTML progress reports

- Issue: #48 (scope item 5)
- breaking: false
- Design screen owned: **Reports** (`design/project/glass/Reports.dc.html`, design.md §3.8)

## Story

As an AR lead, I want to build a progress report for a window, preview it live and export it as one self-contained HTML file I can email, so that people outside the app can see how cash application is going.

## Context

design.md §3.8: form column + live Preview of the exact export document (light, print-safe, its own stylesheet, no scripts). Figures come only from live-progress-dashboard's `MetricsService` (one owner of aggregates). Existing: `services/reports/{export.py,service.py,...}`, `api/routers/reports.py`, `web/app/api/reports/[report]/export/route.ts`, `components/reports/*` (aging-table, failures-by-code-chart, daily-summary-*, export-buttons, partially-paid-*). Load `python-web-app:rendering-untrusted-content` (payer names and references are untrusted text in the HTML).

## Acceptance criteria

1. [unit] `cashapp/services/reports/html_export.py` `HtmlReportRenderer.render(kind: PROGRESS_SUMMARY|EXCEPTIONS_AGING|MODEL_EFFICIENCY, window: 7d|30d|mtd, sections: set[...]) -> RenderedReport{filename, html, bytes, generated_at}` using Jinja2 with autoescape on, inline CSS only, no `<script>`, no external URLs (fonts are system stacks), daily throughput as inline SVG, money per currency never summed, the accuracy/cost caveat footnote, title "Cash application progress", range, generated stamp "As of HH:MM UTC". Tests assert: no `<script`, no `http` URL, a payer name `<img onerror>` is escaped, every section toggled off is absent.
2. [unit] Figures come only from `MetricsService` and the existing aging/report services; no new aggregate query here.
3. [api] `GET /reports/html/preview?kind=&window=&sections=` (REPORTS_READ) returns the HTML (text/html) used by the preview; `POST /reports/html/export {kind, window, sections}` returns the file (`Content-Disposition: attachment`) and records an export row (new table `REPORT_EXPORT`: id, kind, window, sections, filename, bytes, actor, at); `GET /reports/html/exports?limit=` lists recent exports. OpenAPI regenerated; `app/api/reports/[report]/export/route.ts` proxies the HTML export.
4. [unit] Chat tool `reports.export {kind, window, sections}` in `cashapp/services/chat/tools/reports.py` (group REPORTS, REPORTS_READ, not mutating business data, no confirm) returns an `export_card` (filename, size, preview and download links).
5. [browser] Reports board: `/reports` top bar "Reports", env, Sample data, "Preview updates live"; form column "Build a report" (Report select Progress summary | Exceptions aging | Model efficiency; Window 7d | 30d | MTD; Sections checkboxes Headline numbers, Money by currency, Throughput, Exceptions by reason, Model efficiency; primary "Export HTML"; caption "A single self-contained file with inline styles and no scripts. Safe to email."), Recent exports list (mono filename, who · when).
6. [browser] Reports board: the Preview glass panel shows the export document in its light paper style (sandboxed iframe `srcdoc`, scripts disabled) and changes when any form field changes, without a page reload; Export downloads the same HTML.
7. [browser] Reports board states: loading preview, empty ("Nothing to report yet", export disabled), error ("The export didn't finish … No file was created.", Try again).
8. [browser] Existing report panels that still apply (aging table, failures by code, daily summary, partially paid) render restyled through tokens below the builder; their CSV/XLSX exports keep working.

## Out of scope

- Scheduled or emailed reports (no scheduler). PDF export.

## Deps

- live-progress-dashboard: `MetricsService.summary/money_by_currency/throughput/autofix_outcomes/model_efficiency(window)` and their models. plannable: true.
- glass-theme-shell: `GlassPanel`, `Pill`, `StateCard`, `TopBar`, `Segmented`. plannable: true.
- chat-agent-tool-registry: `ToolSpec`, `TOOLS` discovery, `export_card` result model. plannable: true.

## Assumptions

- "Exceptions aging" and "Model efficiency" report kinds reuse the same renderer with different section sets.
- Export rows are kept for the retention period of history payloads; the HTML itself is not stored (regenerated on demand), so "Recent exports" is a log.
