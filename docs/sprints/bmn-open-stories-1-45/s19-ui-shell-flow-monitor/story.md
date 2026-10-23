# s19-ui-shell-flow-monitor: UI shell and flow monitor (with item drill-down)

- Issue: #19
- Wave: 5 (owns `web/app/(shell)/layout.tsx`, `web/app/(shell)/flow/**`, `web/app/(shell)/items/**`, `web/app/signed-out/`, `web/components/common/*` except `llm-chat*` and `lock-banner`, `web/components/shell/`, `cashapp/api/routers/flow.py`, `cashapp/api/routers/items.py`, `cashapp/services/flow_query.py`)
- breaking: false

## Story

As an operator, I want to watch the assembly line live and drill from a stage down to a single item, its history, its original artifact with each extracted field highlighted, and its per-line Fusion outcome, so that I understand what the system is doing and why.

## Context

Design screens owned here: design.md §3 "App shell" (incl. `/signed-out` and the unauthorized state) and §4 "Flow monitor" (incl. `/flow/[stage]` and the three-pane item view `/items/[id]`). Shared components (design §9) built ONCE here: `status-badge`, `money`, `data-table`, `kpi-card`, `empty-state`, `error-alert`, `history-timeline`, `artifact-viewer`, `live-indicator` (s20 owns `lock-banner`; s22 owns `llm-chat`). All data comes through s31's typed client; Server Components by default.

## Acceptance criteria

1. [api] `GET /flow/summary` (`items:read`) → `{kpis: {in_today, auto_applied_pct, applied_by_currency: [{currency, amount}], needs_person}, stages: [{stage, in_queue, in_progress, errors, throughput_per_min: number[60], p95_dwell_s, awaiting_buckets?: {"0-2d","3-7d","8-30d",">30d"}}], pollers: [{name, last_cycle_at}], cohere_utilisation_pct|null, backlog: [{id, name, processed, total, eta_minutes, status}]}`; `GET /flow/stream` (SSE) emits, per open connection, `summary` every 5 s and `item_changed {id, stage, state, lock: LockInfo|null, payment_status}` for every item whose `UPDATED_AT` advanced since the connection's previous tick (one indexed query per tick; the stream is a view of the DB, not a poller of an external source). Lock changes bump `UPDATED_AT` (s40 writes it).
2. [api] `GET /flow/stages/{stage}/items?state=&page=` → `{items: [{id, payer_name, amount, currency, received_at, attempts, state, payment_status, lock}], total}`; `GET /items/{id}` → `{item, lock, extraction: {final, provenance, disagreements, confidence, reader_a, reader_b, missing_reader}, parts: [{part_no, kind, media_type}], lines: [{line_no, transaction_number, stated_amount, fusion_balance, applied_amount, line_status, fusion_result_code}], resolution, receipt}`; `GET /items/{id}/history` → ordered rows with actor names; `GET /items/{id}/parts/{n}` streams the stored part (content-type preserved, `Content-Disposition: inline`, never logged); `GET /search?q=` → items by WI id, receipt number or invoice number (for ⌘K).
3. [browser] Design §3 "App shell": sidebar (Flow, Exceptions with count, Reports, Config only for `config:read`), breadcrumb, ⌘K palette jumping to an item by WI id/receipt/invoice, env badge (PROD in red outline) from `NEXT_PUBLIC_ENV_LABEL`, user menu with sign-out; nav items hidden per `/me` permissions (VIEWER sees no Config); `/signed-out` page renders without the shell ("You've been signed out. Sign in again"); a route the user can't access shows "You don't have access to this page. Ask an administrator for the <role> role."
4. [browser] Design §3 live indicator at the sidebar foot: "Live" (green) when `/flow/stream` is connected, "Reconnecting…" with retry count, "Disconnected — data may be stale" with Retry (driven by `useEventStream` status; tested with `sse-mock`).
5. [browser] Design §4 "Flow monitor" `/flow`: KPI strip of 4 `kpi-card`s; stage tiles in pipeline order with in-queue, in-progress, sparkline, p95 dwell, error badge; Awaiting receipt tile shows aging buckets; Extract tile shows Cohere utilisation %; a running backlog batch shows the full-width progress bar "Backlog batch B-0007 · 2,140 / 5,000 items · ETA 41 min" with Pause (calls `POST /backlog/batches/{id}/pause`, permission `backlog:run`).
6. [browser] Design §4 drill-down: clicking a tile opens `/flow/[stage]` (`data-table` with WI id, payer, amount+ccy via `money`, received, attempts, `status-badge`, lock owner with violet lock icon); clicking a row opens `/items/[id]` three-pane view: left `artifact-viewer` (PDF via pdfjs-dist, image, email text) drawing highlight boxes from each field's `source.bbox`; hovering a field in the middle pane highlights its box; middle tabs Final (value tagged A / B / A+B with confidence bar) · Reader A · Reader B · Disagreements, plus the lines table with Fusion outcome; right rail `history-timeline` (expand an entry to a `Collapsible` with payload JSON and copy button) and the Chat tab rendering `<LlmChat context={{kind:"item", id}} systemPromptKey="item" actions=[…] variant="panel" />`; `/flow` has the "Ask" button rendering `<LlmChat … kind:"flow" variant="sheet">`.
7. [browser] Lock state visible: an item locked by a person shows the violet lock + owner name in the stage table and a lock line on the item view; an `item_changed` event for a displayed item (lock taken/released, state change) updates the row and the item header without reload.
8. [browser] States per design §4: skeleton tiles/table while loading; empty day "Nothing has arrived yet today. The intake poller last checked the mailbox N minutes ago."; API error shows `error-alert` "Couldn't load the flow. The API returned 503 (request id …). Retry" with stale data kept under a "stale" tag.
9. [unit] `status-badge` maps every `ItemState`, `PaymentStatus` and `LineStatus` value (imported from the generated OpenAPI enums, not redeclared) to one of the design status tokens; a test fails if any enum value is unmapped. `money` renders `"12480.00","USD"` as `12,480.00 USD`, right-aligned tabular-nums, never a bare `$`.
10. [browser] Responsive per design §10: at <1024 px the item view stacks; at phone width (375 px) stages render as a vertical list and tables scroll inside their card with no page-level horizontal scroll.

## Out of scope

Exceptions workbench (s20), configuration (s21), reports (s41), chat internals (s22).

## Deps

- s31-typed-web-api-client — `api()`, `useEventStream`, SSE proxy for `/flow/stream`, `api-mock.ts`, `sse-mock.ts`. plannable.
- s04-sign-in-authorization — `requireSession()`, `GET /me` permissions, `require_permission(ITEMS_READ)`, `web/tests/support/session.ts`. plannable.
- s22-ui-shared-llm-chat — `<LlmChat context systemPromptKey actions variant suggestions? />`. plannable (same wave, merged before this story).
- s15-line-matching-apply — `LineResultRepository.for_item`, `ApplicationLedgerRepository.for_item`. plannable.
- s13-receipt-matching-scorer — chosen receipt via `MATCH_CANDIDATE` (CHOSEN) / `ReservationRepository.active_for_item`. plannable.
- s35-backlog-reprocessing — `GET /backlog/batches?status=RUNNING` and `POST /backlog/batches/{id}/pause`. plannable.
- s40-item-locking — `lock_info_for(item)`, `LockInfo`. plannable.
- s36-llm-usage-cost-ledger — `cohere_utilisation()`. plannable.
- s29-observability — `collect_queue_stats(uow)`. plannable.
- s09-adjudicate-fan-in / s08-extraction-fan-out / s11-customer-resolution — `AdjudicationRepository.latest_for`, `EXTRACTION_READING`, `CustomerResolutionRepository.latest_for`. plannable.
## Test-support files owned

`web/tests/support/fixtures/dto.ts`: builders for flow summary, stage items, item detail, history rows (typed from `schema.d.ts`), reused by s20, s21, s41 tests.

## Assumptions

- `item_changed` is derived from `WORK_ITEM.UPDATED_AT` per SSE tick (5 s), so it works across API instances with no extra bus consumer; up to 5 s latency is acceptable for a monitor.
