# s10-validate-station: Validate station (code checks on the adjudicated extraction)

- Issue: #10
- Wave: 3 (owns `cashapp/stations/validate/`, `cashapp/services/validation.py`)
- breaking: false

## Story

As AR, I want obvious data problems caught by code, not the LLM, before anything touches Fusion, so that bad extractions fail fast with a clear code.

## Context

No LLM calls in this station. Header ≠ sum of lines is common and legitimate: a flag, not a failure (reference doc §2, §4.10). Ambiguous `$` is deferred to customer resolution (s11).

## Acceptance criteria

1. [unit] `validate(extraction: RemittanceExtraction, today: date) -> ValidationReport{flags: set[InfoFlag], errors: list[ValidationIssue{code: ErrorCode, field_path, message}], cleaned: RemittanceExtraction}` is a pure function in `cashapp/services/validation.py`.
2. [unit] Header amount vs sum of line `amount_paid` (lines with amounts only, credit memos negative) differing by more than 0.005 adds `InfoFlag.PAYMENT_HEADER_LINE_MISMATCH` and is NOT an error.
3. [unit] Invoice numbers: trimmed, must match `^[A-Za-z0-9][A-Za-z0-9\-_/\.]{0,39}$`, scientific-notation forms (`2.598014E6`) → `INVALID_INVOICE_NUMBER`; duplicate transaction numbers are kept (dedupe happens in s15) but flagged in the report.
4. [unit] Dates: payment date missing → `MISSING_PAYMENT_DATE`; a payment date more than 400 days old or more than 60 days in the future → `INVALID_DATE`. Currency: a present ISO code not in ISO 4217 → `INVALID_CURRENCY`; `currency_ambiguous=True` or `currency=None` with raw `$` is NOT an error (deferred to s11).
5. [unit] Zero-amount lines (`|amount_paid| ≤ 0.005`) are rejected: removed from `cleaned`, listed as `ZERO_AMOUNT_LINE` issues; if every line is zero and the header is zero → error `ZERO_AMOUNT_LINE` for the item. Lines with no amount are kept.
6. [unit] References only (PO/SO/ERS refs and no invoice-like transaction numbers) → `PO_SO_ERS_ONLY` (always a person).
7. [integration] `ValidateRunner` (stage VALIDATE) loads the latest adjudication (`AdjudicationRepository.latest_for`), runs `validate`, writes flags to `WORK_ITEM.INFO_FLAGS`, copies `payment_amount`, `currency` (if unambiguous), `payment_date`, `payer_name` onto the work item, records the report in history, and returns `Advance(RESOLVE_CUSTOMER)`; any error raises `StageError(<first error code by severity>, detail={"issues": [...]})` so the auto-fix engine gets a typed code.
8. [unit] A static test asserts nothing under `cashapp/stations/validate/` or `cashapp/services/validation.py` imports `cashapp.integrations.llm`.
9. [unit] `ROLE = RoleSpec("validate", "consumer", build)`.

## Out of scope

Customer and currency resolution (s11); fixes (s18).

## Deps

- s09-adjudicate-fan-in — `AdjudicationRepository.latest_for(item_id)`. plannable.
- s08-extraction-fan-out — `RemittanceExtraction`, `make_extraction`. plannable.
- s02-data-layer-foundation — `InfoFlag`, `ErrorCode`, `money_eq`. plannable.
- s03-pipeline-runtime — `StageRunner`. plannable.

## Assumptions

- The date bounds (400 days back, 60 forward) are code constants for now; they can move to config later.
