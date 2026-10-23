# s11-customer-resolution: Customer resolution (payer aliases, anchor customer, pay-on-behalf relationships)

- Issue: #11
- Wave: 3 (owns `cashapp/stations/resolve_customer/`, `cashapp/services/customer.py`, `cashapp/data/repositories/customer_resolution.py`)
- breaking: false

## Story

As AR, I want each remittance tied to the right Fusion customer account(s) before receipt matching, so that receipts are searched under the right owners and multi-account payers never get auto-assigned.

## Context

Reference doc §4.2–4.4: anchor = `BillToCustomerNumber` of the first allocation whose invoice was found (query both invoices and credit memos); pay-on-behalf relationships (BIP report, one hop, both directions, deduplicated) only widen the receipt search and are never a failure; never auto-assign a payer that maps to several accounts; resolve ambiguous `$` from the customer's account currency.

## Acceptance criteria

1. [unit] `resolve_customer(extraction, *, aliases: AliasLookup, fusion: FusionClient) -> CustomerResolution{anchor_customer_number, related_customer_numbers: tuple[str,...], method: "alias"|"invoice", alias_ids: tuple[int,...], transactions: list[FusionTransaction], currency: str|None, flags: set[InfoFlag]}` in `cashapp/services/customer.py`.
2. [unit] Aliases first: `aliases.lookup(payer_name, payer_bank_account, references)` (s37); exactly one customer → anchor from alias (`method="alias"`, `InfoFlag.ALIAS_USED`, alias id recorded); more than one customer → `StageError(CUSTOMER_MULTIPLE_ACCOUNTS)` (never auto-assigned); none → invoice path.
3. [unit] Invoice path: one batched `fusion.find_transactions(all line transaction numbers)` (both invoices and credit memos); the anchor is the `bill_to_customer_number` of the first extracted line (by `line_no`) whose transaction was found; no transaction found → `StageError(INVOICE_NOT_FOUND)` when every line is unmatched, and no anchor → `CUSTOMER_NOT_FOUND`. Found transactions are kept on the resolution for s16/s13/s15 (no second lookup needed unless stale).
4. [unit] Lines whose bill-to customer differs from the anchor and isn't related → recorded per line (`allocation-customer-not-found` candidate) but don't fail the item; transactions billed to two or more accounts with no relationship → `InfoFlag.MULTIPLE_ACCOUNTS_SAME_RECEIPT`.
5. [unit] Relationships: `fusion.customer_relationships([anchor])` → one hop, both directions, deduplicated, anchor excluded; a relationship lookup failure or empty result is never an error (logged, empty set).
6. [unit] Currency: if the extraction currency is ambiguous/missing, take the anchor's account currency from `fusion.get_customer_account(anchor).currency_codes`; exactly one → use it and add `InfoFlag.CURRENCY_RESOLVED_FROM_CUSTOMER`; several (dual-currency payer) → `StageError(DUAL_CURRENCY)` (always a person); invoice currencies disagreeing with the payment currency are left for s15's per-line check.
7. [integration] One Alembic revision creates `CUSTOMER_RESOLUTION` (ID, WORK_ITEM_ID, ANCHOR_CUSTOMER_NUMBER, RELATED_CUSTOMER_NUMBERS JSON, METHOD, ALIAS_IDS JSON, CURRENCY, TRANSACTIONS JSON, CREATED_AT); `CustomerResolutionRepository.latest_for(item_id)` is the accessor s13/s15/s16/s20 use.
8. [integration] `ResolveCustomerRunner` (stage RESOLVE_CUSTOMER) honours `HUMAN_HINTS["customer_number"]` (a person's choice, `method="human"`), stores the resolution, sets `WORK_ITEM.CUSTOMER_ACCOUNT_NUMBER` and `CURRENCY`, writes a DECISION history row explaining the anchor choice, and returns `Advance(FAST_PATH)`.
9. [unit] `ROLE = RoleSpec("resolve-customer", "consumer", build)`.

## Out of scope

Receipt search (s13); learning aliases (s37).

## Deps

- s05-fusion-client — `find_transactions`, `customer_relationships`, `get_customer_account`, `FakeFusionClient`, `FusionScenario`. plannable.
- s37-payer-alias-learning — `AliasLookup` Protocol `lookup(payer_name: str|None, bank_account: str|None, references: Sequence[str]) -> AliasMatch{customer_numbers: tuple[str,...], alias_ids: tuple[int,...]}` from `cashapp/services/aliases.py`. plannable (same wave).
- s09-adjudicate-fan-in — `AdjudicationRepository.latest_for`. plannable.
- s03-pipeline-runtime — `StageRunner`, `StageError`. plannable.
- s30-worker-host — `RoleSpec`. plannable.

## Assumptions

- `HUMAN_HINTS` keys (`customer_number`, `receipt_id`, `target_stage`) are written only by s18 requeue; `FIX_HINTS` only by s18 handlers (s02 pins both).
