# Prior implementation: lessons for Fusion-CashApp-AI

This file distils a previous cash-application automation we built for a client on Oracle Fusion Receivables (Phase 2, 2026). That system used OIC, a separate AI extraction service and Kafka. **This system uses none of the OIC machinery.** What carries over:

- the Fusion calls
- the matching rules
- the status vocabulary
- the failure data
- the mistakes

Treat every rule here as a **starting point to confirm against the target tenant and business**, not as a specification. Client, customer and staff names are omitted on purpose.

---

## 1. What the business actually needs

**Volume and backlog**
- About 2,000–3,000 receipts a day, with month-end peaks.
- Up to about 2,500 remittance emails on a peak day.
- A backlog of tens of thousands of unworked remittances.
- About 60% of payments auto-applied before the project. About 60% of remittances related to receipts that had *already* applied, so working them by hand was wasted effort.

**How people work today**
- The work surface is mail folders: the eGain queue, a shared Gemstone folder and personal Outlook.
- There's no status, poor search (you can't search by amount) and no archive.
- Staff work in both directions: from a receipt looking for its remittance, and from a remittance looking for its receipt.

**What they asked for**
- **Apply as much as possible.** Apply what's valid, and report the rest line by line. Never throw away the whole document because one line fails.
- **An exception-only worklist.** Don't show the items that auto-applied; show only what needs work.
- **A continuous matching loop instead of a fixed 3-business-day hold.** The old upstream service held every remittance 3 business days so the bank receipt could post first. The business wants each held remittance re-checked until its receipt appears, with an aging limit (for example 30 days), then escalated.
- **Tell the story in Fusion.** Leave a note on the receipt saying what was applied and why lines failed. The receipt note field is small, so this needs design.
- **Attach the remittance email to the receipt,** including when the receipt is already fully applied: attach, then close the item.
- **Reprocess the backlog** through the same pipeline.
- **Synthetic test data on demand:** one receipt plus N invoices and credit memos, for each scenario.

**What must stay with a person**
- Prepayments ("prepaids shouldn't auto apply").
- PO, sales-order and ERS references.
- Bank fees and tariffs, for now.
- Discounts Fusion rejects.
- Payers who map to multiple accounts. Never auto-assign these.
- Anything not grounded in the remittance itself ("never invent a discount").

**Controls they insisted on**
- Completeness checks: counts and totals reconciled.
- Maker/checker separation on reconciliation.
- A readable audit trail.

## 2. Extraction contract (what the AI produced)

The upstream service emitted one payment per message:

```
payerName
payments[]:
  reference_number, payment_amount, payment_date (YYYY-MM-DD), payment_currency
  allocations[]:
    application_type   "Payment" | "Credit Memo"
    invoice_number
    applied_amount
    credit_memo_id     credit memos only
paymentSummary, status, statusDescription
```

Problems we hit, which the new extraction schema must handle:

- **`invoice_number` must be a string.** It arrived as a JSON number and became `2.598014E6`. Real references carry suffixes: credit memos are `<invoice>-1`, `-2`.
- **Many remittances have no per-line amounts.** Example: 21 invoice references and only a total. Some have no payment amount or date at all.
- **Several dates in one remittance** (order date, issue date, expected deposit date). Which one is the payment date must be decided, and the others kept.
- **Ambiguous currency.** A `$` can mean USD, CAD or AUD. Resolve it from the customer's account currency rather than guessing.
- **Header total ≠ sum of lines** is common and legitimate. It's a flag, not a failure.
- **Fields with no slot in the old schema:** PO, sales-order and ERS references; bank fees; tariffs (sometimes a separate line with the same invoice number); discount claimed.
- **No customer account field.** The customer was always derived from an invoice.
- **The same remittance is often submitted twice.** Dedupe at intake.

## 3. Fusion calls that worked

**REST basics**
- Base path: `/fscmRestApi/resources/11.13.18.05`.
- **Send `REST-Framework-Version: 4`.** Without it, `in (...)`, `AND` and `BETWEEN` in `q=` return HTTP 400.
- Use `onlyData=true`, and send `fields=` everywhere.

**Calls**

| Purpose | Call | Notes |
|---|---|---|
| Invoice lookup | `GET /receivablesInvoices?q=TransactionNumber in ('a','b')` | One batched call. Fields: `CustomerTransactionId, TransactionNumber, InvoiceBalanceAmount, BillToCustomerNumber, BusinessUnit, InvoiceCurrencyCode, InvoiceStatus`. |
| Credit memo lookup | `GET /receivablesCreditMemos` with the same `q` | Remittances don't say which is which, so query both. `TransactionBalanceDue` is **negative** while credit remains. |
| Receipt lookup | `GET /standardReceipts?q=CustomerAccountNumber in (...) AND ReceiptDate BETWEEN 'd1' AND 'd2'&expand=remittanceReferences` | **This tenant could not filter on `UnappliedAmount` or `Currency`, and `Status='UNAPP'` returned a 500,** so filter amount and currency in memory. Fields: `ReceiptNumber, StandardReceiptId, Amount, UnappliedAmount, Currency, CustomerAccountNumber, ReceiptDate, Status, State`. |
| Pay-on-behalf relationships | BI Publisher SOAP `runReport` on `/xmlpserver/services/ExternalReportWSSService` | Uses a custom report filtered on `status='A'`, `bill_to_flag='Y'` and date-effective. It returns each related account twice (INBOUND and OUTBOUND), so dedupe. Ask for XML: HTML fails because it's a data-model-only report. **This report must be built in each new tenant.** |
| **Apply** | SOAP `createApplyReceipt` on `/fscmService/StandardReceiptService` | There is no REST apply. Key on IDs: `ReceiptId` (StandardReceiptId) and `CustomerTrxId` (CustomerTransactionId), because transaction and receipt numbers are not unique. Fields: `AmountApplied` (signed, negative for credit memos), `ReceiptCurrency`, `ApplicationDate`/`AccountingDate` = the later of payment date and today. |
| Fallback, not used | `POST /standardReceipts/{id}/child/remittanceReferences` plus the AutoMatch job | Asynchronous with no confirmation. Rejected in favour of the immediate SOAP apply. |
| Test data | `POST /receivablesInvoices`, then `POST /receivablesInvoices/{id}/action/completeTransaction`, then `POST /standardReceipts` | Create the receipt without an application child so it stays unapplied. |

**SOAP response handling: fail closed**
- Count it as success only if a `Value` block exists and there is no fault.
- Faults also arrive **inside an HTTP 200 envelope** as ADF `ServiceErrorMessage`. Treating those as success caused silent under-application.
- Ignore these noise codes: `AR_RAPI_TRX_NUM_IGN`, `AR_RAPI_RCPT_NUM_IGN`, `GENERIC_MESSAGE`, `FND_AS_UNEXPECTED_ERROR`, and the "…ID takes precedence" warnings (AR-855741, AR-855799). The meaningful fault is usually in the middle of 8–9 messages.
- `ReceiptId` comes back nil in the apply response, so keep the ID you matched on.

**Paging and query safety:** the old code ignored `hasMore` and didn't escape quotes in `q=` values. Both are bugs: paginate, and escape.

**Faults seen in production, and what they mean**

| Fault | Meaning / fix |
|---|---|
| `AR-855287` (overapply) | The applied amount exceeded the invoice balance. Clamp it. |
| `AR-856102` (paid the same invoice twice) | Duplicate line or re-run. Check existing applications first (idempotency). |
| `AR-857607` (duplicate receipts) | Apply by ID, not by number. |
| `AR-856089` (GL date before receipt GL date) | Date rule. Accounting date must be ≥ the receipt's GL date. |
| `ORA-00054` (lock), `AR-856792` (record changed) | Concurrency. Retry with backoff, and serialize per receipt. |
| REST 401 and 404 `NotAuthorizedOrNotFound`, SFTP write failures | Infrastructure or transient. Retry. |

## 4. Matching rules as built

These are the rules the last production version used. Port the intent, not the bugs.

1. **Money** is 2-decimal with half-up rounding, so use `Decimal` (Python's `round` uses banker's rounding). Exact equality means `|a − b| ≤ 0.005`.
2. **Anchor customer**: the `BillToCustomerNumber` of the first allocation whose invoice was found. No anchor means customer-not-found, and nothing is applied.
3. **Verdict for each line**, checked in this order:
   1. invoice not found
   2. no bill-to customer
   3. no remaining balance (credit memos: sign-aware)
   4. customer differs from the anchor (relationship check)
   5. valid

   Gap to fix: currency and `InvoiceStatus` were fetched but **never checked**.
4. **Pay-on-behalf relationships only widen the receipt search.** They follow one hop, in both directions, and are never a failure status. An earlier relationship-not-found status mislabeled timing failures and was removed.
5. **Receipt match: one receipt per payment.** All of these must hold:
   - same currency
   - `UnappliedAmount` ≈ the payment header amount
   - receipt date within **payment date ±5 days**. The documents also say ±2 and ±4; make the window one configuration value shared by the fetch and the matcher.
   - receipt owned by the anchor customer
   
   The fallback passes run in this order:
   1. exact match, anchor customer
   2. exact match, related customers
   3. INR whole-rupee floor/ceiling match, anchor customer
   4. the same, related customers
   
   The first match wins.
6. **Lines with a zero amount** (`abs ≤ 0.005`) are rejected before matching. Twenty $0.00 applications reached production before this guard existed.
7. **A missing payment date stops the match.** A match that ignored the date was tried and removed.
8. **Credit memos are applied first,** in a stable order, so invoice balances reflect them.
9. **Apply the customer's stated amount per line.** If it's less than the balance, the invoice stays open (short pay). The leftover receipt amount stays unapplied.
10. **The payment grade** compares the applied total with the total due: success, less-than-due success, or more-than-due success. Flag `payment-header-line-mismatch` when the header differs from the sum of lines.

**Agreed but not built**
- Rounding tolerance: **±0.10 in every currency, ±0.49 for INR.** It only widens the receipt match. Apply the receipt's real amount and record the residual.
- **Discounts:** take a discount only when the customer references it, it was earned under the payment terms, and the receipt ≈ balance − discount within tolerance. Send `DiscountTaken` on the same apply call. The payment-terms resource and the discount element were never confirmed on a tenant.
- Bank-fee band (deferred).
- Write-off under $1 (left to the "standard process").

**Defects in the as-built logic. The new system must fix these.**
- No cap at `min(line amount, invoice balance, receipt remaining)`, so overapply faults.
- No reservation of a matched receipt. Two payments or two concurrent messages could take the same receipt; a test applied to the "wrong" receipt because of this.
- No ambiguity check: the first of several qualifying receipts won. The rule was "oldest wins", and a note said "closest date".
- No idempotency before applying, and a re-sent message was re-applied.
- A partly applied receipt never matched again, because its unapplied amount no longer equalled the header. So retries couldn't resume.
- The overall status once reported success when the receipt or customer wasn't found. **Derive the roll-up strictly from header and line results.**
- No unapply or adjustment flows exist anywhere. Design them from scratch.

## 5. Status vocabulary

Make this **one shared enum** used by the matcher, the API, the UI and reporting. Reporting drifted from the matcher last time.

**Payment level**
- Success family: `payment-success`, `payment-less-than-total-due-success`, `payment-more-than-total-due-success`.
- When nothing applied, use the first that applies, in this precedence: `invoice-not-found` > `customer-not-found` > `missing-payment-date` > `receipt-not-found` > `zero-amount` > `payment-apply-failed`.
- Info flag: `payment-header-line-mismatch`.

**Line level**

| Status | Meaning |
|---|---|
| `allocation-applied` | Applied (full or short pay) |
| `allocation-invoice-not-found` | No invoice or credit memo with that number |
| `allocation-customer-not-found` | No anchor customer could be derived |
| `allocation-no-remaining-balance` | Invoice already fully paid |
| `allocation-zero-amount` | Line amount is zero |
| `allocation-missing-payment-date` | No payment date to match on |
| `allocation-no-receipt-match` | No qualifying receipt |
| `allocation-apply-failed` | Apply call faulted; detail in `exceptions[]` |

**Designed but not built:** `allocation-applied-short-pay`, `allocation-applied-less-than-instruction`, `allocation-applied-with-discount`, `allocation-previously-applied`, `multiple-accounts-same-receipt-fail`. Also, `payment-apply-failed` needs splitting into system fault, receipt closed, and all lines at zero balance.

**Exception shape:** `{type, errorCode, reason, severity, title, detail, errorDetails[]}`, with every key always present.

## 6. Failure data: inputs for the auto-fix engine

**One production day:** 242 messages.

| Level | Status | Count | Share |
|---|---|---|---|
| Payment | `receipt-not-found` | 160 | about 71% |
| Payment | success | 46 | |
| Payment | apply failed | 12 | |
| Payment | customer not found | 6 | |
| Line | `no-receipt-match` | 659 | 64% |
| Line | applied | 258 | 25% |
| Line | no remaining balance | 103 | |

Another 19 messages were fatal: SOAP, REST 401/404 and SFTP failures.

**Failure categorization:** 122 failed payments.

| Category | Share | Auto-fix |
|---|---|---|
| Receipt not in Fusion yet (timing) | 46% | Re-match when the receipt arrives, with backoff and aging. |
| Timing miss mislabeled as a relationship failure (receipts created a day after their receipt date) | 21% | Same as above. Also consider the receipt *creation* date, not just the receipt date. |
| Apply fault after a match (mostly whole-rupee INR) | 22% | Parse the fault code, then the per-code fixes in §3. |
| Fatal SOAP/SFTP | 4% | Infrastructure retry. |
| Amount variance (bank fees, short pays) | 3% | Tolerance or bank-fee band (configurable), otherwise a person. |
| Outside the date window | 1% | Widened window on re-match, otherwise a person. |
| Dual currency | 1% | A person. |
| Anchor never resolved (prepaid, very old receipt) | 2% | A person. |

**About 67% of failures fixed themselves given time.** A re-match triggered when the receipt arrives is the single biggest lever on the automation rate.

**Guardrails stated by the business**
- Retry only *transient* failures. Never retry not-found or closed invoices.
- Never act on an item a person is working.
- Never auto-assign multi-account payers.

## 7. Architecture lessons

- **The ledger table is the system.** In the old design one request table was "the queue, the state machine, the audit trail and the watchdog". Moving to Kafka replaced only the queue and lost selective re-drive. → Keep state in the database and use the bus only for notifications.
- **Persist before publishing. Commit offsets only after persisting.**
- **Use real transactions.** The old stack committed every insert separately and relied on a never-built sweep for half-written rows.
- **A DLQ from day one.** Malformed messages vanished.
- **Kafka/Streaming hygiene:**
  - one consumer group per environment, never renamed or reset ("read from beginning" replays everything)
  - versioned topic and schema contracts
  - capture partition and offset
  - publish only terminal outcomes downstream
- **SOAP apply is about 6 seconds per line** and scaled roughly linearly in the benchmark. A remittance with 30–100+ lines is minutes of serial work. Plan for concurrency limits per receipt, and back-pressure against Fusion.
- **A fatal error mid-loop must not lose the record of lines already applied.** Persist each apply result as it happens.
- **Test data must cover:**
  - split payments
  - short pays
  - INR rounding
  - duplicate amounts
  - credit memos
  - ambiguous receipts
  
  The old generator only made 1:1 same-amount pairs.
