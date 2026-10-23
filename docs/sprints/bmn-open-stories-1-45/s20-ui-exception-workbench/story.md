# s20-ui-exception-workbench: UI exception workbench (dequeue, fix, requeue)

- Issue: #20
- Wave: 5 (owns `web/app/(shell)/exceptions/**`, `web/components/exceptions/`, `web/components/common/lock-banner.tsx`, `cashapp/api/routers/exceptions.py`, `cashapp/services/exceptions_query.py`, `cashapp/services/fusion_context.py`)
- breaking: false

## Story

As an AR specialist, I want to find, understand and fix a stuck item quickly, with automation kept away while I work, so that exceptions are cleared in minutes and I can see what Fusion's own screens hide.

## Context

Design screen owned here: design.md §5 "Exception workbench" (`/exceptions` with the right-side detail sheet, deep link `/exceptions?item=WI-…`). Uses shared components from s19 (`data-table`, `status-badge`, `money`, `empty-state`, `error-alert`, `history-timeline`) and owns `lock-banner`. Every action goes through existing API endpoints: lock (s40), requeue (s18), reverse (s38), classification override (s07).

## Acceptance criteria

1. [api] `GET /exceptions` (`items:read`) query `{q (payer|invoice|reference), amount_min, amount_max, date_from, date_to, error_codes[], stage, locked_by_me, include_auto_applied=false, include_archived=false, page, sort}` → `{items: [{id, payer_name, amount, currency, payment_date, error_code, autofix_tried, autofix_limit, age_s, stage, state, lock}], total}`; by default only ESCALATED, AWAITING_RECEIPT past 1 day, and items with failed lines; amount search uses `money_eq`-tolerant ranges.
2. [api] `GET /items/{id}/fusion-context` (`items:read`) → `{customer: {account_number, name, bill_to_site, location, relationships: [..]}, invoices: [{number, bill_to_customer, original_amount, remaining, currency, status}], credit_memo_history: [{number, original, remaining, applications: [...]}], candidate_receipts: [{receipt_number, receipt_id, receipt_date, amount, remaining, customer, score, qualifies}], autofix_attempts: [{at, code, decision, reasoning}]}` built from s11/s13 records and fresh `FusionClient` reads (cached 60 s per item).
3. [browser] Design §5 list: filter bar (search, amount range, date range popover+calendar, error-code multi-select, stage select, "Locked by me" toggle, "Show auto-applied" switch off by default) drives the URL query; columns WI id · Payer · Amount · Payment date · Error code badge · Auto-fixes tried "2 / 3" · Age · Lock · `⋯`; auto-applied items hidden by default and visible when the switch is on.
4. [browser] Design §5 detail sheet (60% width, opens on row click and on `/exceptions?item=…`): header with WI id, status badge and **Dequeue**; "Why it's stuck" shows the Haiku `ESCALATION_SUMMARY`, error code and last error; "Auto-fixes tried" ordered list with outcome icons and reasoning; Fusion context cards (customer with bill-to location and relationships, candidate receipts, invoices with original/remaining/currency/status, credit memo history).
5. [browser] Dequeue → `POST /items/{id}/lock`; the violet `lock-banner` reads "Locked by you since 10:42. Automation won't touch this item until you requeue or release it." with **Requeue** and **Release lock**; the sheet renews the lease every `lease/3` minutes while open; locked by someone else → "Locked by Priya N. since 09:15" and no edit controls; 409 `lock_conflict` → toast "Priya N. dequeued this item a moment ago."; 409 `item_busy` → toast "The line is processing this item; try again in a moment."
6. [browser] Edit and requeue: the extracted data renders as a react-hook-form + Zod form (header fields + editable lines grid); a pick-a-receipt radio when the error is RECEIPT_AMBIGUOUS; a customer picker when CUSTOMER_*; before requeue a diff summary "You changed 2 fields: line 3 invoice 'INV1044' → 'INV-1044'; receipt → R-88213." then `POST /items/{id}/requeue`; on success the item leaves the list and the lock is released; a requeue error shows an alert and keeps the form values.
7. [browser] Reverse (#38): visible only with `apply:reverse`; per applied ledger line an action opens an `AlertDialog` requiring a reason and typing the receipt number before `POST /items/{id}/applications/{ledger_id}/reverse`; mismatched number keeps the confirm button disabled.
8. [browser] Transitions made by others while the sheet is open (via `item_changed` on `/flow/stream`): (a) my lock expired → banner switches to "Your lock expired — automation may act. Dequeue again" and edit controls disable; (b) another person force-took the lock → "Priya N. took over this item" and controls disable; (c) the item was requeued/released by someone else or advanced by automation → sheet shows the new stage/state badge and a "This item moved on" notice; (d) the item was escalated again or parked AWAITING_RECEIPT → badge and reason update; (e) after my reversal the item shows ESCALATED at Match receipt with the reversal summary and stays locked by me.
9. [browser] Classification: archived non-remittances are reachable with `include_archived`; "This is a remittance" calls `POST /items/{id}/classification/override` (permission `classification:override`).
10. [browser] States per design §5: loading skeleton; empty "No exceptions. Everything that arrived has been applied or is still moving." with a link to the flow; filtered-empty "No exceptions match these filters. Clear filters"; at <1024 px the sheet is full-screen.

## Out of scope

Flow monitor and item view (s19); reversal and requeue logic (s38, s18).

## Deps

- s19-ui-shell-flow-monitor — shell layout, `data-table`, `status-badge`, `money`, `empty-state`, `error-alert`, `history-timeline` props; `/flow/stream` `item_changed` event; `GET /items/{id}`; `web/tests/support/fixtures/dto.ts`. plannable (same wave, merged first).
- s40-item-locking — lock endpoints and error codes `lock_conflict`, `item_busy`, `lock_not_held`; `LockInfo`. plannable.
- s18-auto-fix-engine — `POST /items/{id}/requeue` contract; `ESCALATION_SUMMARY`; AUTOFIX_ATTEMPT history rows. plannable.
- s38-reverse-automated-application — `POST /items/{id}/applications/{ledger_id}/reverse` contract and error codes. plannable (same wave, merged first).
- s07-classify-station — `POST /items/{id}/classification/override`. plannable.
- s11-customer-resolution / s13-receipt-matching-scorer / s15-line-matching-apply — resolution, `MATCH_CANDIDATE`, ledger rows for fusion-context. plannable.
- s05-fusion-client — `find_transactions`, `get_customer_account`, `list_transaction_applications`. plannable.
- s31-typed-web-api-client — `api()`, `apiAction`, `useEventStream`. plannable.
- s04-sign-in-authorization — permissions from `/me`; session fixture. plannable.

## Assumptions

- Lease renewal cadence = one third of `locks.lease_minutes`.
