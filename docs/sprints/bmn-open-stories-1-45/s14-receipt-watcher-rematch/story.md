# s14-receipt-watcher-rematch: Fusion receipt watcher and re-matching of items awaiting a receipt

- Issue: #14
- Wave: 3 (owns `cashapp/pollers/receipt_watcher/`, `cashapp/stations/receipt_arrived/`, `cashapp/data/repositories/awaiting.py`, `cashapp/data/repositories/watermark.py`)
- breaking: false

## Story

As AR, I want remittances that arrive before their bank receipt to wait and be re-matched the moment the receipt appears, so that the ~70% "receipt not found" failures fix themselves without a fixed hold.

## Context

Poller 2 of exactly 2 (CLAUDE.md non-negotiable 5). Filters on receipt creation time (receipts are often created a day after their receipt date). Restarts neither miss nor replay receipts: high-water mark in the DB. Items enter AWAITING_RECEIPT via s18's handler for `RECEIPT_NOT_YET_AVAILABLE` (raised by s13), which sets `AWAITING_SINCE`.

## Acceptance criteria

1. [integration] One Alembic revision creates `RECEIPT_WATERMARK` (POD pk, HIGH_WATER_MARK timestamp, SEEN_AT_MARK JSON (receipt ids sharing the mark), UPDATED_AT).
2. [integration] `ReceiptWatcher.run(stop)` loops on `config.receipt_watcher().poll_interval_seconds` (re-read each cycle): `fusion.receipts_created_since(mark - overlap)` (overlap 5 min), drops receipts already in `SEEN_AT_MARK` or older than the mark, and in ONE transaction per batch writes an outbox `ReceiptArrived` event per new receipt and advances the mark (+ ties). A crash between fetch and commit replays nothing that was committed and misses nothing (tests: restart mid-batch; two receipts with identical creation time across cycles).
3. [unit] `ReceiptArrived` event (topic `{prefix}.{env}.receipt-arrived`, schema_version 1): `{event_id, receipt_id, receipt_number, customer_account_number, currency, amount, unapplied_amount, receipt_date, creation_date}` (money as strings).
4. [integration] `ReceiptArrivedConsumer` (`cashapp/stations/receipt_arrived/`) finds AWAITING_RECEIPT items it could match via `AwaitingReceiptRepository.candidates_for(receipt, window_days, tolerance) -> list[WorkItem]`: currency equal (or item currency null), `CUSTOMER_ACCOUNT_NUMBER` equal to the receipt's customer or in the item's related customers (from `CUSTOMER_RESOLUTION`), `|PAYMENT_AMOUNT − unapplied_amount| ≤ tolerance` OR `PAYMENT_AMOUNT ≤ unapplied_amount` (split payments), and `PAYMENT_DATE` within `matching.date_window_days` of either receipt_date or creation_date; skips items with a live lock; for each: STATE AWAITING_RECEIPT → PENDING at STAGE=MATCH_RECEIPT, history row "woken by receipt <number>", `StageEvent(MATCH_RECEIPT)` — all in one transaction; redelivery is a no-op.
5. [integration] Aging: each watcher cycle escalates AWAITING_RECEIPT items with `AWAITING_SINCE` older than `config.aging().awaiting_receipt_max_days` via s18's `escalate(uow, item, ErrorCode.AGED_OUT, summary)` (STATE=ESCALATED, history, notify event).
6. [unit] `ROLE = RoleSpec("receipt-watcher", "poller", build)` and `ROLE = RoleSpec("receipt-arrived", "consumer", build)`; s30's poller-count guard sees exactly two pollers.

## Out of scope

Scoring/choosing the receipt (s13); entering AWAITING_RECEIPT (s18).

## Deps

- s05-fusion-client — `receipts_created_since(since, limit)`, `FusionReceipt`, `FakeFusionClient`. plannable.
- s18-auto-fix-engine — `escalate(uow, item, code: ErrorCode, summary: str|None, principal=SYSTEM_PRINCIPAL) -> None` from `cashapp/services/autofix/escalation.py`. plannable (same wave).
- s11-customer-resolution — `CUSTOMER_RESOLUTION.RELATED_CUSTOMER_NUMBERS`. plannable (same wave).
- s03-pipeline-runtime — `emit`, `StageEvent`, `EventBus.subscribe`. plannable.
- s28-runtime-config-service — `receipt_watcher()`, `matching()`, `aging()`. plannable.
- s40-item-locking — `is_locked_for_automation`. plannable.

## Assumptions

- Aging escalation happens on the watcher's cycle (an event), not via a scheduler.
