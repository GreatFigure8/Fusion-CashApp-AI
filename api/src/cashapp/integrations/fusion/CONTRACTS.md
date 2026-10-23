# Fusion contracts

One row per endpoint, field or element the client depends on. `CONFIRMED` rows come from the
reference doc (prior production build) or a `-m live` probe; everything else is `UNVERIFIED` and
carries an `# UNVERIFIED:` comment in code. The fake models this contract; it does not prove it.

| Item | Where | Status | Source |
|---|---|---|---|
| `REST-Framework-Version: 4`, `onlyData=true`, explicit `fields=` | transport | CONFIRMED (prior build) | reference doc 3 |
| `receivablesInvoices` `q=TransactionNumber in (...)` | client | CONFIRMED (prior build) | reference doc 3 |
| `receivablesCreditMemos` `q=TransactionNumber in (...)`, balances negative | client | CONFIRMED (prior build) | reference doc 3 |
| `standardReceipts` list, `expand=remittanceReferences` | client | CONFIRMED (prior build) | reference doc 3 |
| `standardReceipts` cannot filter `UnappliedAmount` or `Currency` | client | CONFIRMED (prior build) | reference doc 3 |
| SOAP `createApplyReceipt` on `/fscmService/StandardReceiptService`, keyed `ReceiptId` + `CustomerTrxId` | soap | CONFIRMED (prior build) | reference doc 3 |
| SOAP noise codes and fault codes (AR-855287, AR-856102, ORA-00054, AR-856792, AR-856089) | errors | CONFIRMED (prior build) | reference doc 3, 6 |
| BIP `runReport` on `/xmlpserver/services/ExternalReportWSSService`, XML format | bip | CONFIRMED (prior build) | reference doc 3 |
| Invoice fields `EnteredAmount`, `BillToSite`, `PaymentTerms` | query | UNVERIFIED | |
| Credit memo fields `TransactionBalanceDue`, `EnteredAmount`, `BillToSite`, `CurrencyCode`, `TransactionStatus` | query | UNVERIFIED | |
| Receipt fields `CreationDate`, `Comments`; child `remittanceReferences.ReferenceNumber` | query | UNVERIFIED | |
| `CreationDate` filter literal format `'YYYY-MM-DDTHH:MM:SS+00:00'` | query | UNVERIFIED | |
| `standardReceipts/{id}/child/receiptApplications` and its fields | client | UNVERIFIED | falls back to a BIP data model (s32) |
| `receivablesInvoices/{id}/child/receiptApplications` and its fields | client | UNVERIFIED | falls back to a BIP data model (s32) |
| Customer account resource `/crmRestApi/resources/11.13.18.05/accounts` and its fields | client | UNVERIFIED | |
| `PATCH standardReceipts/{id}` body `{"Comments": ...}`, size limit | client | UNVERIFIED | confirmed by s17 |
| `POST standardReceipts/{id}/child/attachments` body and `AttachedDocumentId` | client | UNVERIFIED | confirmed by s17 |
| SOAP namespaces, `SOAPAction` values, `ReceiptCurrency`, `DiscountTaken`, `ReceivableApplicationId` | soap | UNVERIFIED | |
| SOAP unapply operation `createUnapplyReceipt` and its elements | soap | UNVERIFIED | confirmed by s38 |
| BIP namespace `PublicReportService`, request element names, HTTP basic auth | bip | UNVERIFIED | |
| Relationships report row shape (`P_ACCOUNT_NUMBERS`, `G_1` rows) | bip | PINNED by this client | s32 builds the report to match |
