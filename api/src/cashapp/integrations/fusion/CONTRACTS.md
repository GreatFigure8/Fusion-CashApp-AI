# Fusion contracts

One row per endpoint, field or element the client depends on. `CONFIRMED` rows come from the
reference doc (prior production build) or a `-m live` probe; everything else is `UNVERIFIED` and
carries an `# UNVERIFIED:` comment in code. The fake models this contract; it does not prove it.

| Item | Transport | Where | Status | Source |
|---|---|---|---|---|
| `REST-Framework-Version: 4`, `onlyData=true`, explicit `fields=` | MCP (fusion_rest_get) | mcp_client | CONFIRMED (prior build) | reference doc 3 |
| `receivablesInvoices` `q=TransactionNumber in (...)` | MCP (fusion_rest_get) | mcp_client | CONFIRMED (prior build) | reference doc 3 |
| `receivablesCreditMemos` `q=TransactionNumber in (...)`, balances negative | MCP (fusion_rest_get) | mcp_client | CONFIRMED (prior build) | reference doc 3 |
| `standardReceipts` list, `expand=remittanceReferences` | MCP (fusion_rest_get) | mcp_client | CONFIRMED (prior build) | reference doc 3 |
| `standardReceipts` cannot filter `UnappliedAmount` or `Currency` | MCP (fusion_rest_get) | mcp_client | CONFIRMED (prior build) | reference doc 3 |
| SOAP `createApplyReceipt` on `/fscmService/StandardReceiptService`, keyed `ReceiptId` + `CustomerTrxId` | SOAP | soap | CONFIRMED (prior build) | reference doc 3 |
| SOAP noise codes and fault codes (AR-855287, AR-856102, ORA-00054, AR-856792, AR-856089) | SOAP | errors | CONFIRMED (prior build) | reference doc 3, 6 |
| BIP `runReport` on `/xmlpserver/services/ExternalReportWSSService` | removed | bip | REMOVED | ad-hoc SQL through `run_query` replaces it |
| Invoice fields `EnteredAmount`, `BillToSite`, `PaymentTerms` | MCP (fusion_rest_get) | query | UNVERIFIED |  |
| Credit memo fields `TransactionBalanceDue`, `EnteredAmount`, `BillToSite`, `CurrencyCode`, `TransactionStatus` | MCP (fusion_rest_get) | query | UNVERIFIED |  |
| Receipt fields `CreationDate`, `Comments`; child `remittanceReferences.ReferenceNumber` | MCP (fusion_rest_get) | query | UNVERIFIED |  |
| `CreationDate` filter literal format `'YYYY-MM-DDTHH:MM:SS+00:00'` | MCP (fusion_rest_get) | query | UNVERIFIED |  |
| `standardReceipts/{id}/child/receiptApplications` and its fields | MCP (fusion_rest_get) | mcp_client | UNVERIFIED | falls back to a BIP data model (s32) |
| `receivablesInvoices/{id}/child/receiptApplications` and its fields | MCP (fusion_rest_get) | mcp_client | UNVERIFIED | falls back to a BIP data model (s32) |
| Customer account resource `/crmRestApi/resources/11.13.18.05/accounts` and its fields | MCP (fusion_rest_get) | mcp_client | UNVERIFIED |  |
| `PATCH standardReceipts/{id}` body `{"Comments": ...}`, size limit | MCP (fusion_rest_write) | mcp_client | UNVERIFIED | describe-confirmed (`Comments` string, maxLength 2000, updatable; non-prod pod 2026-10-23), write UNVERIFIED; confirmed by the s17 live probe |
| `POST standardReceipts/{id}/child/attachments` body and `AttachedDocumentId` | MCP (fusion_rest_write) | mcp_client | UNVERIFIED | describe-confirmed (`DatatypeCode`, `FileName`, `Title`, `UploadedFileContentType`, `FileContents`, `AttachedDocumentId`, `CreationDate`), write UNVERIFIED; confirmed by the s17 live probe |
| `GET standardReceipts/{id}/child/attachments` fields `AttachedDocumentId,FileName,Title,CreationDate` (`list_receipt_attachments`) | MCP (fusion_rest_get) | mcp_client | UNVERIFIED | s17 live probe |
| SOAP namespaces, `SOAPAction` values, `ReceiptCurrency`, `DiscountTaken`, `ReceivableApplicationId` | SOAP | soap | UNVERIFIED |  |
| SOAP unapply operation `createUnapplyReceipt` and its elements | SOAP | soap | UNVERIFIED | confirmed by s38 |
| BIP namespace `PublicReportService`, request element names, HTTP basic auth | removed | bip | REMOVED | no BIP call remains |
| Relationships report row shape (`P_ACCOUNT_NUMBERS`, `G_1` rows) | MCP (run_query) | bip | PINNED by this client | s32 builds the report to match |
| GET `?WSDL` on `StandardReceiptService` (operation `createApplyReceipt`) | SOAP | preflight | UNVERIFIED | s32 |
| `GET standardReceipts/describe` lists an `attachments` child | MCP (fusion_rest_get) | preflight | UNVERIFIED | s32 |
| Data-model catalog keys `/Custom/CashApp/CashAppRelationships.xdo`, `/Custom/CashApp/CashAppReceiptSignals.xdo` (names only; no BIP report is created) | MCP (run_query) | datamodels | UNVERIFIED | s32 |
| SQL data models `relationships.sql`, `receipt_signals.sql` (HZ/AR/CE/IBY table and column names) | MCP (run_query) | datamodels | UNVERIFIED | s32 |
| Payment-terms resource `receivablesPaymentTerms`, `q=Name=` / `q=TermId=` filter | MCP (fusion_rest_get) | query | UNVERIFIED | s39 |
| Payment-terms fields `TermId`, `Name`, `DiscountTiers` (`DiscountDays`, `DiscountPercent`) | MCP (fusion_rest_get) | query | UNVERIFIED | s39 |
| Invoice field `TransactionDate` (start of the discount clock) | MCP (fusion_rest_get) | query | UNVERIFIED | s39 |
| SOAP `DiscountTaken` sent with `AmountApplied` on one `createApplyReceipt` call | SOAP | soap | UNVERIFIED | s39 |
| Application discount field (`DiscountTaken` on `receiptApplications`) | MCP (fusion_rest_get) | mcp_client | UNVERIFIED | s39 |
| Discount-rejection fault code(s) in `DISCOUNT_REJECT_CODES` (empty until probed) | SOAP | errors | UNVERIFIED | s39 |

## fusion-sql-mcp (Greenlight) server contract

Reads and REST writes go through this server (verified against `D:\fusion-sql-mcp\backend\src\fusion_sql_mcp`
on 2026-10-23). The cash app is an OAuth `client_credentials` client (scope `greenlight/mcp`).

| Item | Transport | Where | Status | Source |
|---|---|---|---|---|
| Tools `list_sources`, `run_query`, `fetch_rows`, `fusion_rest_get`, `fusion_rest_describe`, `fusion_rest_write` (plus `describe_table`, probed live only) | MCP | mcp/client | CONFIRMED (server source) | `server.py`, `fusion/rest_tools.py` |
| `fusion_rest_get(source, path, params, account)` returns `RestOutput{status, body, has_more, duration_ms, account_used}`; one call is one page; `limit` capped by `fusion_rest_max_rows` | MCP | mcp_client | CONFIRMED (server source) | `rest_tools.py` |
| `fusion_rest_write(source, method POST\|PATCH\|DELETE, path, body, account)`, refused unless write-back is on for the source and the path is allowlisted | MCP | mcp_client | CONFIRMED (server source) | `rest_tools.py` |
| `run_query(source, sql, max_rows, account, keep_result, slices)` returns `QueryOutput{columns, rows, truncated, total_rows, result_id, status, error}`; one SELECT or WITH on a Fusion source; no bind parameters | MCP | mcp_client | CONFIRMED (server source) | `server.py` |
| `fetch_rows(result_id, offset, max_rows)` pages a kept result | MCP | mcp_client | CONFIRMED (server source) | `server.py` |
| The server sends `REST-Framework-Version` (`fusion_rest_framework_version`, default 4); the worker start-up probe fails on a 400 | MCP | mcp_client.verify_framework | CONFIRMED (server source) | `rest.py:221`, `models.py:257` |
| `ToolError` texts: `Fusion answered <status>`, `No answer from the pod`, `Write-back is off`, `write allowlist` | MCP | mcp/errors | CONFIRMED (server source) | `rest.py:121-128`, `rest_tools.py` |
| Tool results are read from the text content with `Decimal`, never from the float `structuredContent` | MCP | mcp/client | PINNED by this client | |
| REST action calls (for example `completeTransaction`) need `application/vnd.oracle.adf.action+json`; `fusion_rest_write` may send plain JSON | MCP | testdata tool | UNVERIFIED | cross-repo follow-up for fusion-sql-mcp |
| `fusion_rest_get` has no binary download; `get_raw` serves only a SOAP `?WSDL` (direct), anything else is `FUSION_FAULT` | MCP / SOAP | mcp_client | PINNED by this client | cross-repo follow-up if a binary GET is needed |
