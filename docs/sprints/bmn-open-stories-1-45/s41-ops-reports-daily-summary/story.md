# s41-ops-reports-daily-summary: Operations reports and the daily summary

- Issue: #41
- Wave: 5 (owns `web/app/(shell)/reports/**`, `web/components/reports/`, `cashapp/services/reports/`, `cashapp/api/routers/reports.py`; appends one hook to `cashapp/pollers/intake/hooks.py`)
- breaking: false

## Story

As AR and management, I want a daily summary and a partially-paid-invoices report, viewable, exportable and emailed, so that we know how the line is doing without opening the app.

## Context

Design screen owned here: design.md §8 "Reports" (`/reports`, tabs Daily summary · Partially paid invoices). No scheduler: generation is on request, or by the intake poller's first cycle after the configured cutover time (`reports.daily_summary_cutover`). Email via s42's `send_report_email`. Statuses come from the shared enum (s02), never redeclared.

## Acceptance criteria

1. [integration] One Alembic revision creates `REPORT_RUN` (ID, KIND, REPORT_DATE, GENERATED_AT, GENERATED_BY (user|first-event-after-cutover), PAYLOAD JSON, EMAILED_TO JSON, EMAILED_AT).
2. [unit] `daily_summary(uow, day) -> DailySummary{items_in, auto_applied_pct, applied_by_currency, failures_by_error_code, aging_buckets, escalations}` computed from WORK_ITEM, LINE_RESULT and history for that UTC day; `partially_paid(uow, from, to) -> list[{invoice_number, customer, original, paid, remaining, short_pay_reason, item_id}]` from `LINE_RESULT` statuses `allocation-applied-short-pay` / `allocation-applied-less-than-instruction`.
3. [api] `GET /reports/daily-summary?date=` (`reports:read`) → summary + `last_generated {at, by}`; `POST /reports/daily-summary/generate {date}`; `POST /reports/daily-summary/email {date, recipients?}` (defaults from `notifications.recipients.daily_summary`); `GET /reports/partially-paid?from=&to=`; any report `?format=csv|xlsx` returns a file (openpyxl for XLSX) with stable column headers.
4. [unit] `DailySummaryCycleHook` appended to `CYCLE_HOOKS`: on the first intake cycle after the cutover time each day, if no `REPORT_RUN` exists for yesterday, generate it and email it once (idempotent across processes via a unique (KIND, REPORT_DATE) constraint).
5. [browser] Design §8 Daily summary tab: date picker defaulting to yesterday; KPI cards (Items in, Auto-applied %, Amount applied by currency, Escalations); bar chart "Failures by error code"; "Aging items" table by bucket; buttons Generate now, Email to list…, Export CSV / XLSX; line "Last generated 07:02 by first event after 07:00 cutover."
6. [browser] Design §8 Partially paid invoices tab: `data-table` (invoice #, customer, original, paid, remaining, short-pay reason, WI link to `/exceptions?item=` or `/items/[id]`) with export buttons.
7. [browser] States: loading skeletons; empty "No activity on 22 Oct 2026."; generation error alert with Retry; Reports nav visible with `reports:read`.

## Out of scope

Scheduling of any kind; notification channels (s42).

## Deps

- s15-line-matching-apply — `LINE_RESULT` statuses and amounts. plannable.
- s42-notifications — `send_report_email(recipients, subject, body, attachments)`, `config.notifications().recipients`. plannable.
- s06-intake-poller — `CycleHook`, `CYCLE_HOOKS`. plannable.
- s19-ui-shell-flow-monitor — shell, `kpi-card`, `data-table`, `money`, `empty-state`, `error-alert`, dto fixtures. plannable (same wave, merged first).
- s31-typed-web-api-client — `api()`. plannable.
- s04-sign-in-authorization — `require_permission(REPORTS_READ)`. plannable.
- s28-runtime-config-service — `config.reports().daily_summary_cutover`. plannable.

## Assumptions

- Report days are UTC; a tenant timezone setting can come later.
