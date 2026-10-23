# UI design — bmn-open-stories-1-45

> **Claude Design unavailable.** No Claude Design tools were exposed in this environment (ToolSearch `+claude_design` returned nothing), so no project, directions or previews were produced. This document is the fallback: one direction built from shadcn/ui + Tailwind v4 conventions. Assumption recorded: a neutral, dense, data-table-oriented operations UI. Revisit with Claude Design when it is available.

Covers stories #19 (shell + flow monitor), #20 (exception workbench), #21 (configuration), #22 (shared LLM chat), #41 (reports / daily summary).

## 1. Principles

- **Ops console, not marketing.** Dense tables, small type, high information per pixel, no hero sections.
- **Status is the primary visual signal.** One status enum (CLAUDE.md non-negotiable 7) maps to one badge variant map, defined once in `web/components/common/status-badge.tsx`.
- **Money is always right-aligned, tabular-nums, with its currency code** (`12,480.00 USD`). Never a bare `$`.
- **Every automated decision is one click from its reason** (history drawer).
- **The UI hides; the API enforces.** Controls a role can't use are hidden, not disabled-with-tooltip, except on Configuration where read-only admins see values greyed with "Admin role required to edit".
- **Light and dark** both supported via shadcn CSS variables; default follows system.

## 2. Tokens (Tailwind v4 `@theme`, shadcn neutral base)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--background` | neutral-50 | neutral-950 | page |
| `--card` | white | neutral-900 | panels, tables |
| `--muted-foreground` | neutral-500 | neutral-400 | secondary text, column headers |
| `--border` | neutral-200 | neutral-800 | all dividers |
| `--primary` | slate-900 | slate-50 | primary buttons |
| `--status-success` | emerald-600 | emerald-400 | APPLIED, DONE |
| `--status-progress` | sky-600 | sky-400 | in-flight stages |
| `--status-waiting` | amber-600 | amber-400 | AWAITING_RECEIPT, aging |
| `--status-attention` | orange-600 | orange-400 | auto-fix in progress, partial |
| `--status-error` | red-600 | red-400 | escalated, failed |
| `--status-locked` | violet-600 | violet-400 | dequeued/locked by a person |

- **Type:** Geist Sans 13px base for tables, 14px for body; Geist Mono for IDs, invoice numbers, amounts (`font-variant-numeric: tabular-nums`).
- **Spacing:** 4px grid; table row height 36px (compact) / 44px (comfortable, user toggle persisted in localStorage).
- **Radius:** `--radius: 0.375rem`.
- **Status badges:** outline variant, coloured dot + label, uppercase snake-case label converted to Title Case ("Awaiting receipt").

## 3. App shell (#19)

```
┌────────────┬───────────────────────────────────────────────────────────┐
│ ◆ CashApp  │ Breadcrumb: Flow / Match receipt / WI-20481   [⌘K] [env: DEV] [avatar ▾] │
│            ├───────────────────────────────────────────────────────────┤
│ Flow       │                                                           │
│ Exceptions │                    page content                           │
│   (37)     │                                                           │
│ Reports    │                                                           │
│ Config*    │                                                           │
│            │                                                           │
│ ── live ●  │                                                           │
└────────────┴───────────────────────────────────────────────────────────┘
```

- shadcn `Sidebar` (collapsible to icons), `Breadcrumb`, `Command` palette (⌘K: jump to item by WI id, receipt number, invoice number).
- Nav items filtered by the `Principal`'s roles from `/me`. `Config` shown only for `admin` (read-only role sees it if granted `config:read`).
- Environment badge (DEV / TEST / PROD) in header, PROD in red outline.
- Live indicator at sidebar foot: green dot "Live" when SSE connected, amber "Reconnecting…" with retry count, red "Disconnected — data may be stale" with a Retry button.
- Sign-in: server-side OIDC redirect; the only page without the shell is `/signed-out` ("You've been signed out. Sign in again").
- Unauthorized route: full-panel empty state "You don't have access to this page. Ask an administrator for the <role> role."

## 4. Flow monitor (#19) — `/flow`

**Top:** KPI strip (4 `Card`s): *In today* 412 · *Auto-applied* 78.4% · *Applied* 1,284,930.17 USD · *Needs a person* 37. Plus, when a backlog batch (#35) is running, a full-width `Progress` bar: "Backlog batch B-0007 · 2,140 / 5,000 items · ETA 41 min · Pause".

**Main:** the assembly line as a horizontal row of stage columns (scrolls horizontally on narrow screens):

`Intake → Classify → Extract (A ∥ B) → Adjudicate → Validate → Resolve customer → Match receipt ⇄ Awaiting receipt → Match lines → Apply → Write-back → Done`

Each stage tile: name, in-queue count (large), in-progress count, throughput sparkline (last 60 min, items/min), p95 dwell time, error count badge. Awaiting receipt tile shows aging buckets (0–2d / 3–7d / 8–30d / >30d). Extract tile shows Cohere cluster utilisation % (CLAUDE.md requirement).

**Drill-down** (URL-driven, each level a route so it's linkable):
1. Click stage → `/flow/[stage]`: `DataTable` of items — WI id, payer, amount+ccy, received, attempts, status, lock owner (violet lock icon + name).
2. Click item → `/items/[id]`: three-pane item view
   - **Left (40%)**: artifact viewer (PDF/image/email). Extracted fields drawn as highlight boxes at their source region; hovering a field in the middle pane highlights its box.
   - **Middle**: Extraction tabs — *Final* (adjudicated, each value tagged A / B / A+B, confidence bar), *Reader A*, *Reader B*, *Disagreements*. Lines table below: invoice #, stated amount, Fusion balance, applied, line status, Fusion outcome (SOAP result code if any).
   - **Right (rail)**: History timeline (stage transitions, auto-fix attempts with reasoning, human actions with who/when), and the shared chat (§7) collapsed as a tab.
3. Click a history entry → expands inline with payload JSON in a `Collapsible` (mono, copy button).

**States**
- Loading: skeleton tiles with shimmer; table skeleton 10 rows.
- Empty (no items today): "Nothing has arrived yet today. The intake poller last checked the mailbox 2 minutes ago." with poller last-run times.
- Error: inline `Alert` destructive "Couldn't load the flow. The API returned 503 (request id 7f3a…). Retry". Stale data stays visible beneath with a "stale" tag.

## 5. Exception workbench (#20) — `/exceptions`

**Layout:** filter bar + `DataTable` + right-side detail `Sheet` (60% width) that opens on row click; deep-linkable `/exceptions?item=WI-20481`.

**Filter bar:** search box (matches payer, invoice, reference), amount range (min/max), date range `Popover`+`Calendar`, error code multi-select, stage select, "Locked by me" toggle, "Show auto-applied" switch (off by default).

**Columns:** WI id · Payer · Amount · Payment date · Error code (badge) · Auto-fixes tried (e.g. "3 / 5") · Age · Lock · actions `⋯`.

Sample rows:
| WI | Payer | Amount | Error | Tried | Age |
|---|---|---|---|---|---|
| WI-20481 | Northwind Components | 48,210.55 USD | RECEIPT_AMBIGUOUS | 2/3 | 1d |
| WI-20477 | Contoso Retail Pvt | 1,92,400.00 INR | AMOUNT_VARIANCE | 1/1 | 3h |
| WI-20462 | Fabrikam Industrial | 9,875.00 USD | INVOICE_NOT_FOUND | 4/4 | 2d |

**Detail sheet**
- Header: WI id, status badge, **Dequeue** primary button. Once dequeued: violet banner "Locked by you since 10:42. Automation won't touch this item until you requeue or release it." Buttons: **Requeue**, **Release lock**. If locked by someone else: "Locked by Priya N. since 09:15" and no edit controls.
- **Why it's stuck:** plain-language summary (Haiku-written) + error code + the last error message.
- **Auto-fixes tried:** ordered list with outcome icons and reasoning.
- **Fusion context** (the stuff Fusion hides): customer card (account #, name, bill-to site/location, pay-on-behalf relationships), candidate receipts table (receipt #, date, amount, remaining, customer), invoices table (invoice #, bill-to customer, original amount, remaining, currency, status), credit memo history.
- **Edit:** the extracted data as a form (react-hook-form + Zod) — header fields and an editable lines grid. Pick-a-receipt radio when ambiguous. Diff summary before requeue: "You changed 2 fields: line 3 invoice 'INV1044' → 'INV-1044'; receipt → R-88213."
- **Reverse application** (#38): visible only with `apply:reverse` permission; `AlertDialog` confirmation requires typing the receipt number.

**States:** loading skeleton; empty "No exceptions. Everything that arrived has been applied or is still moving." (with link to flow); filtered-empty "No exceptions match these filters. Clear filters"; lock conflict toast "Priya N. dequeued this item a moment ago."; requeue error alert keeps the form values.

## 6. Configuration (#21) — `/config`

- Left vertical `Tabs`: Access (group → role) · Polling · Matching (date window, tolerances per currency, bank-fee bands) · Retries & aging · Models · Retention · Payer aliases.
- Each setting row: label, description, current value input, unit, "Changed by J. Stevenson 3 days ago" link that opens a history `Sheet` (who, when, old → new, reason).
- Edits stage locally; sticky footer "3 unsaved changes · Discard · Review & save". Save opens a review dialog listing old → new and a required "Reason" field (goes into history).
- Tolerances: table of currency rows (USD ±0.10, EUR ±0.10, INR ±0.49) with Add currency.
- Models: role rows (Reader A, Reader B, Adjudicator, Workhorse) with model ID select, effort select, timeout; a fixed note "Claude Fable models are not allowed (zero data retention)."
- Payer aliases: table (alias text, maps to customer, learned from WI, uses, last used) with Retire action and confirmation.
- Non-admin: values read-only, footer replaced by "Admin role required to edit".
- States: loading skeleton per tab; save validation errors inline per field; save conflict "This setting was changed by someone else since you opened it. Reload".

## 7. Shared LLM chat (#22) — `web/components/common/llm-chat.tsx`

One component, props: `context` (`{ kind: "item" | "flow" | ..., id? }`), `systemPromptKey`, `actions` (array of `{ id, label, confirm? }`), `variant` (`"panel" | "sheet"`).

- Message list (user right-aligned muted bubble, assistant left plain text with markdown rendered through a sanitizer), streaming caret while SSE tokens arrive, Stop button during stream.
- Suggested prompts row when empty: on item: "Why is this stuck?", "Which receipt fits best?"; on flow: "What's driving failures today?".
- Action chips the assistant may propose render as buttons; clicking runs the API action after a confirm dialog (never auto-executes).
- Footer note: "Answers by Claude Haiku 5.5. Check before acting."
- States: empty (suggestions), streaming, error ("The assistant didn't answer (timeout). Try again"), disconnected.
- Placement: item view right rail tab; flow monitor as a bottom-right `Sheet` toggled by an "Ask" button.

## 8. Reports (#41) — `/reports`

- Tabs: **Daily summary** · **Partially paid invoices** · (future reports).
- Daily summary: date picker (defaults to yesterday), KPI cards (Items in, Auto-applied %, Amount applied by currency, Escalations), bar chart "Failures by error code", table "Aging items" by bucket. Buttons: **Generate now**, **Email to list…**, Export CSV / XLSX. Line "Last generated 07:02 by first event after 07:00 cutover."
- Partially paid invoices: DataTable (invoice #, customer, original, paid, remaining, short-pay reason, WI link), export buttons.
- States: loading skeletons; empty "No activity on 22 Oct 2026."; generation error alert with retry.

## 9. Shared components (one each)

`status-badge`, `money` (formats Decimal string + ccy), `data-table` (TanStack Table wrapper: sort, filter, paging, column visibility, density), `kpi-card`, `empty-state`, `error-alert` (renders the API's single error shape incl. request id), `history-timeline`, `lock-banner`, `llm-chat`, `artifact-viewer`, `live-indicator`. shadcn primitives from the CLI: sidebar, breadcrumb, command, card, table, badge, button, input, select, tabs, sheet, dialog, alert-dialog, alert, popover, calendar, progress, skeleton, tooltip, sonner, form, switch, collapsible, chart.

## 10. Responsive

Desktop-first (≥1280px is the working target). At <1024px the item view stacks (artifact → extraction → history) and the detail sheet becomes full-screen. At phone width, the flow monitor shows stages as a vertical list; tables scroll horizontally inside their card, never the page.
