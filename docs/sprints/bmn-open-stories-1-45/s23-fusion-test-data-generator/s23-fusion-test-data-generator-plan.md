# Plan: s23-fusion-test-data-generator

Issue #23. Wave 4. Owns `cashapp/tools/testdata/` (`cashapp/` = `api/src/cashapp/`). No LLM calls, no
UI, no migration. Builds on s05 (`FusionClient.rest_post/rest_get/apply_receipt`, `FusionClientFactory`,
`FakeFusionClient`, `q_in`, `accounting_date_for`), s08 (`RemittanceExtraction`), s02 (`money`,
`LineStatus`, `ErrorCode`), s27 (`Settings`, `FusionPodSettings.testdata`).

## Standards followed

- CLAUDE.md *Working with BMN → Test data*: parameterised generator; `POST receivablesInvoices` →
  `completeTransaction` → `POST standardReceipts` with **no application child**; covers splits, short
  pays, INR rounding, duplicate amounts, ambiguous receipts (plus credit memo netting and
  already-applied, reference doc §7).
- CLAUDE.md *Fusion*: every Fusion call goes through the one `FusionClient` (no httpx here). Writes go
  through s05's `WriteGuard` (needs `fusion.write_enabled=true`) **and** this story's own
  pre-flight production refusal, which runs before a client is even built. Never a production pod.
  "Never guess a payload": every POST field name is a constant in `payloads.py` tagged
  `# UNVERIFIED:` and listed in s05's `CONTRACTS.md` convention (rows appended in our own
  `cashapp/tools/testdata/CONTRACTS.md`, not s05's file). The coder may confirm shapes read-only with
  `aix-greenlight` `fusion_rest_describe` (never `fusion_rest_write`).
- *Conventions*: money is `Decimal` via `to_money`/`MoneyStr` (amounts generated from integer cents
  with `random.Random(seed)`, never `float`); every amount carries its currency. No client or customer
  names: payer names are synthetic (`Synthetic Payer <seed>`).
- research.md: the fake is s05's `FakeFusionClient` (no third Fusion implementation). DRY: `q_in`,
  `accounting_date_for`, `to_money`, `LineStatus`, `ErrorCode` are imported, never re-implemented.
- `python-web-app:building-python-web-apps`: logic in plain modules (scenarios/generator/cleanup are
  pure or take the client as an argument); the CLI is a thin typer shell (typer is pinned by s01);
  settings loaded only in `cli.py`.
- pyright strict, ruff. Pydantic v2 frozen models for everything serialised (plans, manifests).

## Files to touch

All new and owned by this story unless marked.

| Path | Contents |
|---|---|
| `api/src/cashapp/tools/testdata/__init__.py` | re-exports the pinned public names below |
| `api/src/cashapp/tools/testdata/__main__.py` | `from .cli import app; app()` (enables `python -m cashapp.tools.testdata`) |
| `api/src/cashapp/tools/testdata/models.py` | `ScenarioName`, `ScenarioParams`, `PlannedTransaction`, `PlannedReceipt`, `PlannedApplication`, `ExpectedLine`, `Expected`, `ScenarioPlan`, `CreatedRecord`, `GeneratedData`, `TaggedRecord`, `CleanupReport` |
| `api/src/cashapp/tools/testdata/tagging.py` | `TAG_PATTERN`, `validate_tag`, `tagged_number`, `tag_marker`, `is_tagged` |
| `api/src/cashapp/tools/testdata/scenarios.py` | `Scenario` base, eight presets, `PRESETS`, `build_plan`, amount helpers |
| `api/src/cashapp/tools/testdata/payloads.py` | `invoice_payload`, `credit_memo_payload`, `receipt_payload`, path constants (all UNVERIFIED field names) |
| `api/src/cashapp/tools/testdata/safety.py` | `ProductionPodRefused`, `production_hosts`, `assert_non_production` |
| `api/src/cashapp/tools/testdata/generator.py` | `GenerationError`, `generate` |
| `api/src/cashapp/tools/testdata/cleanup.py` | `cleanup`, `render_cleanup_steps`, `load_manifests` |
| `api/src/cashapp/tools/testdata/fixtures.py` | `FixturePaths`, `render_remittance_csv`, `plan_to_fake_json`, `write_fixtures`, `write_manifest` |
| `api/src/cashapp/tools/testdata/cli.py` | typer `app`, `run` command |
| `api/src/cashapp/tools/testdata/CONTRACTS.md` | one row per POST path/field: `UNVERIFIED` / `CONFIRMED <date> <pod>` |
| `api/src/cashapp/integrations/fusion/fake.py` (**s05-owned, small edit, only if needed**) | add `receivablesCreditMemos/{id}/action/completeTransaction` to the fake's `rest_post` path table if s05 did not ship it (s05 pinned only the invoice complete action). No other change. |
| `api/tests/unit/testdata/test_testdata_scenarios.py` | AC1 |
| `api/tests/unit/testdata/test_testdata_generator.py` | AC2 |
| `api/tests/unit/testdata/test_testdata_tagging.py` | AC3 |
| `api/tests/unit/testdata/test_testdata_safety.py` | AC4 |
| `api/tests/unit/testdata/test_testdata_cli.py` | AC5 |
| `api/tests/live/testdata/test_testdata_live.py` | AC6 (`@pytest.mark.live`) |

No `pyproject.toml`/lockfile edit (typer pinned by s01). No `[project.scripts]` entry (the AC uses
`python -m`). No settings edit: `FusionTestDataSettings` (business_unit, transaction_type,
receipt_method, bank_account) is already in s27's pinned model. Test basenames prefixed
`test_testdata_`; no `__init__.py` in test dirs unless s01's layout uses them.

## Design

### Tagging (`tagging.py`)

- `TAG_PATTERN = r"^[A-Z0-9]{1,8}$"`; `validate_tag` upper-cases and raises `ValueError` otherwise
  (keeps numbers short: Fusion transaction/receipt numbers have length limits, see Risks).
- `tagged_number(tag, kind, n)` → `CATD-<tag>-<kind>-<n:03d>`, kind ∈ `INV`, `CM`, `RCPT`
  (e.g. `CATD-T001-INV-001`).
- `tag_marker(tag)` → `cashapp-testdata:<tag>`; written into the `Comments` field of every invoice,
  credit memo and receipt. `is_tagged(number, comments, tag)` requires **both** prefix and marker.

### Scenarios (`scenarios.py`)

`ScenarioParams{currency="USD", lines=3 (1..50), seed=0, as_of: date}`. `as_of` is the payment date
(CLI default: today UTC; tests pass a fixed date). Amounts come from `random.Random(seed)` as integer
cents in [100.00, 9 999.99] → `to_money`; same params → identical plan (deterministic). Each preset
subclasses `Scenario` and implements only `build(params, tag, customer_account) -> ScenarioPlan`; the
base class fills the remittance (`_remittance(...)`) and validates the plan (`_check`: numbers unique,
all tagged, currencies consistent, expected numbers exist in the plan).

| Preset | Fusion data | Remittance | Expected |
|---|---|---|---|
| `one_to_one` | 1 invoice A; 1 receipt = A, date `as_of` | 1 line A | receipt R1; line `allocation-applied` A |
| `split_payment` | `lines` invoices; 1 receipt = Σ | `lines` lines | R1; every line applied full |
| `short_pay` | `lines` invoices; last line paid 95% (rounded half-up); receipt = Σ paid | last line `amount_paid` < `gross_amount`, `deduction` = difference | R1; last line `allocation-applied-short-pay` at paid amount, others `allocation-applied` |
| `inr_rounding` | currency forced `INR`; invoices with non-zero paise; receipt = Σ rounded half-up to whole rupees (residual ≤ 0.49, ≠ 0) | lines at paise amounts, `payment_amount` = whole-rupee total | R1; lines applied at invoice amounts; `expected.residual` = receipt − Σ |
| `duplicate_amounts` | `lines` invoices; R1 = Σ dated `as_of`, refs `[remittance_reference]`; R2 = Σ dated `as_of − 20 days`, refs `[other]` | reference matches R1 | R1 (the in-window, reference-matching one) |
| `ambiguous_receipts` | two receipts = Σ, both dated within ±2 days of `as_of`, no references | no reference | `receipt_number=None`, `error_code=RECEIPT_AMBIGUOUS`, lines `allocation-no-receipt-match`, applied 0 |
| `credit_memo_netting` | `max(lines,2)` invoices + 1 credit memo (negative, ≤ 40% of smallest invoice); receipt = Σ invoices + CM | CM line kind `CREDIT_MEMO` with negative amount | R1; CM line first in `expected.lines`, applied at its negative amount; invoices applied full |
| `already_applied` | as `split_payment` plus `pre_applications` applying every invoice fully to R1 | same | R1; every line `allocation-previously-applied`, applied 0 |

`remittance` is a real `RemittanceExtraction` (s08): `payer_name`, `remittance_reference`
(`CATD-<tag>-REF`), `payment_amount`, `currency_raw` = currency code (never a bare `$`),
`currency`, `currency_ambiguous=False`, `dates=[DateCandidate(kind=PAYMENT)]`, `payment_date`,
`lines` (`transaction_number` as `str`), every `Extracted` with `source=SourceLocation(part_no=1)`
and `confidence=1.0`. Credit memos are negative throughout (Fusion convention, s05).

### Generator (`generator.py`)

`generate(plan, fusion, *, tag, defaults, bill_to_site=None)`:
1. `validate_tag(tag)`; `tag != plan.tag` → `ValueError` (no call made).
2. Invoices, in plan order: `rest_post("receivablesInvoices", invoice_payload(...))` → id from response
   `CustomerTransactionId`; then `rest_post(f"receivablesInvoices/{id}/action/completeTransaction", {})`.
3. Credit memos: `rest_post("receivablesCreditMemos", credit_memo_payload(...))` then
   `rest_post(f"receivablesCreditMemos/{id}/action/completeTransaction", {})` (UNVERIFIED that a
   separate complete action exists; if the live probe shows the POST can create it complete, the
   coder drops step 2 for credit memos and records it in CONTRACTS.md).
4. Receipts: `rest_post("standardReceipts", receipt_payload(...))`, body has **no**
   `receiptApplications`/application child; remittance references, if any, as the nested
   `remittanceReferences` child (UNVERIFIED). Id from `StandardReceiptId`.
5. `pre_applications` (only `already_applied`): `fusion.apply_receipt(ApplyRequest(receipt_id,
   customer_trx_id, amount_applied, receipt_currency, application_date=as_of,
   accounting_date=accounting_date_for(as_of, today)))`; `result.ok is False` → `GenerationError`.
6. Any `FusionError` mid-way → `GenerationError(partial=GeneratedData so far)`; the CLI still writes the
   manifest so `cleanup` can find what was created. No retry, no rollback (no automatic deletes).

Payloads (`payloads.py`, all UNVERIFIED): invoice `{TransactionNumber, BusinessUnit, TransactionSource:
"Manual"*, TransactionType, TransactionDate, AccountingDate, BillToCustomerNumber, BillToSite*,
InvoiceCurrencyCode, PaymentTerms*, Comments, receivablesInvoiceLines: [{LineNumber: 1, Description,
Quantity: 1, UnitSellingPrice: "<amount>"}]}`; credit memo the same shape on
`receivablesCreditMemos` with `CurrencyCode*` and a negative `UnitSellingPrice`; receipt
`{ReceiptNumber, BusinessUnit, ReceiptMethod, ReceiptDate, AccountingDate, Amount, Currency,
CustomerAccountNumber, RemittanceBankAccountNumber*, Comments}`. Money serialised as `f"{d:.2f}"`
strings. `BusinessUnit`/`TransactionType`/`ReceiptMethod`/bank account come from
`pod.testdata` (s27 `FusionTestDataSettings`), never code.

### Safety (`safety.py`)

`assert_non_production(pod_name, pod, *, all_pods, extra_production_hosts=())` raises
`ProductionPodRefused` when `pod.is_production`, or when the host of `pod.base_url` (lower-cased,
port-less) equals the host of any pod in `all_pods` with `is_production=True`, or any of
`extra_production_hosts` (CLI `--production-host`, repeatable). Also raises when
`pod.testdata is None` for a non-dry run (a pod without a testdata block was not set up for this).
The CLI calls it **before** `FusionClientFactory.for_pod` is called, so no client exists and no HTTP is
possible; `generate` and `cleanup` also accept an optional `guard: Callable[[], None]` hook so library
callers cannot skip it (the CLI passes the same check). s05's `WriteGuard` stays as the second rail.

### Cleanup (`cleanup.py`)

`cleanup(tag, fusion, *, manifest_dir)` reads every `manifest-*.json` under `manifest_dir/<tag>/`,
then **reads only**: `rest_get("receivablesInvoices", {"q": q_in("TransactionNumber", nums), "fields":
...})`, same for `receivablesCreditMemos` and `standardReceipts` (`ReceiptNumber`). Records keep only
those passing `is_tagged`. Returns `CleanupReport`. `render_cleanup_steps(report)` returns plain text:
per receipt "Receivables > Manage Receipts > <number> > Reverse (reason: test data)" and unapply any
application first; per invoice/credit memo "Manage Transactions > <number> > Incomplete, then Delete,
or Credit if posted". The tool never calls a delete/void/reverse. A manifest number that Fusion no
longer returns is listed as "not found".

### Fixtures (`fixtures.py`) and CLI (`cli.py`)

`write_fixtures(plan, out_dir, *, drop_folder=None)` writes under `out_dir/<tag>/`:
- `<scenario>.plan.json` — the full `ScenarioPlan` (`model_dump_json(indent=2)`).
- `<scenario>.remittance.csv` — a remittance-advice CSV the s06 `FolderSource` + s34 normaliser
  ingest (`text/csv`): a header block (`Payer`, `Remittance reference`, `Payment date`,
  `Payment amount`, `Currency`) then a table `Invoice number,Gross amount,Discount,Deduction,Amount paid`.
- `<scenario>.gold.json` — `{"schema": "cashapp-testdata-gold@1", "artifact": "<scenario>.remittance.csv",
  "extraction": <RemittanceExtraction JSON>, "expected": <Expected JSON>}` (for s24's gold set).
- `<scenario>.fusion.json` — `plan_to_fake_json(plan)`: the post-generation Fusion state in s05's pinned
  `FakeFusionClient.from_json` shape (customer, transactions with deterministic ids from 100001,
  receipts from 500001, `pre_applications` as applications with balances adjusted).
- `drop_folder` given → copies **only** the CSV there (so FolderSource never ingests the JSON).

`run` command options: `--pod` (default `settings.fusion.default_pod`), `--scenario`, `--lines 3`,
`--currency USD`, `--seed 0`, `--as-of` (default today UTC), `--tag` (required), `--customer`
(required unless `--dry-run`; dry-run default `CATD-<tag>-CUST`), `--bill-to-site`, `--out`
(default `tests/fixtures/testdata`, relative to `api/`), `--drop-folder`, `--production-host`
(repeatable), `--dry-run`, `--cleanup`.
- `--dry-run`: builds the plan, prints `plan.model_dump_json(indent=2)` to stdout, writes fixtures,
  exits 0. **Loads no settings and builds no client.**
- normal: `load_settings()` → `assert_non_production` → `FusionClientFactory(settings).for_pod(pod)` →
  `generate` → `write_manifest` → `write_fixtures` → prints a summary (numbers and ids only); `aclose()`
  in `finally`. `ProductionPodRefused` / `GenerationError` → stderr message, exit code 2 / 1.
- `--cleanup`: same guard, then `cleanup` and prints `render_cleanup_steps`.

## Interfaces provided (pinned)

```python
# cashapp/tools/testdata/models.py   (Pydantic v2, model_config = ConfigDict(frozen=True, extra="forbid"))
class ScenarioName(StrEnum):
    ONE_TO_ONE = "one_to_one"; SPLIT_PAYMENT = "split_payment"; SHORT_PAY = "short_pay"
    INR_ROUNDING = "inr_rounding"; DUPLICATE_AMOUNTS = "duplicate_amounts"
    AMBIGUOUS_RECEIPTS = "ambiguous_receipts"; CREDIT_MEMO_NETTING = "credit_memo_netting"
    ALREADY_APPLIED = "already_applied"

class ScenarioParams(BaseModel):
    currency: CurrencyCode = "USD"; lines: int = Field(3, ge=1, le=50); seed: int = 0; as_of: date

class PlannedTransaction(BaseModel):
    number: str; amount: MoneyStr            # credit memos negative
    currency: CurrencyCode; terms: str | None = None; transaction_date: date

class PlannedReceipt(BaseModel):
    number: str; amount: MoneyStr; currency: CurrencyCode; receipt_date: date; references: list[str] = []

class PlannedApplication(BaseModel):
    receipt_number: str; transaction_number: str; amount: MoneyStr    # signed

class ExpectedLine(BaseModel):
    number: str; line_status: LineStatus; applied_amount: MoneyStr

class Expected(BaseModel):
    receipt_number: str | None; lines: list[ExpectedLine]
    error_code: ErrorCode | None = None; residual: MoneyStr = Decimal("0.00")

class ScenarioPlan(BaseModel):
    scenario: ScenarioName; tag: str; params: ScenarioParams; customer_account: str
    invoices: list[PlannedTransaction]; credit_memos: list[PlannedTransaction]
    receipts: list[PlannedReceipt]; pre_applications: list[PlannedApplication] = []
    remittance: RemittanceExtraction; expected: Expected

class CreatedRecord(BaseModel):
    kind: Literal["INVOICE", "CREDIT_MEMO", "RECEIPT", "APPLICATION"]; number: str; fusion_id: int | None

class GeneratedData(BaseModel):
    tag: str; scenario: ScenarioName; pod_name: str; created_at: datetime
    records: list[CreatedRecord]
    def ids_by_number(self) -> dict[str, int]

class TaggedRecord(BaseModel):
    kind: Literal["INVOICE", "CREDIT_MEMO", "RECEIPT"]; number: str; fusion_id: int | None
    status: str | None; found: bool

class CleanupReport(BaseModel):
    tag: str; pod_name: str; records: list[TaggedRecord]

# cashapp/tools/testdata/tagging.py
TAG_PATTERN: Final[str]
def validate_tag(tag: str) -> str                         # upper-cased; ValueError if not ^[A-Z0-9]{1,8}$
def tagged_number(tag: str, kind: Literal["INV", "CM", "RCPT"], n: int) -> str   # CATD-<tag>-<kind>-<nnn>
def tag_marker(tag: str) -> str                            # "cashapp-testdata:<tag>"
def is_tagged(number: str, comments: str | None, tag: str) -> bool

# cashapp/tools/testdata/scenarios.py
class Scenario(ABC):
    name: ClassVar[ScenarioName]
    def plan(self, params: ScenarioParams, *, tag: str, customer_account: str) -> ScenarioPlan   # template: build + remittance + _check
    @abstractmethod
    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft
PRESETS: Mapping[ScenarioName, Scenario]
def build_plan(name: ScenarioName | str, params: ScenarioParams, *, tag: str, customer_account: str) -> ScenarioPlan

# cashapp/tools/testdata/safety.py
class ProductionPodRefused(Exception): pod_name: str; reason: str
def production_hosts(all_pods: Mapping[str, FusionPodSettings], extra: Iterable[str] = ()) -> frozenset[str]
def assert_non_production(pod_name: str, pod: FusionPodSettings, *, all_pods: Mapping[str, FusionPodSettings],
                          extra_production_hosts: Iterable[str] = (), require_testdata: bool = True) -> None

# cashapp/tools/testdata/generator.py
class GenerationError(Exception): partial: GeneratedData; cause: Exception
async def generate(plan: ScenarioPlan, fusion: FusionClient, *, tag: str, defaults: FusionTestDataSettings,
                   bill_to_site: str | None = None, guard: Callable[[], None] | None = None,
                   today: date | None = None, clock: Clock = SystemClock()) -> GeneratedData

# cashapp/tools/testdata/cleanup.py
def load_manifests(manifest_dir: Path, tag: str) -> list[GeneratedData]
async def cleanup(tag: str, fusion: FusionClient, *, manifest_dir: Path,
                  guard: Callable[[], None] | None = None) -> CleanupReport      # reads only
def render_cleanup_steps(report: CleanupReport) -> str

# cashapp/tools/testdata/fixtures.py
@dataclass(frozen=True, slots=True)
class FixturePaths: plan: Path; remittance_csv: Path; gold: Path; fusion: Path; dropped_csv: Path | None
def render_remittance_csv(plan: ScenarioPlan) -> str
def plan_to_fake_json(plan: ScenarioPlan) -> dict[str, Any]     # s05 FakeFusionClient.from_json shape
def write_fixtures(plan: ScenarioPlan, out_dir: Path, *, drop_folder: Path | None = None) -> FixturePaths
def write_manifest(data: GeneratedData, out_dir: Path) -> Path   # out_dir/<tag>/manifest-<scenario>-<utc>.json

# cashapp/tools/testdata/cli.py
app: typer.Typer
```

Consumers: s24 (`build_plan`, `PRESETS`, `ScenarioPlan.expected`, `plan_to_fake_json`, gold JSON
shape `cashapp-testdata-gold@1`), s05 live write probes (s23-tagged data), s32/s39 live checks
(`generate` for disposable data).

## Migrations

None.

## TEST PLAN (written and run only at step 5)

All unit tests use s05's `FakeFusionClient` (`guard=WriteGuard.allow_all()` unless stated), s27's
`make_settings`, a fixed `as_of=date(2026, 1, 15)` and `tmp_path`.

| AC | Test (file::name) |
|---|---|
| 1 | `test_testdata_scenarios.py::test_every_preset_builds_a_valid_plan` (parametrised over all 8 `ScenarioName`s: numbers unique and tagged, `remittance` validates as `RemittanceExtraction`, every `expected.lines[].number` exists in the plan, money is `Decimal` with 2 dp) |
| 1 | `…::test_plans_are_deterministic_for_same_seed_and_differ_for_other_seed` |
| 1 | `…::test_parameters_line_count_and_currency_are_honoured` (`split_payment` lines=5 USD/EUR; `lines=0` and `51` rejected) |
| 1 | `…::test_split_payment_receipt_equals_sum_of_invoices` |
| 1 | `…::test_short_pay_last_line_short_with_deduction_and_expected_short_pay_status` |
| 1 | `…::test_inr_rounding_receipt_is_whole_rupee_and_residual_within_0_49` (currency forced INR; residual ≠ 0) |
| 1 | `…::test_duplicate_amounts_two_receipts_same_amount_different_dates_and_refs_expects_referenced_one` |
| 1 | `…::test_ambiguous_receipts_expect_receipt_ambiguous_and_no_receipt_match_lines` |
| 1 | `…::test_credit_memo_netting_negative_cm_listed_first_and_receipt_nets` |
| 1 | `…::test_already_applied_has_pre_applications_and_previously_applied_expectations` |
| 1 | `…::test_remittance_transaction_numbers_are_strings_and_currency_not_ambiguous` |
| 2 | `test_testdata_generator.py::test_generate_posts_invoice_then_complete_then_receipt_in_order` (`fake.calls` order; `posted("receivablesInvoices")`, `…/action/completeTransaction`, `posted("standardReceipts")`) |
| 2 | `…::test_receipt_payload_has_no_application_child` (no `receiptApplications` key; fake receipt `unapplied_amount == amount`) |
| 2 | `…::test_credit_memo_created_on_credit_memo_resource_and_completed` |
| 2 | `…::test_payload_uses_pod_testdata_defaults` (BU, transaction type, receipt method, bank account from `FusionTestDataSettings`) |
| 2 | `…::test_generated_data_returns_ids_and_numbers` (`ids_by_number()` covers every planned record) |
| 2 | `…::test_already_applied_applies_via_apply_receipt_with_accounting_date_helper` |
| 2 | `…::test_failure_midway_raises_generation_error_with_partial_records` (`fail_next("rest_post", FusionError(...))` on the receipt POST; `partial.records` holds the invoices) |
| 2 | `…::test_tag_mismatch_raises_before_any_call` |
| 3 | `test_testdata_tagging.py::test_numbers_prefixed_and_comments_carry_marker` (every POST body: number starts `CATD-T001-`, `Comments` contains `cashapp-testdata:T001`) |
| 3 | `…::test_validate_tag_rejects_bad_tags` (`""`, `t-1`, `TOOLONGTAG`, lower-case upper-cased) |
| 3 | `…::test_cleanup_lists_tagged_records_and_reads_only` (after `generate` + `write_manifest`; `fake.calls` contain only `rest_get`; untagged look-alike excluded; missing number reported `found=False`) |
| 3 | `…::test_render_cleanup_steps_mentions_every_record_and_no_delete_call_made` |
| 4 | `test_testdata_safety.py::test_refuses_is_production_pod_before_any_call` (CLI path with a monkeypatched `FusionClientFactory.for_pod` that fails the test if called; exit code 2) |
| 4 | `…::test_refuses_pod_whose_host_matches_a_production_pod` (dev pod pointing at prod host, case/port/trailing slash variations) |
| 4 | `…::test_refuses_extra_production_host_option` |
| 4 | `…::test_refuses_pod_without_testdata_block` |
| 4 | `…::test_generate_guard_hook_runs_before_any_call` (`guard` raises → `fake.calls == []`) |
| 4 | `…::test_fusion_write_guard_still_applies` (`WriteGuard(write_enabled=False, ...)` on the fake → `FusionError(FUSION_WRITE_DISABLED)` from `generate`) |
| 5 | `test_testdata_cli.py::test_dry_run_prints_plan_json_without_settings_or_fusion` (`typer.testing.CliRunner`; stdout parses as `ScenarioPlan`; `load_settings` and `FusionClientFactory` monkeypatched to fail if touched) |
| 5 | `…::test_dry_run_writes_csv_gold_plan_and_fusion_fixtures` (`gold.json` has `schema == "cashapp-testdata-gold@1"` and a valid `RemittanceExtraction`; `fusion.json` loads with `FakeFusionClient.from_json` and its receipts/transactions equal the plan) |
| 5 | `…::test_remittance_csv_is_accepted_by_normaliser` (s34 `normalise(IncomingArtifact(... text/csv))` returns `Normalised` with one TABLE part containing every transaction number) |
| 5 | `…::test_drop_folder_receives_only_the_csv` |
| 5 | `…::test_module_entry_point_runs` (`subprocess.run([sys.executable, "-m", "cashapp.tools.testdata", "--scenario", "one_to_one", "--tag", "T001", "--dry-run", "--out", tmp])` exit 0) |
| 5 | `…::test_full_run_against_fake_writes_manifest` (factory monkeypatched to return a `FakeFusionClient`; manifest written; `aclose` called) |
| 6 | `api/tests/live/testdata/test_testdata_live.py::test_generate_one_to_one_on_dev_pod_and_read_back` (`@pytest.mark.live`; skipped unless settings load, `CASHAPP_TESTDATA_LIVE_POD` names a pod with `is_production=False` and a `testdata` block, `fusion.write_enabled` is true and `CASHAPP_TESTDATA_LIVE_CUSTOMER` is set; tag `L<yyMMdd><nn>`; reads back via `find_transactions` and `get_receipt`: amounts, currency, `unapplied_amount == amount`, `Comments` marker; then prints cleanup steps) |

## Risks

- **Payload field names are guesses** (`TransactionSource`, `BillToSite`, `PaymentTerms`, line child
  name `receivablesInvoiceLines`, `UnitSellingPrice`, credit memo currency field, receipt
  `RemittanceBankAccountNumber`, nested `remittanceReferences`, the credit memo complete action).
  All live in `payloads.py` constants and `CONTRACTS.md`; the coder confirms read-only with
  `fusion_rest_describe` before the live test. The fake accepts whatever s05 pinned, so a rename
  touches `payloads.py` and possibly s05's fake mapping only.
- **Fake/real drift on POST bodies.** s05's fake builds ledger rows from POSTed bodies "using the same
  field names"; the amount source (header vs lines) is not pinned by s05. The s23 coder aligns with
  s05's implementation and, if the fake cannot derive an amount from line bodies, adds that one
  mapping to `fake.py` (logged as a cross-story edit, the same as the credit memo complete path).
- **Number length.** `CATD-<8>-RCPT-999` is 22 characters; Fusion transaction/receipt number limits are
  UNVERIFIED (expected ≥ 30). Tag is capped at 8 to keep margin.
- **Live writes.** Need `fusion.write_enabled=true` on a non-production pod with a `testdata` block and
  a real test customer; nothing runs live without Jonathan's credentials. Created records are not
  deleted automatically; `cleanup` prints the manual steps.
- **Already-applied preset** uses the SOAP apply (s05 `apply_receipt`), so it inherits every UNVERIFIED
  SOAP detail; the other seven presets need only REST.
- **INR on the dev pod** needs an INR-enabled business unit/receipt method; if absent, the live run of
  `inr_rounding` fails at the POST and reports it (unit coverage is unaffected).

## Assumptions / deviations

- `generate` takes `defaults: FusionTestDataSettings` (and optional `bill_to_site`, `guard`, `today`,
  `clock`) beyond the AC's `generate(plan, fusion, *, tag)`: BU, transaction type, receipt method and
  bank account are pod settings (story assumption) and must reach the payloads.
- The customer account is a CLI argument (`--customer`), not a setting: s27's `FusionTestDataSettings`
  has no customer field and is not edited here.
- "Configured production host" = the host of any pod in `fusion.pods` with `is_production=True`, plus
  `--production-host` values. No new setting (s27's `Settings` is `extra="forbid"`).
- `cleanup` lists by the manifests `generate` wrote (exact `in (...)` queries), not a `LIKE` search:
  s05's fake evaluates only `=`/`in`, and LIKE support on the tenant is UNVERIFIED. It still filters on
  both prefix and marker, so a manifest can never point cleanup at untagged data.
- The fixture is a CSV (FolderSource + s34 accept `text/csv`); `.gold.json` and `.fusion.json` sit
  beside it for s24. Only the CSV is copied to a drop folder.
- `ScenarioPlan` gains `scenario`, `tag`, `params`, `pre_applications`; `Expected` gains `error_code`
  and `residual` (needed for `ambiguous_receipts`, `already_applied`, `inr_rounding`).
- Credit memo amounts are negative in plans and payloads (Fusion convention, s05).
- Expected statuses use s02's `LineStatus` values (`allocation-applied`, `allocation-applied-short-pay`,
  `allocation-previously-applied`, `allocation-no-receipt-match`); s24 compares, this story does not
  run the matcher.
