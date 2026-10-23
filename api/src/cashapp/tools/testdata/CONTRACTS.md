# Test-data generator contracts

One row per POST path or field the generator depends on. `UNVERIFIED` rows carry an
`# UNVERIFIED:` comment in `payloads.py` and are confirmed on a non-production pod (read-only with
`fusion_rest_describe`, then by the `-m live` test). Update the status to
`CONFIRMED <date> <pod>` when done. s05's own table is `integrations/fusion/CONTRACTS.md`.

| Item | Where | Status |
|---|---|---|
| `POST receivablesInvoices` with `TransactionNumber`, `BusinessUnit`, `TransactionType`, `TransactionDate`, `AccountingDate`, `BillToCustomerNumber`, `InvoiceCurrencyCode`, `Comments` | payloads | UNVERIFIED |
| Invoice `TransactionSource` value `Manual` | payloads | UNVERIFIED |
| Invoice `BillToSite`, `PaymentTerms` (sent only when given) | payloads | UNVERIFIED |
| Invoice line child `receivablesInvoiceLines` with `LineNumber`, `Description`, `Quantity`, `UnitSellingPrice` | payloads | UNVERIFIED |
| `POST receivablesInvoices/{id}/action/completeTransaction` with an empty body | generator | UNVERIFIED |
| `POST receivablesCreditMemos` (same shape, `CurrencyCode`, negative `UnitSellingPrice`) | payloads | UNVERIFIED |
| `POST receivablesCreditMemos/{id}/action/completeTransaction` (drop the step if the POST can create it complete) | generator | UNVERIFIED |
| Response id field `CustomerTransactionId` on create | generator | UNVERIFIED |
| `POST standardReceipts` with `ReceiptNumber`, `BusinessUnit`, `ReceiptMethod`, `ReceiptDate`, `AccountingDate`, `Amount`, `Currency`, `CustomerAccountNumber`, `Comments` and no application child | payloads | UNVERIFIED |
| Receipt `RemittanceBankAccountNumber` | payloads | UNVERIFIED |
| Receipt nested `remittanceReferences` with `ReferenceNumber` | payloads | UNVERIFIED |
| Response id field `StandardReceiptId` on create | generator | UNVERIFIED |
| `Comments` readable on invoices, credit memos and receipts (cleanup relies on it) | cleanup | UNVERIFIED |
| Transaction and receipt number length of `CATD-<8>-RCPT-999` (22 characters) | tagging | UNVERIFIED |
