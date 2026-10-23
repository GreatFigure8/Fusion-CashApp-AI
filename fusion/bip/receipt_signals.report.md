# CashAppReceiptSignals report definition (optional)

| Item | Value |
|---|---|
| Data model name | `CashAppReceiptSignals` |
| Data model SQL | `receipt_signals.sql` |
| Data set | `DATA_DS` (SQL Query, data source `ApplicationDB_FSCM`) |
| Parameters | `P_DATE_FROM` and `P_DATE_TO`, text, `YYYY-MM-DD`, receipt date range, no defaults |
| Output format | XML (data-model-only report, no layout) |
| Layout | none |
| Catalog path | `/Custom/CashApp/CashAppReceiptSignals.xdo` |
| Setting | none; the receipt-matching tool takes the path as an option |

## Output shape

Root `DATA_DS`; one `G_1` element per receipt and matched statement line. Statement columns are
empty when the receipt is not reconciled.

`CASH_RECEIPT_ID`, `RECEIPT_NUMBER`, `RECEIPT_DATE`, `CREATION_DATE`, `AMOUNT`, `CURRENCY_CODE`,
`CUSTOMER_ACCOUNT_NUMBER`, `RECEIPT_COMMENTS`, `STATEMENT_LINE_ID`, `STATEMENT_LINE_REFERENCE`,
`STATEMENT_LINE_ADDENDA`, `STATEMENT_PAYER_NAME`, `PAYER_BANK_ACCOUNT_HASH`.

`PAYER_BANK_ACCOUNT_HASH` is the SHA-256 hash of the payer's bank account number. The raw number
is never selected, so the pipeline can compare payers for equality without holding the number.
