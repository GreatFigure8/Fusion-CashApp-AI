# Plan: s10-validate-station

Validate is code, not the LLM. One pure service (`validate`) checks the adjudicated extraction and one thin `StageRunner` applies the result to the work item. No migration, no LLM, no Fusion.

## Standards followed

- **CLAUDE.md layering:** the rules live in `cashapp/services/validation.py`, a pure module with no I/O, no ORM and no `Request`. The runner (`cashapp/stations/validate/runner.py`) only loads, calls, persists and returns an outcome. Repositories are reached only through `ctx.uow`.
- **One StageRunner (s03):** `ValidateRunner` subclasses `StageRunner` and implements `process` only. The runner owns the claim, idempotency, history row, outbox event and failure routing. A failure is a typed `StageError`, so the s18 auto-fix engine gets an `ErrorCode`.
- **One status enum / one error-code enum (s02):** this story imports `InfoFlag` and `ErrorCode` and defines no status or error strings. The duplicate-number signal is a report field, not a new `InfoFlag` (see Assumptions).
- **Money (s02):** `Decimal` throughout, `money_eq` for every comparison (`|a-b| <= 0.005`), with no `float` and no `round`. Sums use `sum(..., Decimal("0"))`.
- **python-web-app (building-python-web-apps):** the logic sits in services and the station stays thin. External SDKs stay isolated: this story touches none.
- **PII (CLAUDE.md, s29):** `ValidationIssue.message` and `StageError.detail` carry codes, field paths, line numbers and amounts only. They never carry the payer name or artifact text. Logs carry ids and codes.
- **Auditable decisions:** the full report summary goes into the `Advance` payload, which s03 writes as the `STAGE_TRANSITION` history row. On error, the issues go into `LAST_ERROR_DETAIL`.
- The LLM skills aren't loaded: the station makes no LLM call, and AC8 enforces that.

## Files to touch

All files are new. They are file-disjoint from other stories: the owned paths are `cashapp/stations/validate/` and `cashapp/services/validation.py`, plus one new domain constant module and the tests.

| Path | Content |
|---|---|
| `api/src/cashapp/services/validation.py` | `ValidationIssue`, `ValidationReport`, `VALIDATION_ERROR_PRECEDENCE`, constants, `clean`, `validate`, `first_error`, `current_extraction` |
| `api/src/cashapp/domain/iso4217.py` | `ISO_4217_CODES: frozenset[str]` (active alphabetic codes, hand-written; see Assumptions), `is_iso_4217(code) -> bool` |
| `api/src/cashapp/stations/__init__.py` | empty; create only if absent |
| `api/src/cashapp/stations/validate/__init__.py` | re-exports `ROLE` |
| `api/src/cashapp/stations/validate/runner.py` | `ValidateRunner(StageRunner)`, `build(container)`, `ROLE` |
| `api/tests/services/test_validation.py` | unit tests AC1–AC6 |
| `api/tests/stations/validate/__init__.py` | empty, only if the test layout needs it |
| `api/tests/stations/validate/test_validate_runner.py` | integration tests AC7 (sqlite `uow_factory`) |
| `api/tests/stations/validate/test_no_llm_imports.py` | AC8 |
| `api/tests/stations/validate/test_role.py` | AC9 |

Not touched: `main.py`, lockfiles, `conftest.py`, s02 enums, s08 `extraction.py`, and s09 adjudication files (consumed only).

## Design

### `clean(extraction) -> RemittanceExtraction` (pure, independent of `today`)

- Returns `extraction.model_copy(update=...)` with every line's `transaction_number` stripped of surrounding whitespace (`str.strip()`).
- Drops every line whose `amount_paid is not None and money_eq(amount_paid, 0)`.
- Keeps lines with `amount_paid is None`.
- Keeps `line_no` unchanged, with no renumbering, so s09's `line_provenance` stays traceable.
- Changes nothing else.

### `validate(extraction, today) -> ValidationReport`

All checks run, and every issue is collected in one pass rather than stopping at the first. Constants are module-level `Final`s:
- `MAX_PAST_DAYS = 400`
- `MAX_FUTURE_DAYS = 60`
- `INVOICE_NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/\.]{0,39}$")`
- `SCI_NOTATION_RE = re.compile(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$")`

"Invoice-like" lines are those whose `kind` is in `INVOICE_LIKE_KINDS = {INVOICE, CREDIT_MEMO, UNKNOWN}`. `BANK_FEE`, `TARIFF` and `DISCOUNT` are adjustment lines.

1. **Header vs lines (AC2).**
   - `line_sum` = Σ over invoice-like lines with `amount_paid is not None`. A `CREDIT_MEMO` line contributes `-abs(amount_paid)`; any other kind contributes `amount_paid` as signed.
   - Adjustment kinds are excluded from the sum.
   - The check runs only when `payment_amount.value is not None` and at least one invoice-like line has an amount.
   - `not money_eq(header, line_sum)` adds `InfoFlag.PAYMENT_HEADER_LINE_MISMATCH` to `flags`. It is never an error.
   - `report.header_amount` and `report.line_sum` are recorded.
2. **Invoice numbers (AC3).** For each invoice-like line, take `n = transaction_number.strip()`:
   - `n == ""`, or `SCI_NOTATION_RE.match(n)`, or `not INVOICE_NUMBER_RE.match(n)` gives an error `INVALID_INVOICE_NUMBER` with field path `lines[<idx>].transaction_number`.
   - Note that `2.598014E6` *passes* the character-class regex, so the scientific-notation check is explicit and runs first.
   - Adjustment lines with `""` are skipped. A non-empty number on an adjustment line is checked the same way.
   - Duplicates: among invoice-like lines with valid numbers, compare by `n.upper()`. Any number seen more than once is listed once in `report.duplicate_transaction_numbers`, as the first-seen spelling in line order. The lines themselves are kept, because s15 dedupes.
3. **Dates (AC4).**
   - `payment_date.value is None` gives the error `MISSING_PAYMENT_DATE` at path `payment_date`.
   - Otherwise, `(today - d).days > 400` or `(d - today).days > 60` gives `INVALID_DATE`. Exactly 400 days past or 60 days ahead is valid.
4. **Currency (AC4).**
   - `currency.value is not None and not currency_ambiguous and not is_iso_4217(value)` gives `INVALID_CURRENCY` at path `currency`.
   - `currency_ambiguous=True`, or `currency.value is None` (with or without a raw `$`), is never an error: s11 resolves it.
   - `report.currency` is the value only when it is present, unambiguous and valid. Otherwise it is `None`.
5. **Zero amounts (AC5).**
   - Each line with `amount_paid` ≈ 0 adds a **notice** `ValidationIssue(ZERO_AMOUNT_LINE, "lines[<idx>].amount_paid", ...)`. Notices don't block. The line is absent from `cleaned`.
   - The item-level **error** `ZERO_AMOUNT_LINE` at path `""` is raised when `payment_amount.value is not None and money_eq(header, 0)` **and** either:
     - there were lines and every original line had `amount_paid` ≈ 0, or
     - there were no lines at all.
   - This mirrors s02's `roll_up` ZERO_AMOUNT rule.
6. **References only (AC6).**
   - `has_refs` is true when any of these is non-empty: `po_refs`, `sales_order_refs`, `ers_refs`, or any line's `po_number`, `sales_order` or `ers_reference`.
   - `has_invoice_like` is true when any invoice-like line in the original extraction has a non-empty number that passes check 2.
   - `has_refs and not has_invoice_like` gives the error `PO_SO_ERS_ONLY` at path `""`. That code is always a person (`spec.always_person`).
7. `cleaned = clean(extraction)`.

**Severity for AC7.** `VALIDATION_ERROR_PRECEDENCE` is `(PO_SO_ERS_ONLY, INVALID_INVOICE_NUMBER, MISSING_PAYMENT_DATE, INVALID_DATE, INVALID_CURRENCY, ZERO_AMOUNT_LINE)`:
- Always-person comes first.
- After that, the order follows s02's payment precedence: invoice, then date, then zero.
- `first_error(report)` returns the highest-precedence code present.
- `report.errors` is sorted by (precedence index, line index).

### `ValidateRunner.process(ctx)`

1. `adj = await ctx.uow.repo(AdjudicationRepository).latest_for(ctx.item.id)`. If it is `None`, raise `StageError(EXTRACTION_FAILED, detail={"reason": "no_adjudication"})`.
2. `extraction = RemittanceExtraction.model_validate(adj.final)`. A `pydantic.ValidationError` raises `StageError(EXTRACTION_FAILED, detail={"reason": "final_invalid", "adjudication_id": adj.id, "errors": <loc+type only, no input values>})`.
3. `report = validate(extraction, ctx.clock.now().date())`. "Today" is the UTC date.
4. If `report.errors` is non-empty:
   - raise `StageError(first_error(report), detail=report.to_detail(), message=...)`.
   - The runner rolls back, so nothing is written to the item except s03's failure bookkeeping (`LAST_ERROR_CODE`/`DETAIL`).
5. Otherwise, write to the item:
   - `item.info_flags = merged` (a new list: the existing values in order, then any new `InfoFlag` values, deduplicated). It is assigned rather than mutated in place, so the JSON change is detected.
   - `payment_amount = extraction.payment_amount.value`.
   - `currency = report.currency`, only when it is not `None`. An existing value is never overwritten with `None`.
   - `payment_date = extraction.payment_date.value`.
   - `payer_name = value[:500]` when present.
6. `return Advance(Stage.RESOLVE_CUSTOMER, note=<"validated: N lines kept, M zero lines dropped, flags=[...]">, payload=report.to_history_payload(adjudication_id=adj.id))`. s03 writes this payload on the `STAGE_TRANSITION` history row, which is "records the report in history".

## Interfaces provided (pinned)

```python
# cashapp/services/validation.py
MAX_PAST_DAYS: Final = 400
MAX_FUTURE_DAYS: Final = 60
INVOICE_NUMBER_RE: Final[re.Pattern[str]]       # ^[A-Za-z0-9][A-Za-z0-9\-_/\.]{0,39}$
INVOICE_LIKE_KINDS: Final[frozenset[LineKind]]  # {INVOICE, CREDIT_MEMO, UNKNOWN}
VALIDATION_ERROR_PRECEDENCE: Final[tuple[ErrorCode, ...]]
    # (PO_SO_ERS_ONLY, INVALID_INVOICE_NUMBER, MISSING_PAYMENT_DATE, INVALID_DATE, INVALID_CURRENCY, ZERO_AMOUNT_LINE)

@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: ErrorCode
    field_path: str            # "payment_date", "currency", "lines[3].transaction_number", "" = whole item
    message: str               # no payer name / artifact text
    line_no: int | None = None # the extraction line_no when the issue is about a line
    def to_dict(self) -> dict[str, Any]   # {"code", "field_path", "message", "line_no"}

@dataclass(frozen=True, slots=True)
class ValidationReport:
    flags: frozenset[InfoFlag]
    errors: tuple[ValidationIssue, ...]                 # blocking, sorted by VALIDATION_ERROR_PRECEDENCE then line
    cleaned: RemittanceExtraction
    notices: tuple[ValidationIssue, ...] = ()           # non-blocking: dropped zero-amount lines
    duplicate_transaction_numbers: tuple[str, ...] = ()
    header_amount: Decimal | None = None
    line_sum: Decimal | None = None
    currency: str | None = None                         # present, unambiguous and ISO 4217, else None
    @property
    def ok(self) -> bool                                # not errors
    def to_detail(self) -> dict[str, Any]               # {"issues": [...errors], "notices": [...], "flags": [...]}; JSON-safe, Decimal->str
    def to_history_payload(self, *, adjudication_id: int) -> dict[str, Any]
        # {"adjudication_id", "flags", "notices", "duplicate_transaction_numbers", "header_amount", "line_sum",
        #  "lines_in", "lines_kept"}; money as "0.00" strings

def clean(extraction: RemittanceExtraction) -> RemittanceExtraction
def validate(extraction: RemittanceExtraction, today: date) -> ValidationReport
def first_error(report: ValidationReport) -> ErrorCode | None
async def current_extraction(uow: UnitOfWork, item_id: int) -> RemittanceExtraction | None
    # clean(RemittanceExtraction.model_validate(AdjudicationRepository.latest_for(item_id).final)), or None.
    # The cleaned view (trimmed numbers, zero lines dropped) for s11/s13/s15/s16 to read instead of raw `final`.
    # Read-only. Imports only the data layer, so validation.py stays LLM-free.

# cashapp/domain/iso4217.py
ISO_4217_CODES: Final[frozenset[str]]
def is_iso_4217(code: str) -> bool        # exact upper-case membership

# cashapp/stations/validate/runner.py
class ValidateRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.VALIDATE
    async def process(self, ctx: StageContext) -> StageOutcome
def build(container: Container) -> Runnable      # StageConsumer(ValidateRunner.build(c), c.bus, c.settings.streaming.consumer_group)
ROLE: RoleSpec                                    # RoleSpec("validate", "consumer", build)
```

**Consumed (pinned elsewhere):**
- s09 `AdjudicationRepository.latest_for(item_id) -> Adjudication | None`, with `Adjudication.final` as a JSON dict and `Adjudication.id`.
- s08 `RemittanceExtraction`, `LineKind`, `make_extraction`.
- s02 `InfoFlag`, `ErrorCode`, `money_eq`, `Stage`, `UnitOfWork`, `make_work_item`.
- s03 `StageRunner`, `StageContext`, `Advance`, `StageError`, `RoleSpec`, `StageConsumer`, `make_runner_deps`, `memory_bus`.

## Migrations

None. The work-item columns written here (`INFO_FLAGS`, `PAYMENT_AMOUNT`, `CURRENCY`, `PAYMENT_DATE`, `PAYER_NAME`) are s02's, and `ADJUDICATION` is s09's. The Alembic head is unchanged.

## TEST PLAN (written and run in step 5 only)

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `api/tests/services/test_validation.py::test_validate_is_pure_and_returns_report` | `make_extraction()` with `today=2026-01-15`: the report has `ok`, empty errors, and `cleaned` equal to the input. Calling it twice gives equal reports, and the input is unchanged (deep-equal to a copy). The signature is `(RemittanceExtraction, date) -> ValidationReport`. The module does no I/O: `validate` makes no `await`, and the test is plain `def`. |
| 2 | `…::test_header_line_mismatch_is_flag_not_error` | Header 1300.00 with lines 1000.00 + 250.00: `PAYMENT_HEADER_LINE_MISMATCH` in flags, `errors == ()`. |
| 2 | `…::test_header_within_half_cent_and_credit_memo_negative` | Header 750.00 with INVOICE 1000.00 and CREDIT_MEMO 250.00 (or -250.00): no flag. Header 1250.004 vs 1250.00: no flag. Lines without amounts are excluded from the sum. BANK_FEE lines are excluded. No lines with amounts: no flag. |
| 3 | `…::test_invoice_numbers_trimmed_and_pattern_checked` | `"  INV-1001 "` is valid and trimmed in `cleaned`. `"2598014-1"` is valid. `"-ABC"`, `"A B"`, `""` on INVOICE, and a 41-character number give `INVALID_INVOICE_NUMBER` with path `lines[i].transaction_number`. |
| 3 | `…::test_scientific_notation_rejected` | `"2.598014E6"` and `"2.598014e+06"` give `INVALID_INVOICE_NUMBER`. |
| 3 | `…::test_duplicates_kept_and_reported` | Two lines `"INV-1"` and `"inv-1"`: both stay in `cleaned`, `duplicate_transaction_numbers == ("INV-1",)`, no error. A TARIFF line sharing an invoice number is not a duplicate. |
| 4 | `…::test_missing_payment_date` | `payment_date=None` gives `MISSING_PAYMENT_DATE`. |
| 4 | `…::test_payment_date_bounds` | `today` minus 400 days and plus 60 days are valid. Minus 401 days and plus 61 days give `INVALID_DATE`. |
| 4 | `…::test_currency_checks` | `"XYZ"` gives `INVALID_CURRENCY`. `"USD"` and `"INR"` are fine, with `report.currency == "USD"`. `currency_raw="$"` (ambiguous, value None) and `currency=None` give no error and `report.currency is None`. |
| 4 | `…::test_iso4217_table_sane` | `ISO_4217_CODES` contains USD, EUR, INR, CAD, AUD, GBP and JPY, and excludes XYZ. Every entry matches `^[A-Z]{3}$`. |
| 5 | `…::test_zero_lines_dropped_with_notice` | A line of 0.00 or 0.004 is absent from `cleaned` and listed in `notices` as `ZERO_AMOUNT_LINE`, not in `errors`. A line with `amount_paid=None` is kept. `line_no` values in `cleaned` are unchanged. |
| 5 | `…::test_all_zero_lines_and_zero_header_is_item_error` | All lines 0.00 with header 0.00 gives an item-level `ZERO_AMOUNT_LINE` error at path `""`. No lines with header 0.00 gives the same. All lines zero with header 100.00 gives only notices. |
| 6 | `…::test_po_so_ers_only_is_person` | `po_refs=["PO-77"]` with only adjustment lines or no lines gives `PO_SO_ERS_ONLY`, and `ErrorCode.PO_SO_ERS_ONLY.spec.always_person` holds. Refs plus one valid invoice line gives no error. Refs plus only an invalid invoice number gives both codes, and `first_error` is `PO_SO_ERS_ONLY`. |
| 6 | `…::test_first_error_follows_precedence` | Several errors (invalid currency, missing date, invalid number): `errors` is sorted by `VALIDATION_ERROR_PRECEDENCE`, and `first_error == INVALID_INVOICE_NUMBER`. |
| 7 | `api/tests/stations/validate/test_validate_runner.py::test_valid_item_advances_and_copies_fields` | A sqlite item at stage VALIDATE with an `Adjudication` row whose `final` is `make_extraction(...)` with a header mismatch, handled through `runner.handle(delivery)` on `memory_bus`: the item ends at stage RESOLVE_CUSTOMER / PENDING. `INFO_FLAGS` contains `payment-header-line-mismatch` and keeps a pre-existing flag. `payment_amount`, `currency == "USD"`, `payment_date` and `payer_name` are set. One `STAGE_TRANSITION` history row's payload has `flags`, `adjudication_id` and `line_sum`. One outbox event goes to the resolve-customer topic. |
| 7 | `…::test_latest_adjudication_used` | A MODEL row followed by a later HUMAN row with a different amount: the item gets the HUMAN amount, which proves `latest_for` is the accessor. |
| 7 | `…::test_ambiguous_currency_not_copied` | `currency_raw="$"`: `item.currency` stays `None`, and the item still advances. |
| 7 | `…::test_error_raises_typed_stage_error` | Missing payment date plus an invalid number: `HandleResult.status == FAILED_HANDLED`. `last_error_code == INVALID_INVOICE_NUMBER`. `last_error_detail["issues"]` lists both codes with field paths. The item's `payment_amount` and `info_flags` are unchanged (rolled back). With the default `EscalateAllHandler` the state is ESCALATED. |
| 7 | `…::test_no_adjudication_is_extraction_failed` | No row gives `last_error_code == EXTRACTION_FAILED` with detail reason `no_adjudication`. A `final` that fails schema validation gives `EXTRACTION_FAILED` with reason `final_invalid`. |
| 7 | `…::test_current_extraction_returns_cleaned_view` | `current_extraction(uow, item_id)` returns trimmed numbers with zero lines dropped. With no row it returns `None`. |
| 7 | `…::test_no_payer_name_in_detail_or_logs` | A sentinel payer name never appears in `last_error_detail`, the history payload or `caplog`. |
| 8 | `api/tests/stations/validate/test_no_llm_imports.py::test_validate_station_does_not_import_llm` | AST walk over every `.py` under `cashapp/stations/validate/` plus `cashapp/services/validation.py`: no `Import`/`ImportFrom` whose module is or starts with `cashapp.integrations.llm`, `anthropic` or `oci` (relative imports are resolved before comparing). |
| 8 | `…::test_validation_module_does_not_load_llm_transitively` | A subprocess (`sys.executable -I -c`) imports `cashapp.services.validation` and then asserts that no `cashapp.integrations.llm` or `anthropic` key is in `sys.modules`. |
| 9 | `api/tests/stations/validate/test_role.py::test_role_spec` | `ROLE == RoleSpec("validate", "consumer", build)`, with fields compared by name and kind and `ROLE.build is build`. `build(FakeContainer(...))` returns a `StageConsumer` wrapping a `ValidateRunner` with `stage == Stage.VALIDATE`. |

Every test runs on sqlite and in-memory fakes. No `atp` or `live` markers are needed.

## Assumptions and deviations

- **`notices` added to `ValidationReport`.** AC5 says the dropped zero lines are "listed as `ZERO_AMOUNT_LINE` issues", while AC7 says *any* error raises. Putting the per-line notices in `errors` would fail every item that has one zero line, so they go in a separate non-blocking `notices` tuple. Only the item-level all-zero case is an error.
- **Duplicates are reported in `duplicate_transaction_numbers`**, not as an `InfoFlag`. s02's `InfoFlag` has no duplicate member, and only s02 may define one. Duplicates are compared case-insensitively; adjustment lines are excluded, because a tariff line legitimately repeats an invoice number (reference doc §2).
- **The header-sum scope** is invoice-like lines only (`INVOICE`, `CREDIT_MEMO`, `UNKNOWN`). Bank fees, tariffs and discount lines are adjustments and are excluded. A credit memo counts as `-abs(amount)` whatever sign the reader gave it.
- **Invalid invoice numbers block the item** (`INVALID_INVOICE_NUMBER`). They are not dropped, so s18 can re-extract or normalise. An empty number is invalid on an invoice-like line and allowed on an adjustment line, which matches s08.
- **Zero header with no lines** is an item error, mirroring s02's `roll_up` ZERO_AMOUNT rule. A missing header with all lines zero is not an item error: the notices are recorded and s11/s15 see no payable lines.
- **The error severity order** (`VALIDATION_ERROR_PRECEDENCE`) is defined here because the story doesn't give one. Always-person comes first; after that it follows s02's payment failure precedence.
- **Missing or invalid adjudication raises `EXTRACTION_FAILED`.** The story doesn't cover it; this is the nearest typed code, and s18 retries the readers.
- **On error, nothing is written to the item** (flags, amount, date) because s03 rolls back the outcome transaction. The issues are visible in `LAST_ERROR_DETAIL`.
- **The ISO 4217 table is hand-written** in `cashapp/domain/iso4217.py`. Lockfiles are frozen after s01, and no currency library is pinned. It is a new file, so other stories (s11, s21) can reuse it.
- **`current_extraction` is added** so downstream stations can read the cleaned view without recomputing. `clean` doesn't depend on `today`, so the view is stable. Downstream stories coded against `latest_for` stay correct, because s15 rejects zero lines itself.
- **`today` is the UTC date** from `ctx.clock`. The date bounds are code constants, per the story assumption.
- **s18's `policy_check`** (PREPAYMENT/UNGROUNDED) is not called here. s18 isn't a dependency, so wiring it into validate belongs to s18.

## Risks

- **s09's ORM attribute names aren't pinned yet** (no s09 plan). The plan assumes `Adjudication.final` is a dict and that `AdjudicationRepository` lives at `cashapp.data.repositories.adjudication`. If they differ, the coder adapts two lines in the runner and the test row builder.
- **The ISO 4217 table can go stale** (new or retired codes). It is low impact: a false `INVALID_CURRENCY` goes to s18 or a person. It is easy to update.
- **The 400/60-day bounds** may reject legitimate backlog items (s35 reprocessing old remittances). They are constants for now; if s35 needs it, moving them to config is a later story.
- **Transitive LLM import:** if a shared module (for example `cashapp.domain.extraction`) ever starts importing `cashapp.integrations.llm`, AC8's subprocess test fails. That is the intended alarm.
