# live-progress-dashboard: Live metrics API, SSE and the Progress dashboard

- Issue: #48 (AC 2, scope item 4)
- breaking: false
- Design screen owned: **Dashboard** (`design/project/glass/Dashboard.dc.html`, design.md §3.1)

## Story

As an AR lead, I want a live Progress dashboard showing receipts matched, money applied by currency, throughput, auto-fix outcomes, live activity and model efficiency, so that I can see at a glance how well the cash app is doing right now.

## Context

research.md a1 and its metric-honesty rules: money per currency as Decimal strings, never summed across currencies; no "accuracy" without ground truth (show cost with the null-cost share, adjudicator agreement, auto-fix rate, human-correction rate; accuracy only where people corrected, with n); every tile states its window. Nearest existing code: `api/routers/reports.py`, `api/routers/llm_usage.py` (`/daily`, `/cohere-utilisation`), `services/reports/`, `services/llm_usage/`, `services/flow_query.py`, adjudication `disagreements`/`provenance` rows. Load `python-llm-features:reporting-derived-metrics` and `dataviz`.

## Acceptance criteria

1. [unit] `cashapp/services/metrics/service.py` `MetricsService` (the one owner of progress aggregates; html-progress-reports and the chat reuse it): `summary(window) -> ProgressSummary`, `money_by_currency(window) -> list[CurrencyTotal{currency, amount: MoneyStr, receipts, residual: MoneyStr}]`, `throughput(window, bucket) -> list[ThroughputPoint{at, applied, escalated}]`, `autofix_outcomes(window) -> list[AutofixOutcome{error_code, count, fixed, rate}]`, `model_efficiency(window) -> list[ModelEfficiencyRow{role, model_id, calls, cost_usd: MoneyStr | None, cost_unknown_share, agreement_rate | None, human_correction_rate | None, accuracy | None, accuracy_n}]`, `recent_activity(limit) -> list[ActivityEvent{at, kind: APPLIED|RECEIPT_ARRIVED|AUTOFIX|ESCALATED, item_id, text}]`. Window is `24h|7d|30d|mtd`. All queries go through repositories (new `MetricsQueryRepository`).
2. [unit] Definitions pinned in code and docstrings, each with a test: **receipts matched** = items with a reserved receipt and at least one line applied in the window; **automation rate** = DONE items in the window with no USER history entry / all DONE items; **awaiting receipt** count and oldest age vs `aging.awaiting_receipt_max_days`; **open exceptions** with locked and dead-lettered sub-counts; **accuracy** only from human-corrected extractions (n shown), null otherwise; **cost unknown** share = rows with null cost / all rows, never imputed.
3. [unit] Money is never summed across currencies anywhere in the service or schemas (test asserts no field mixes currencies); amounts are 2 dp `ROUND_HALF_UP` strings.
4. [api] New auto-discovered router `metrics.py` (REPORTS_READ): `GET /metrics/summary?window=`, `/metrics/money-by-currency`, `/metrics/throughput`, `/metrics/autofix`, `/metrics/models`, `/metrics/activity`, each returning `{window, as_of, data}`; plus `GET /metrics/stream` (SSE) emitting `summary` on change (driven by the outbox relay / history writes, no polling loop), `activity` per new event, a heartbeat every 15 s, `X-Accel-Buffering: no`. OpenAPI regenerated.
5. [unit] Chat tool `metrics.read {metric, window}` (group METRICS, REPORTS_READ, read-only) registered in `cashapp/services/chat/tools/metrics.py` over `MetricsService`.
6. [browser] Dashboard board: `/dashboard` shows the top bar "Progress" with env, Live, Sample data and the `24h | 7d | 30d` segmented control; the KPI row (Receipts matched with "Reserved and at least one line applied", Automation rate as a 72px ring with "no human touch", Awaiting receipt with oldest age of the aging limit, Open exceptions with locked and dead-lettered counts).
7. [browser] Dashboard board: one money tile per currency (label, mono amount, "N receipts · residual X") and no cross-currency total; throughput area chart (applied `--acc-hi` with fill, escalated `--warn` dashed, legend, peak/h); auto-fix outcomes table with the 6px meter (ok when rate > 60% else warn); model efficiency table (Role, Model, Calls, Cost, Cost unknown, Agreement, Human corr., Accuracy "x% · n N" only where corrected) with footer pills (auto-fix rate, human-correction rate, Cohere cluster utilisation from `/llm-usage/cohere-utilisation`).
8. [browser] Dashboard board: the live activity feed updates over `/metrics/stream` without a reload (header pill "Streaming · N s ago"); switching the window refetches every tile and each tile states its window.
9. [browser] Dashboard board states: loading (KPI skeletons), empty ("Nothing completed in this window" with Show 30 days and Open Flow), error ("Couldn't load the aggregates", tiles marked stale with the last-good time, Retry).
10. [unit] Components in `web/components/dashboard/` (money-by-currency, throughput-chart, autofix-table, model-efficiency-table, activity-feed) built only from glass-theme-shell's common components and `ui/chart.tsx`; chart colours from `--chart-*`; one `useEventStream` hook in `web/hooks/` (owner: this story) used by every SSE consumer in the web app.

## Out of scope

- HTML export of these figures (html-progress-reports). Engine lag/DLQ (engine-control-api).

## Deps

- glass-theme-shell: `GlassPanel/PanelHeader/PanelBody`, `KpiCard` ring/meter variants, `Pill`, `Meter`, `Segmented`, `StateCard`, `SkeletonRows`, `DataTable`, `TopBar` slot API. plannable: true.
- chat-agent-tool-registry: `ToolSpec`, `TOOLS` discovery. plannable: true.

## Assumptions

- "Model efficiency" accuracy has no ground truth beyond human corrections (research.md); the column is blank with "n 0" elsewhere.
- The SSE uses the same change mechanism as the existing flow SSE (`api/routers/flow.py`, `web/app/api/stream/[...path]`); the planner cites it. It is a per-connection stream, not a third poller (non-negotiable 5): it emits nothing to the bus.
