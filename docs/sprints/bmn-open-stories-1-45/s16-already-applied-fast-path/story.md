# s16-already-applied-fast-path: Already-applied fast path (attach the remittance and close the item)

- Issue: #16
- Wave: 5 (money path; owns `cashapp/stations/fast_path/`)
- breaking: false

## Story

As AR, I want remittances for invoices that are already fully paid closed in seconds, without matching, so that the ~60% of remittances that relate to already-applied receipts stop costing anyone time.

## Context

Reference doc §1: attach the remittance to the receipt even when it is already fully applied, then close the item. Runs right after customer resolution (which already looked up the transactions). Uses s17's attach + note writer so write-back code exists once.

## Acceptance criteria

1. [unit] `find_closing_receipts(transactions, fusion) -> ClosingReceipts{receipt_ids: set[int], complete: bool}`: only when EVERY found transaction on the remittance has zero remaining balance (credit memos sign-aware) and every line's transaction was found; for each, `fusion.list_transaction_applications(customer_trx_id)` gives the receipt(s) that closed it; `complete=False` if any transaction's closing receipt can't be determined.
2. [integration] `FastPathRunner` (stage FAST_PATH): not all closed → `Advance(MATCH_RECEIPT)` (normal path, no Fusion write). All closed and closing receipt(s) determined → for each receipt call `write_back(uow, item, receipt_id, mode="already_applied")` (s17: attach the original remittance + a note "Remittance received <date>; invoices already applied") and `Finish(PaymentStatus.PAYMENT_PREVIOUSLY_APPLIED)` with every line `allocation-previously-applied` in `LINE_RESULT`; STATE=DONE.
3. [unit] Closing receipt can't be determined → `Advance(MATCH_RECEIPT)` with a history note (falls through, test).
4. [unit] An attach failure doesn't reopen the item: s17's `WRITE_BACK_FAILED` handling applies (item goes to s18 with that code; no applications are touched).
5. [unit] History records the closing receipt(s) and the reason ("all N invoices already closed by receipts …").
6. [unit] `ROLE = RoleSpec("fast-path", "consumer", build)`.

## Out of scope

Applying anything.

## Deps

- s11-customer-resolution — resolution with `transactions` (balance, kind, customer_trx_id). plannable.
- s05-fusion-client — `list_transaction_applications(customer_trx_id)`. plannable.
- s17-fusion-write-back — `write_back(uow, item, receipt_id, *, mode: "applied"|"already_applied") -> WriteBackResult` from `cashapp/services/write_back.py`. plannable (same wave).
- s15-line-matching-apply — `LINE_RESULT` table and repository `LineResultRepository.upsert(...)`. plannable (same wave).
- s03-pipeline-runtime — `StageRunner`, `Finish`. plannable.

## Assumptions

- When several receipts closed the invoices, the remittance is attached to each.
