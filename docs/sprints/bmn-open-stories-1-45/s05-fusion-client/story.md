# s05-fusion-client: FusionClient (REST, SOAP apply, BI Publisher, typed errors, Vault credentials)

- Issue: #5
- Wave: 2 (owns `cashapp/integrations/fusion/`)
- breaking: false

## Story

As every station that talks to Fusion, I want one client that encodes what worked in the previous build and maps every failure to a typed error code, so that no station ever builds a Fusion request itself.

## Context

Reference doc §3 (calls, headers, SOAP fail-closed, noise codes, faults). research.md a6 rails: `FUSION_WRITE_ENABLED=false` by default, prod-pod refusal for writes outside a release-approved config, defusedxml SOAP parsing. Built against a fake built from recorded responses; every endpoint/field not yet confirmed on a non-production pod is marked `UNVERIFIED` in code and in `integrations/fusion/CONTRACTS.md`, and a `-m live` probe test per call confirms it when pod credentials exist (`aix-greenlight` `fusion_rest_describe`/`fusion_rest_get` may be used to confirm REST shapes during coding).

## Acceptance criteria

1. [unit] `cashapp/integrations/fusion/client.py`: `FusionClient` Protocol and `HttpFusionClient` implementation with these methods (models are frozen dataclasses in `models.py`, money as `Decimal`):
   - `find_transactions(numbers: Sequence[str]) -> list[FusionTransaction]` — one batched `TransactionNumber in (...)` call each to `receivablesInvoices` and `receivablesCreditMemos` (chunked at 50), `FusionTransaction{customer_trx_id, number, kind: INVOICE|CREDIT_MEMO, balance (credit memos negative), original_amount, currency, status, bill_to_customer_number, bill_to_site, business_unit, payment_terms|None}`.
   - `find_receipts(*, customer_numbers, date_from, date_to, by: "receipt_date"|"creation_date") -> list[FusionReceipt]` with `expand=remittanceReferences`; `FusionReceipt{receipt_id, receipt_number, amount, unapplied_amount, currency, customer_account_number, receipt_date, creation_date, status, state, remittance_references: tuple[str,...], comments|None}`; currency/amount filtering is the caller's (tenant can't filter them).
   - `receipts_created_since(since: datetime, *, limit) -> list[FusionReceipt]` (ordered by creation time).
   - `get_receipt(receipt_id) -> FusionReceipt`; `list_receipt_applications(receipt_id) -> list[FusionApplication]`; `list_transaction_applications(customer_trx_id) -> list[FusionApplication]` (`FusionApplication{application_id, receipt_id, customer_trx_id, amount_applied, apply_date, status}`).
   - `get_customer_account(account_number) -> FusionCustomer{account_number, name, currency_codes, sites[]}`.
   - `customer_relationships(account_numbers) -> list[CustomerRelationship]` via BIP report path from setting `fusion.relationships_report_path`, deduplicated INBOUND/OUTBOUND.
   - `apply_receipt(ApplyRequest{receipt_id, customer_trx_id, amount_applied (signed), receipt_currency, application_date, accounting_date, discount_amount: Decimal|None=None}) -> ApplyResult{ok, application_id|None, fault: FusionFault|None, raw_messages}`.
   - `unapply_receipt(UnapplyRequest{receipt_id, application_id, reversal_gl_date, reason}) -> UnapplyResult` (UNVERIFIED until s38 confirms).
   - `set_receipt_comment(receipt_id, text) -> None` and `attach_to_receipt(receipt_id, filename, content: bytes, content_type, title) -> AttachmentRef` (UNVERIFIED until s17 confirms).
   - `run_report(path, params: Mapping[str,str], fmt="xml") -> bytes` (BIP `runReport`, Base64-decoded).
   - Low-level `rest_get(path, params)` / `rest_post(path, json)` for tools (s23, s32).
2. [unit] Every REST call sends `REST-Framework-Version: 4`, `onlyData=true` and explicit `fields=`; follows `hasMore`/`offset` pagination; every `q=` literal is escaped (single quotes doubled) by one helper `q_literal()` with tests for `O'Brien` and `in (...)` lists.
3. [unit] SOAP `createApplyReceipt` on `/fscmService/StandardReceiptService` keyed on `ReceiptId` and `CustomerTrxId`; accounting/application date = `max(payment_date, today)` computed by `accounting_date_for(payment_date, today)`; parsing with defusedxml is fail-closed: success only if a `Value` block exists and no fault; ADF `ServiceErrorMessage` inside HTTP 200 is a failure; noise codes `AR_RAPI_TRX_NUM_IGN`, `AR_RAPI_RCPT_NUM_IGN`, `GENERIC_MESSAGE`, `FND_AS_UNEXPECTED_ERROR`, AR-855741, AR-855799 are ignored; the receipt ID matched on is kept (response ReceiptId is nil). Tests use recorded envelopes for success, 200-with-fault, mixed noise + real fault.
4. [unit] `errors.py`: `FusionError(code: ErrorCode, fusion_code: str|None, message, retryable)` mapping AR-855287→FUSION_OVERAPPLY, AR-856102→FUSION_ALREADY_APPLIED, ORA-00054/AR-856792→FUSION_LOCKED, AR-856089→FUSION_GL_DATE, 401/5xx/timeouts/`NotAuthorizedOrNotFound`→FUSION_TRANSIENT, other faults→FUSION_FAULT. Transient calls retry with bounded exponential backoff inside the client (max 3) before raising.
5. [unit] Credentials come from `Settings.fusion.pods[name]` (Vault-resolved by s27); `FusionClientFactory.for_pod(name)` selects dev/test/prod by configuration. Every write method (`apply_receipt`, `unapply_receipt`, `set_receipt_comment`, `attach_to_receipt`, `rest_post`) raises `FusionError(FUSION_WRITE_DISABLED)` unless `settings.fusion.write_enabled` is true, and refuses a pod with `is_production=True` unless `settings.env == "prod"`.
6. [unit] `cashapp/integrations/fusion/fake.py`: `FakeFusionClient` implementing the Protocol over an in-memory ledger (transactions, receipts, applications) that enforces Fusion behaviour (overapply fault, already-applied fault, balance and unapplied updates on apply/unapply), seeded from `api/tests/fixtures/fusion/*.json` recordings or a scenario builder.
7. [integration] `-m live` probe tests per call against a configured non-production pod; each records its confirmation in `CONTRACTS.md` (endpoint, fields, date confirmed). Skipped without credentials.

## Out of scope

Matching rules; deciding what to apply; the BIP report itself (s32).

## Deps

- s27-settings-secrets-wiring — `Settings.fusion{pods, default_pod, write_enabled, relationships_report_path}` (add `relationships_report_path`), `env`. plannable.
- s02-data-layer-foundation — `ErrorCode`, `money.to_money`. plannable.
- s29-observability — `span("fusion.<method>")`, `get_logger`. plannable (same wave).

## Test-support files owned

`cashapp/integrations/fusion/fake.py`, `api/tests/fixtures/fusion/` (recorded REST JSON and SOAP envelopes), `api/tests/support/fusion.py` (`FusionScenario` builder: `.invoice(...)`, `.credit_memo(...)`, `.receipt(...)`, `.build() -> FakeFusionClient`). Used by s11, s13, s14, s15, s16, s17, s38, s39, s24.

## Assumptions

- Receipt note = the `Comments` field on `standardReceipts` (UNVERIFIED; s17 confirms the field and its size).
- Attachments via `standardReceipts/{id}/child/attachments` (UNVERIFIED; s17 confirms).
