# s15-line-matching-apply: Line matching and apply in Fusion

- Issue: #15
- Wave: 5 (money path; owns `cashapp/stations/match_lines/`, `cashapp/stations/apply/`, `cashapp/services/matching/lines.py`, `cashapp/data/repositories/applications.py`)
- breaking: false

## Story

As AR, I want each remittance line applied to its invoice or credit memo safely — never over-applied, never applied twice, never lost mid-remittance — so that cash lands where the customer said with no clean-up.

## Context

CLAUDE.md *Lines* and *Idempotency*; reference doc §4.3, §4.6–4.10 and the as-built defects (no cap, no idempotency, roll-up lied). All Fusion writes go through `FusionClient.apply_receipt` (s05), behind `fusion.write_enabled`. Applies are ~6 s per line: per-receipt concurrency cap from s30's `ReceiptApplyGate`. Locks (s40) are respected by the runner's claim and re-checked before every line.

## Acceptance criteria

1. [unit] `plan_lines(lines: Sequence[ExtractedLine], transactions: Mapping[str, FusionTransaction], receipt_remaining: Decimal, existing: Sequence[FusionApplication], payment_currency: str) -> LinePlan{steps: list[LineStep{line_no, transaction, amount, kind}], results: list[LineResultDraft{line_no, line_status, reason}]}` in `cashapp/services/matching/lines.py`, pure:
   - verdict order per line: zero amount → `allocation-zero-amount`; not found → `allocation-invoice-not-found`; no bill-to → `allocation-customer-not-found`; currency ≠ payment currency → `allocation-apply-failed` with `INVOICE_CURRENCY_MISMATCH`; status not open/complete → `INVOICE_STATUS_INVALID`; no remaining balance (sign-aware for credit memos) → `allocation-no-remaining-balance`; already applied from this receipt (existing applications) → `allocation-previously-applied`; else valid.
   - duplicate transaction lines are deduplicated (amounts summed when both stated, else one) and recorded;
   - credit memos first, then invoices, stable by (kind, line_no);
   - amount = `min(stated amount, balance, receipt remaining)` (credit memos signed negative, increasing remaining); lines without an amount use the full balance only when the header amount equals the sum of balances within tolerance, else the line is `allocation-apply-failed` with `AMOUNT_VARIANCE`;
   - short pay (amount < balance) → step status target `allocation-applied-short-pay`; capped below stated → `allocation-applied-less-than-instruction`.
2. [integration] One Alembic revision creates `LINE_RESULT` (ID, WORK_ITEM_ID, LINE_NO, TRANSACTION_NUMBER, CUSTOMER_TRX_ID, KIND, STATED_AMOUNT, BALANCE_BEFORE, APPLIED_AMOUNT, DISCOUNT_AMOUNT, RESIDUAL, LINE_STATUS, ERROR_CODE, REASON, UPDATED_AT; unique WORK_ITEM_ID+LINE_NO) and `APPLICATION_LEDGER` (ID, WORK_ITEM_ID, LINE_NO, RECEIPT_ID, CUSTOMER_TRX_ID, AMOUNT, DISCOUNT_AMOUNT, IDEMPOTENCY_KEY unique (item:receipt:trx), STATUS (PLANNED|APPLIED|FAILED|REVERSED|DRY_RUN), FUSION_APPLICATION_ID, ERROR_CODE, REQUEST JSON, RESPONSE_MESSAGES JSON, APPLIED_AT, APPLIED_BY (system), REVERSED_AT, REVERSED_BY, REVERSAL_REASON), with `LineResultRepository{upsert(item_id, line_no, **cols), for_item(item_id)}` and `ApplicationLedgerRepository{planned_for(item_id), mark(row, status, **cols), for_item(item_id)}` (public for s16, s17, s19, s20, s35, s38, s39, s41).
3. [integration] `MatchLinesRunner` (stage MATCH_LINES): fetches fresh balances (`find_transactions`) and existing applications (`list_receipt_applications(receipt_id)`), runs `plan_lines`, persists PLANNED ledger rows and draft `LINE_RESULT`s, `Advance(APPLY)`. Re-entry (after overapply/already-applied reroute) re-plans from fresh Fusion data and reconciles: a ledger row whose application now exists in Fusion becomes APPLIED (`FUSION_ALREADY_APPLIED` reconciled, then success).
4. [integration] `ApplyRunner` (stage APPLY): for each PLANNED row in order, inside `apply_gate.slot(receipt_id)`: re-check the item's lock (abort and release claim if a person took it), re-check Fusion's existing applications for that receipt+trx (idempotency: if present, mark APPLIED without calling), call `apply_receipt` with `accounting_date = max(payment_date, today, FIX_HINTS.gl_date_floor)`, and persist the ledger row + `LINE_RESULT` in its own transaction immediately after each call (a crash after line 3 keeps lines 1–3; test kills mid-loop and resumes without re-applying).
5. [unit] A fault on one line marks that line `allocation-apply-failed` with the mapped code and continues with the others (apply what's valid); FUSION_LOCKED/TRANSIENT on a line raises `StageError` after persisting earlier lines (the retry resumes at the first non-APPLIED row); FUSION_OVERAPPLY/ALREADY_APPLIED/GL_DATE raise their codes for s18's reroutes.
6. [unit] After all lines: `PAYMENT_STATUS = roll_up(header, line statuses)` (strictly derived; test: nothing applied + receipt missing never reports success), `RECEIPT_RESERVATION` consumed (`ReservationRepository.consume`), history row with per-line outcome summary, `Advance(WRITE_BACK)`.
7. [unit] `fusion.write_enabled=false` → apply raises `FUSION_WRITE_DISABLED` before any call and the item escalates (no silent success).
8. [unit] `ROLES = [RoleSpec("match-lines", "consumer", …), RoleSpec("apply", "consumer", …)]`.

## Out of scope

Discounts (s39 adds them on the same call); write-back (s17); dry-run (s35); reversal (s38).

## Deps

- s13-receipt-matching-scorer — `Advance(MATCH_LINES, payload={receipt_id})`, `ReservationRepository.active_for_item/consume`. plannable.
- s11-customer-resolution — `CustomerResolutionRepository.latest_for` (anchor, related, transactions). plannable.
- s05-fusion-client — `find_transactions`, `list_receipt_applications`, `apply_receipt(ApplyRequest)`, `accounting_date_for`, `FakeFusionClient`. plannable.
- s30-worker-host — `ReceiptApplyGate.slot(receipt_id)` (resolved via `container.resolve(ReceiptApplyGate)`). plannable.
- s40-item-locking — `is_locked_for_automation`. plannable.
- s02-data-layer-foundation — `LineStatus`, `PaymentStatus`, `roll_up`, `money_eq`, `to_money`. plannable.
- s09-adjudicate-fan-in — `AdjudicationRepository.latest_for` (lines). plannable.
- s18-auto-fix-engine — `FIX_HINTS.gl_date_floor`; reroute contracts for OVERAPPLY/ALREADY_APPLIED. plannable.

## Assumptions

- Lines with no stated amount are applied in full only when the header reconciles; otherwise a person decides.
