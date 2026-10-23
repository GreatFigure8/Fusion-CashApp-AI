# s23-fusion-test-data-generator: Fusion test-data generator with realistic scenarios

- Issue: #23
- Wave: 4 (owns `cashapp/tools/testdata/`)
- breaking: false

## Story

As a tester, I want repeatable Fusion test data for every hard case, so that matching and apply can be tested without production data.

## Context

CLAUDE.md *Working with BMN → Test data*; reference doc §3 (test-data calls) and §7 (cases the old 1:1 generator couldn't make). Writes go only to a non-production pod and only when Jonathan provides credentials; until then the generator is exercised against `FakeFusionClient` (which implements the same low-level REST surface for these endpoints). Payload field names are UNVERIFIED until confirmed on the pod (`aix-greenlight` `fusion_rest_describe` may be used).

## Acceptance criteria

1. [unit] `cashapp/tools/testdata/scenarios.py`: parameterised `Scenario` objects producing a `ScenarioPlan{customer_account, invoices: [{number, amount, currency, terms|None}], credit_memos: [...], receipts: [{number, amount, currency, receipt_date}], remittance: RemittanceExtraction (the matching synthetic remittance), expected: {receipt_number, lines: [{number, line_status, applied_amount}]}}`. Presets: `one_to_one`, `split_payment` (1 receipt, N invoices), `short_pay`, `inr_rounding` (whole-rupee receipt vs paise invoices), `duplicate_amounts` (two receipts same amount different dates/refs), `ambiguous_receipts` (two qualifying receipts), `credit_memo_netting`, `already_applied`. Parameters: currency, line count, amounts seed.
2. [unit] `cashapp/tools/testdata/generator.py`: `generate(plan, fusion, *, tag) -> GeneratedData` creates invoices with `rest_post("receivablesInvoices", …)` then `…/action/completeTransaction`, credit memos with `receivablesCreditMemos` (complete as needed), and unapplied receipts with `rest_post("standardReceipts", …)` with no application child; returns created ids/numbers.
3. [unit] Every generated record is tagged: transaction/receipt numbers prefixed `CATD-<tag>-` and the comments/description field carries `cashapp-testdata:<tag>`; `cleanup(tag)` lists tagged records (reads only) and prints the Fusion steps to void/reverse them (no automatic deletes).
4. [unit] Refuses to run against a pod with `is_production=True` or whose base URL matches a configured production host, before any call (test), in addition to FusionClient's own write guard.
5. [unit] CLI `uv run python -m cashapp.tools.testdata --pod dev --scenario split_payment --lines 5 --currency USD --tag T001 [--dry-run]`; `--dry-run` prints the plan JSON without calling Fusion. Also writes the synthetic remittance as a fixture file usable by s24 and the pipeline's FolderSource.
6. [integration] `-m live`: generate `one_to_one` on the configured dev pod and read it back; skipped without credentials.

## Out of scope

Running scenarios through the pipeline (s24 does that against fakes).

## Deps

- s05-fusion-client — `rest_post(path, json)`, `rest_get`, `FusionClientFactory.for_pod`, `FakeFusionClient` supporting these POSTs. plannable.
- s08-extraction-fan-out — `RemittanceExtraction`. plannable.

## Assumptions

- Business unit, transaction type, receipt method and bank account for generated records are settings of the dev pod (`fusion.pods[dev].testdata` block), not code.
