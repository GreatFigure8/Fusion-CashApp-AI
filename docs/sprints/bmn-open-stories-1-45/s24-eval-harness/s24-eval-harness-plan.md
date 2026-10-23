# s24-eval-harness: plan

Issue #24. Wave 5. Python only: no web files, no UI, no migration. `cashapp/` means `api/src/cashapp/`.

## Standards followed

- **`python-llm-features:building-llm-backed-features`:**
  - Evaluation is its own deliberate job. It is never run by CI, and no live call happens in the default pytest run (s01 `addopts` deselects `live`).
  - Tests cover the scorer and report logic with canned outcomes (`ReplayLlmClient` recordings, `FakeFusionClient`), so they stay deterministic.
  - Raw per-case outcomes are persisted alongside the aggregates (`report.json` `per_case`, and `outputs/` for live runs).
  - `--runs N` repeats each extraction case, because one stochastic pass measures little.
  - The gold set has negative cases: a field expected to be absent and a `$` that must not be resolved.
  - **Fail closed on an empty selection.** If a selected suite finds zero cases (no gold files, no prior fixtures), it is reported as `status: "not_evaluated"` with the reason, and the exit code is 1. It is never a clean 100%.
  - No field over-claims. "Agreement with AR labels" is named agreement, not accuracy, because the prior outcomes came from a build with known defects.
- **`python-web-app:building-python-web-apps` (layering):**
  - The harness is a tool in the business layer. It calls services and station builders and never imports FastAPI.
  - SQLAlchemy appears only through s02's `UnitOfWork` and models in the autofix suite (in-memory SQLite, see Assumptions).
  - Pydantic v2 models define the report contract. Money is serialized as strings.
- **CLAUDE.md:**
  - Money is `Decimal` and is compared with s02's `money_eq` (≤ 0.005).
  - Invoice numbers are strings, and suffixes are significant (`2598014` ≠ `2598014-1`).
  - No model role changes: the readers, adjudicator and models come from config (`models.*`), changed only by `--config` overrides for an experiment.
  - Zero data retention is inherited from s08's clients. The harness builds no SDK client of its own.
  - No client names: the gold set is synthetic, and the s43 fixtures are anonymised. A test runs s43's `scan_for_identifiers` over `api/evals/`.
  - Model output is never logged. Reports are written only to the local, gitignored `api/evals/reports/`.
- **DRY: everything is reused, and nothing in the harness is a second copy:**

  | Need | Reused from |
  |---|---|
  | Content loading | s08 `load_content_parts` + `fit_parts` |
  | Reader requests | s08 `build_reader_request` |
  | Adjudicator request and result | s09 `build_adjudicator_request`, `AdjudicatorDecision`, `AdjudicationResult.from_decision`, `single_reader_result`, `check_grounding` |
  | Customer resolution | s11 `resolve_customer` |
  | Receipt scoring | s13 `score_candidates` |
  | Line planning | s15 `plan_lines` |
  | Auto-fix decisions | s18 engine through the `FailureHandler.handle` entry point |
  | Usage metering | s36 `MeteredLlmClient` + `PRICES`/cost function |
  | Label-to-decision mapping | s43's mapping |
  | Name normalisation | s37 normalisers |
  | Money | s02 `money_eq` / `to_money` |

## Files to touch

All files are new and owned by this story: `cashapp/evals/`, `api/evals/` and `api/tests/evals/`. No existing file is edited: not `pyproject.toml`, not the lockfile, not the root `.gitignore`, not `main.py`.

| Path | Content |
|---|---|
| `cashapp/evals/__init__.py` | re-exports `run_evals`, `EvalOptions`, `EvalReport` |
| `cashapp/evals/__main__.py` | `from cashapp.evals.cli import app; app()` |
| `cashapp/evals/cli.py` | typer `app` with the `run` command (flags below); exit codes 0/1/2 |
| `cashapp/evals/options.py` | `EvalOptions`, `Suite`, `default_paths()` (api root from the package location) |
| `cashapp/evals/models.py` | Pydantic report schema (pinned below) |
| `cashapp/evals/runner.py` | `run_evals(options, *, llm_factory) -> EvalReport`: spend guard, config snapshot, suite dispatch, cost summary |
| `cashapp/evals/config.py` | `StaticConfigStore` (registry defaults plus `--config` JSON overrides validated through s28 `validate_value`), `eval_snapshot(overrides) -> ConfigSnapshot` |
| `cashapp/evals/usage.py` | `EvalUsageRecorder` (s36 `UsageRecorder` in memory), `meter_clients(clients, recorder) -> LlmClients`, `summarise_cost(recorder, mode) -> CostSummary` |
| `cashapp/evals/gold.py` | `GoldCase`, `GoldExpected`, `GoldLine`, `load_gold(dir) -> list[GoldCase]` |
| `cashapp/evals/prior.py` | `PriorMessage`, `LabelledFailure`, `PriorFixtures`, `load_prior(dir) -> PriorFixtures` (s43 format) |
| `cashapp/evals/scoring.py` | pure functions: `normalise_ref`, `score_fields`, `score_lines`, `aggregate_variant`, `ConfusionCounter` |
| `cashapp/evals/report.py` | `write_report(report, out_dir)`, `render_markdown(report) -> str` |
| `cashapp/evals/suites/__init__.py` | empty |
| `cashapp/evals/suites/extraction.py` | `run_extraction_suite(cases, clients, config, *, runs, outputs_dir) -> ExtractionSuiteReport` |
| `cashapp/evals/suites/matching.py` | `replay_message(...)`, `run_matching_suite(prior, config, *, limit) -> MatchingSuiteReport` |
| `cashapp/evals/suites/autofix.py` | `run_autofix_suite(prior, config, *, limit) -> AutofixSuiteReport` |
| `api/evals/README.md` | how to run, cost warning, replay versus live, how to promote live outputs into recordings, gold-file format |
| `api/evals/gold/g01_credit_memo_suffix.json` … `g06_inr_whole_rupee.json` | the gold set (AC6, below) |
| `api/evals/artifacts/g01_credit_memo_suffix.txt` … (`.txt` / `.csv`) | synthetic remittance artifacts the gold files reference |
| `api/evals/recordings/<case>.<purpose>.json` | s08 Recording JSON for `extract.reader_a`, `extract.reader_b` and `adjudicate.adjudicator` per gold case. Synthetic, `verified_against_live: false`, with deliberate reader mistakes so the metrics aren't trivially 100%. |
| `api/evals/reports/.gitignore` | `*` and `!.gitignore` (reports are never committed) |
| tests in the TEST PLAN | written in step 5 only |

## Design

### CLI

```
uv run python -m cashapp.evals run --suite extraction|matching|autofix|all
    [--limit N] [--replay] [--runs N=1] [--confirm-spend]
    [--out DIR]            # default api/evals/reports/<UTC YYYYMMDDTHHMMSSZ>/
    [--gold DIR]           # default api/evals/gold
    [--prior DIR]          # default api/tests/fixtures/prior (s43)
    [--recordings DIR]     # default api/evals/recordings
    [--config FILE]        # JSON {config_key: value} overrides, e.g. {"models.reader_a": {...}, "matching.tolerances": {...}}
```

**Exit codes:**
- 0: report written.
- 1: a selected suite was `not_evaluated`, or the run failed. A partial report is still written when possible.
- 2: bad arguments, or the spend guard refused.

**Default paths** resolve against the api project root (`Path(cashapp.__file__).parents[2]`), so the command works from `api/` or from the repo root. Paths given by the user resolve against the current directory.

### Spend guard (AC5)

`needs_models = Suite.EXTRACTION in suites and not replay`. If that's true and `--confirm-spend` is absent:
- print `refusing: a live extraction run calls Opus x2 + Cohere per case (N cases x runs); re-run with --confirm-spend or --replay`
- exit 2

This happens **before** settings are loaded or any client is built. `llm_factory` is never called. The matching and autofix suites make no model calls and never need the flag.

### LLM clients

- **Replay:** every role is `ReplayLlmClient(recordings_dir=...)`, keyed by `(purpose, parts_digest)`.
- **Live:** `build_llm_clients(await aload_settings(), snapshot)` (s08 + s27), then `.with_models(snapshot.models())`.
- **Both:** the clients are wrapped by `meter_clients`, which wraps each role in s36's `MeteredLlmClient(inner, role, recorder=EvalUsageRecorder())`. Every call, success or failure, lands in the in-memory recorder; nothing goes to the database.

### Extraction suite (AC2)

For each `GoldCase` (the first `--limit`), and for each run of `--runs`:

1. **Load the artifact.** Build parts with `load_content_parts([ArtifactPartRef(part_no=1, kind=<by extension>, media_type, object_key=<relative name>)], LocalFolderObjectStore(artifacts_dir))`, then `fit_parts`. This is the same loader and limiter `ExtractRunner` uses.
   - The extension sets the kind: `.txt`→TEXT, `.csv`→TABLE, `.pdf`→PDF, `.png`/`.jpg`→IMAGE, `.docx`→DOCX.
2. **Run both readers.** `role_a/role_b = config.models().reader_a/reader_b`. Build `build_reader_request(parts, role=…, effort=role.effort, slot=ReaderSlot.A|B, work_item_id=0)` and call `clients.reader_a|reader_b.parse(req, RemittanceExtraction)` concurrently. Each call is wrapped in `asyncio.wait_for(role.timeout_s)`. A refusal, an `LlmError` or a timeout makes that reader failed for the case, and the code is recorded.
3. **Adjudicate.**
   - Both readers OK: `clients.adjudicator.parse(build_adjudicator_request(a, b, role=…, work_item_id=0), AdjudicatorDecision)`, then `AdjudicationResult.from_decision`. Grounding violations are recorded from `check_grounding(result, a, b)`.
   - Exactly one OK: `single_reader_result(reading, slot)` with no LLM call (the s09 rule), and `missing_reader` is recorded.
   - Neither OK: the adjudicated variant failed.
4. **Score three variants** against `GoldExpected`: `reader_a`, `reader_b`, `adjudicated`.
   - **Header fields** (scored only when present in the gold file; an explicit `null` means "expected absent", which is a negative case):

     | Field | Comparison |
     |---|---|
     | `payer_name` | s37 `normalise_payer_name` equality |
     | `payer_bank_account` | s37 `normalise_bank_account` equality |
     | `remittance_reference` | `normalise_ref` equality (strip, upper-case, collapse inner whitespace; suffixes kept) |
     | `payment_amount` | `money_eq` |
     | `currency` | exact code, or `None` |
     | `currency_ambiguous` | bool equality |
     | `payment_date` | date equality |
     | `dates` | set equality of values |
     | `bank_fees` | multiset of amounts compared with `money_eq` |

   - **Lines:** precision, recall and F1 on the multiset of `normalise_ref(transaction_number)` for lines of kind INVOICE, CREDIT_MEMO or UNKNOWN with a non-empty number. Line-amount accuracy covers matched lines (`money_eq`, or both `None`). Line-kind accuracy covers matched lines. Fee, tariff and discount lines are scored separately as `fee_lines` (count equality and amount multiset).
   - **A failed variant** scores every gold field wrong and recall 0. It counts as a miss, so a model that refuses can't look accurate. `failures` counts it.
5. **Live runs** save each `LlmResult` to `<out>/outputs/<case>/<run>/<purpose>.json` in s08's Recording JSON shape, so a person can promote it into `api/evals/recordings/`. Replay runs save nothing.

The harness does **not** drive the database-bound `ExtractRunner` or `AdjudicateRunner` (see Assumptions). It does reuse their request builders, schemas, model config, clients, limiter and result constructors. Whatever the stations send, the eval sends too.

### Matching suite (AC3)

1. `fake = FakeFusionClient.from_json(prior/day/fusion.json, today=<max payment date in the fixtures>)`. A fresh fake is built for each message, so nothing leaks between messages.
2. For each `PriorMessage`: `extraction = RemittanceExtraction.model_validate(msg.extraction)`.
3. `resolution = await resolve_customer(extraction, aliases=_NoAliases(), fusion=fake)`.
   - `_NoAliases.lookup` returns `AliasMatch()`. Alias learning isn't under evaluation, and it keeps the replay stateless.
   - A `StageError` gives outcome `resolution_error` and records its code.
4. Query receipts:
   - `w = config.matching().date_window_days`
   - `receipts = await fake.find_receipts(customer_numbers=resolution.owners(), date_from=pd-w, date_to=pd+w)`
5. Build the `MatchContext` with s13's builder if s13 exposes one. Otherwise build it from the AC1 fields:
   - payment amount and currency from the extraction or `resolution.currency`
   - `payment_date`
   - `anchor` and `related`
   - `references` (the remittance reference)
   - `invoice_numbers` from the lookup lines
   - `payer_bank_account`
   - `fix_hints={}`
6. Score: `scored = score_candidates(ctx, receipts, config.matching(), None)`. The outcome is `scored.outcome`: `matched`, `none`, `ambiguous` or `variance`.
7. If the outcome is `matched`, plan the lines:
   - `plan = plan_lines(extraction.lines, txn_map, winner.receipt.unapplied_amount, await fake.list_receipt_applications(id), currency)`
   - `txn_map` is built the way s15's `MatchLinesRunner` builds it. The s15 helper is used if exposed. Otherwise the map keys `resolution.transactions` by number, with the kind preferred by the line.
8. Predicted line status, keyed by `normalise_ref(transaction_number)`:
   - from the plan: the result drafts, plus the steps' target applied statuses
   - otherwise from `resolution.line_findings[*].candidate_status`
   - otherwise `None` (`no-verdict`)

**Metrics:**
- **Confusion matrix:** rows are AR's four labels (`receipt_in_fusion`, `not_yet_entered`, `not_in_fusion`, `future`). Columns are `matched`, `none`, `ambiguous`, `variance`, `resolution_error`.
- **Label agreement:** `receipt_in_fusion`→`matched`; the other three→`none`. The receipt isn't in the snapshot, so `none` is the correct "await" outcome. The report gives agreement overall and per label.
- **Line-status agreement:** over `day/messages.jsonl` outcome lines, comparing the prior `line_status` with the predicted status (exact enum). It comes with a status confusion matrix and counts of lines `skipped` for a missing extraction or a non-matching number.
- **Skips:** labelled failures whose `message_id` is missing from `messages.jsonl` are counted as `skipped.no_extraction`.

### Auto-fix suite (AC4)

1. For each `LabelledFailure` (the first `--limit`), the code is derived by replaying the message through the matching pipeline above:
   - outcome `none` → `RECEIPT_NOT_YET_AVAILABLE`
   - `ambiguous` → `RECEIPT_AMBIGUOUS`
   - `variance` → `AMOUNT_VARIANCE`
   - `resolution_error` → its code
   - `matched` → no error, actual decision `matched`
2. **Call the engine through its production entry point**, `await engine.handle(uow, item, StageError(code), ctx)`:
   - `engine` comes from s18's `build_failure_handler`, given a minimal container with the eval `RuntimeConfig`, a `FrozenClock` and an `LlmClients` whose workhorse is a `ReplayLlmClient` that always raises `LLM_TRANSIENT`. s18 AC4 then guarantees the template summary, so there are zero model calls.
   - `uow` is an in-memory aiosqlite engine (`load_all_models()` + `create_all`, imported lazily). A `WORK_ITEM` row is seeded per case at the stage that raised the code.
   - The `StageContext` is built from s03's dataclass with `SYSTEM_PRINCIPAL`.
3. Map each decision to a kind with s03's `decision_kind`: `park` → `AWAITING_RECEIPT`, `escalate` → `escalation`, `retry`/`reroute` → as named.
4. **For labels whose expected decision is "escalation after aging" (`not_in_fusion`):** after a `park`, the clock is advanced past `config.aging()` and `AGED_OUT` is fed to the engine. The final decision must be `escalate`.
5. **Expected decisions come from s43's label mapping.** No copy lives here.
6. **Report:** agreement overall and per label, a confusion matrix (expected → actual), the error codes seen with counts, and a per-case list `{message_id, label, code, decisions[], agrees}`.

### Cost (AC5)

`EvalUsageRecorder` keeps one row per call: role, model, input and output tokens, outcome and `cost_usd`. Cost uses s36's per-model cost function over `PRICES`.

`CostSummary` reports:
- `mode` (`live` or `replay`)
- `calls`, `input_tokens`, `output_tokens`
- `spent_usd`: the sum in live mode, and `"0.00"` in replay, since recorded usage isn't spent
- `recorded_usage_usd`: what the recorded calls would cost
- `by_role` and `by_model`
- `unknown_price_models`: their cost is null; they are listed and never summed as zero

The extraction-free suites report `calls: 0`.

### Report (AC1)

- `report.json` is `EvalReport.model_dump_json(indent=2)`.
- `report.md` is rendered from the same object:
  - a header with run id, mode, suites, limit, runs, config overrides, model ids, and prompt and schema versions
  - a cost table
  - for extraction: a per-field accuracy table with columns A / B / adjudicated, and a line precision/recall/F1 table
  - for matching: the confusion matrix and label agreement
  - line-status agreement
  - for autofix: agreement and the confusion matrix
  - a `not_evaluated` banner for any empty suite
- The output directory is created with `exist_ok=False`, so a run never overwrites an earlier report.

### Gold set (AC6)

The gold files are synthetic and use invented payer names (`Example Payer One` style, no real entities). Every file has `"synthetic": true`.

| File | Covers |
|---|---|
| `g01_credit_memo_suffix` | invoice `INV-10021` plus credit memo `2598014-1` with a negative amount, and a plain `2598014` invoice. The suffix must be kept, and the two are distinct. |
| `g02_no_amount_lines` | three invoice numbers listed without amounts, a header amount only |
| `g03_dollar_ambiguous` | currency written `$` only: `currency_ambiguous=true`, `currency=null` (a negative case: a reader that guesses USD is wrong) |
| `g04_multiple_dates` | invoice date, value date and deposit date. `dates` holds all three; `payment_date` is the value date. |
| `g05_bank_fee` | two invoices plus a `BANK_FEE` line of 15.00. `bank_fees=["15.00"]`; header = invoices − fee. |
| `g06_inr_whole_rupee` | a CSV table artifact in INR with whole-rupee amounts and a PO reference (`po_refs`) |

Gold JSON (`GoldCase`):

```json
{"case_id": "g01_credit_memo_suffix", "synthetic": true, "artifact": "g01_credit_memo_suffix.txt",
 "tags": ["suffix"], "expected": {GoldExpected}}
```

## Interfaces provided (pinned)

```python
# cashapp/evals/options.py
class Suite(StrEnum): EXTRACTION = "extraction"; MATCHING = "matching"; AUTOFIX = "autofix"; ALL = "all"
@dataclass(frozen=True, slots=True)
class EvalOptions:
    suites: frozenset[Suite]                 # ALL expanded
    out_dir: Path
    gold_dir: Path; prior_dir: Path; recordings_dir: Path; artifacts_dir: Path
    limit: int | None = None
    runs: int = 1
    replay: bool = False
    confirm_spend: bool = False
    config_overrides: Mapping[str, Any] = field(default_factory=dict)
    @property
    def needs_models(self) -> bool           # EXTRACTION in suites and not replay
def default_paths() -> dict[str, Path]       # api-root-relative defaults

# cashapp/evals/runner.py
class SpendNotConfirmed(Exception): ...
LlmFactory = Callable[[ConfigSnapshot], Awaitable[LlmClients]]
async def run_evals(options: EvalOptions, *, llm_factory: LlmFactory | None = None,
                    clock: Clock | None = None) -> EvalReport
    # raises SpendNotConfirmed before calling llm_factory when options.needs_models and not confirm_spend
    # writes report.md + report.json into options.out_dir

# cashapp/evals/gold.py
class GoldLine(BaseModel): kind: LineKind; transaction_number: str; amount_paid: MoneyStr | None = None
class GoldExpected(BaseModel):          # every field optional; omitted = not scored, explicit null = expected absent
    payer_name: str | None; payer_bank_account: str | None; remittance_reference: str | None
    payment_amount: MoneyStr | None; currency: CurrencyCode | None; currency_ambiguous: bool | None
    payment_date: date | None; dates: list[date] | None; bank_fees: list[MoneyStr] | None
    po_refs: list[str] | None; lines: list[GoldLine]
    model_config = ConfigDict(extra="forbid")   # fields_set drives "scored or not"
class GoldCase(BaseModel): case_id: str; synthetic: bool; artifact: str; tags: list[str]; expected: GoldExpected
def load_gold(directory: Path) -> list[GoldCase]     # sorted by case_id; invalid file -> ValueError naming it

# cashapp/evals/prior.py   (consumes s43's pinned format)
class PriorLineOutcome(BaseModel): transaction_number: str; line_status: LineStatus; applied_amount: MoneyStr | None
class PriorMessage(BaseModel): message_id: str; extraction: dict[str, Any]; outcome: PriorOutcome
class LabelledFailure(BaseModel): message_id: str; label: PriorLabel; fusion_amount: MoneyStr | None; line_labels: list[Any]
PriorLabel = Literal["receipt_in_fusion", "not_yet_entered", "not_in_fusion", "future"]
@dataclass(frozen=True, slots=True)
class PriorFixtures: messages: list[PriorMessage]; failures: list[LabelledFailure]; fusion_json: dict[str, Any]
def load_prior(directory: Path) -> PriorFixtures

# cashapp/evals/scoring.py   (pure)
def normalise_ref(value: str | None) -> str | None
def score_fields(expected: GoldExpected, actual: RemittanceExtraction | None) -> dict[str, bool]
def score_lines(expected: Sequence[GoldLine], actual: RemittanceExtraction | None) -> LineScore
class ConfusionCounter:
    def __init__(self, rows: Sequence[str], cols: Sequence[str]) -> None
    def add(self, row: str, col: str) -> None
    def to_model(self) -> ConfusionMatrix

# cashapp/evals/usage.py
class EvalUsageRecorder:                 # satisfies s36 UsageRecorder; in memory only
    rows: list[UsageRow]
def meter_clients(clients: LlmClients, recorder: EvalUsageRecorder) -> LlmClients   # s36 MeteredLlmClient per role
def summarise_cost(recorder: EvalUsageRecorder, *, mode: Literal["live", "replay"]) -> CostSummary
```

```python
# cashapp/evals/models.py   (report.json contract; money as strings)
class Ratio(BaseModel): correct: int; total: int; rate: float | None          # None when total == 0
class LineScore(BaseModel): expected: int; predicted: int; true_positive: int
    precision: float | None; recall: float | None; f1: float | None
    amount_correct: int; kind_correct: int; missing: list[str]; extra: list[str]
class VariantScore(BaseModel): fields: dict[str, Ratio]; lines: LineScore; fee_lines: Ratio; failures: int
class ExtractionCaseResult(BaseModel):
    case_id: str; run: int
    variants: dict[Literal["reader_a", "reader_b", "adjudicated"], CaseVariant]   # CaseVariant{fields: dict[str,bool], lines: LineScore, error_code: str|None}
    missing_reader: Literal["A", "B"] | None; grounding_violations: list[str]
    disagreements: int; adjudication_confidence: float | None
class ConfusionMatrix(BaseModel): rows: list[str]; cols: list[str]; counts: list[list[int]]
class SuiteStatus(StrEnum): EVALUATED = "evaluated"; NOT_EVALUATED = "not_evaluated"
class ExtractionSuiteReport(BaseModel):
    status: SuiteStatus; reason: str | None; cases: int; runs: int
    by_variant: dict[str, VariantScore]; per_case: list[ExtractionCaseResult]
class MatchingCaseResult(BaseModel):
    message_id: str; label: PriorLabel | None; outcome: str; error_code: str | None
    receipt_id: int | None; candidates: int; agrees: bool | None
class MatchingSuiteReport(BaseModel):
    status: SuiteStatus; reason: str | None; messages: int; labelled: int
    label_confusion: ConfusionMatrix; label_agreement: Ratio; agreement_by_label: dict[str, Ratio]
    line_status_agreement: Ratio; line_status_confusion: ConfusionMatrix
    skipped: dict[str, int]; per_case: list[MatchingCaseResult]
class AutofixCaseResult(BaseModel):
    message_id: str; label: PriorLabel; error_code: str | None; decisions: list[str]; expected: str; agrees: bool
class AutofixSuiteReport(BaseModel):
    status: SuiteStatus; reason: str | None; cases: int; agreement: Ratio
    agreement_by_label: dict[str, Ratio]; confusion: ConfusionMatrix; codes_seen: dict[str, int]
    per_case: list[AutofixCaseResult]
class RoleCost(BaseModel): calls: int; input_tokens: int; output_tokens: int; cost_usd: str | None
class CostSummary(BaseModel):
    mode: Literal["live", "replay"]; calls: int; input_tokens: int; output_tokens: int
    spent_usd: str; recorded_usage_usd: str; by_role: dict[str, RoleCost]; by_model: dict[str, RoleCost]
    unknown_price_models: list[str]
class EvalReport(BaseModel):
    run_id: str; started_at: datetime; finished_at: datetime; cashapp_version: str
    suites: list[Suite]; limit: int | None; runs: int; replay: bool
    config_overrides: dict[str, Any]; models: dict[str, str]; prompt_versions: dict[str, str]
    cost: CostSummary
    extraction: ExtractionSuiteReport | None = None
    matching: MatchingSuiteReport | None = None
    autofix: AutofixSuiteReport | None = None
```

No later story consumes these yet. They're pinned so that report.json stays a stable format across runs, which is what makes comparing a change before and after possible.

## Consumed interfaces (from Deps; names adapted to each plan by the coder/merger)

| From | What's used |
|---|---|
| s08 (planned) | `LlmClients`, `LlmClient.parse`, `LlmError`, `ReplayLlmClient(recordings_dir=)`, `build_llm_clients`, `load_content_parts`, `ArtifactPartRef`, `fit_parts`, `build_reader_request`, `RemittanceExtraction`, `LineKind`, `ReaderSlot`, `PROMPT_VERSION`, `SCHEMA_VERSION` |
| s09 (planned) | `build_adjudicator_request`, `AdjudicatorDecision`, `AdjudicationResult.from_decision`, `single_reader_result`, `check_grounding`, `PROMPT_VERSION`, `ADJUDICATION_SCHEMA_VERSION` |
| s11 (planned) | `resolve_customer(extraction, *, aliases, fusion)`, `CustomerResolution.owners()`, `.transactions`, `.line_findings` |
| s05 (planned) | `FakeFusionClient.from_json(data, today=)`, `find_receipts`, `list_receipt_applications` |
| s28 (planned) | `ConfigSnapshot`, `RuntimeConfig(store)`, `ConfigStore`, `lookup_key`, `validate_value`, `matching()`, `models()`, `aging()` |
| s02 / s03 / s06 / s27 / s30 / s37 (planned) | `money_eq`, `LineStatus`, `ErrorCode`, `make_uow_factory`, `load_all_models`, `StageError`, `StageContext`, `decision_kind`, `LocalFolderObjectStore`, `aload_settings`, `Container`, `AliasMatch`, `normalise_payer_name`, `normalise_bank_account` |
| s13 (not yet planned; story AC1) | `score_candidates(ctx, receipts, config, aliases) -> ScoredCandidates`, `MatchContext` |
| s15 (not yet planned; story AC1) | `plan_lines(lines, transactions, receipt_remaining, existing, payment_currency) -> LinePlan`. A target applied status per step is needed (see Risks). |
| s18 (not yet planned; story AC1) | `build_failure_handler(container)` returning a `FailureHandler`, plus the template fallback when the workhorse fails |
| s36 (not yet planned; story AC2/3) | `MeteredLlmClient(inner, role, recorder)`, the `UsageRecorder` Protocol, `PRICES` and its per-call cost function |
| s43 (not yet planned; story AC2/3) | the fixture files, and the label → expected decision mapping constant |

## Migrations

None. The harness writes nothing to ATP. The autofix suite uses a throwaway in-memory SQLite schema created from the ORM metadata. No Alembic head changes.

## TEST PLAN (written and run in step 5 only; all unit, no `live`, no `atp`)

| AC | Test (`api/tests/evals/…::name`) | Asserts |
|---|---|---|
| 1 | `test_cli.py::test_run_all_replay_writes_report_md_and_json` | typer `CliRunner` `run --suite all --replay --out <tmp>` exits 0; `report.json` validates as `EvalReport` with all three suites; `report.md` contains each suite heading and the cost table |
| 1 | `test_cli.py::test_default_out_dir_is_timestamped_under_api_evals_reports` | Without `--out` (paths patched to tmp), the directory name matches `\d{8}T\d{6}Z` under `evals/reports`; a second run into an existing `--out` is refused (exit 2) |
| 1 | `test_cli.py::test_limit_caps_cases_per_suite` | `--limit 2` gives extraction `cases == 2`, and matching/autofix ≤ 2 |
| 1 | `test_cli.py::test_unknown_suite_rejected` | `--suite nope` exits 2 |
| 1 | `test_cli.py::test_empty_suite_is_not_evaluated_and_exit_1` | Empty gold dir gives extraction `status == "not_evaluated"` with a reason, exit 1, and no `rate == 1.0` anywhere |
| 2 | `test_extraction_suite.py::test_replay_scores_per_reader_and_adjudicated` | Over the committed gold + recordings: exact expected `Ratio`s for the deliberately wrong fields (for example reader B `lines.recall < 1` on g01 because it dropped `-1`, and reader A misses `bank_fees` on g05); adjudicated equals the recorded decision's scores |
| 2 | `test_extraction_suite.py::test_uses_station_builders_and_same_parts` | `ReplayLlmClient.calls` purposes are `extract.reader_a`, `extract.reader_b`, `adjudicate.adjudicator`; A and B requests have identical `system`/`parts`/`prompt_version`/`schema_version`; adjudicator parts are text only |
| 2 | `test_extraction_suite.py::test_one_reader_fails_uses_single_reader_result` | Scripted B refusal: no adjudicator call, `missing_reader == "B"`, adjudicated scores equal reader A's, B `failures == 1` |
| 2 | `test_extraction_suite.py::test_failed_variant_counts_as_miss` | Both readers fail: every gold field wrong for all variants, recall 0, `failures == 1` |
| 2 | `test_extraction_suite.py::test_runs_repeat_each_case` | `runs=3` gives 3 `per_case` entries per case and totals ×3 |
| 2 | `test_scoring.py::test_field_normalisation_money_and_dates` | Payer name case/space-insensitive; `normalise_ref(" inv 1 ")=="INV 1"`; money 10.004 vs 10.00 equal, 10.006 not; dates exact; an omitted gold field is not scored; an explicit null is scored (negative case) |
| 2 | `test_scoring.py::test_line_precision_recall_keep_suffix` | Expected {`2598014`, `2598014-1`} vs predicted {`2598014`} gives P=1.0, R=0.5; duplicates scored as a multiset; fee lines excluded from transaction P/R |
| 2 | `test_scoring.py::test_ratio_none_when_total_zero` | No 100% from nothing |
| 3 | `test_matching_suite.py::test_confusion_over_four_labels` | `FusionScenario` (tests/support) built in-test with 5 messages: `receipt_in_fusion` with a matching receipt → `matched`; `not_yet_entered`/`future`/`not_in_fusion` with no receipt → `none`; a duplicate-amount pair → `ambiguous` (counted as disagreement). Exact matrix and `label_agreement` |
| 3 | `test_matching_suite.py::test_line_status_agreement` | A matched message with a short pay and a not-found line: predicted `allocation-applied-short-pay` and `allocation-invoice-not-found` vs the prior outcome; exact `Ratio` and status confusion |
| 3 | `test_matching_suite.py::test_resolution_error_and_missing_extraction_skips` | An unknown invoice gives `resolution_error` with `INVOICE_NOT_FOUND`; a failure whose message_id is absent is counted in `skipped.no_extraction` |
| 3 | `test_matching_suite.py::test_runs_on_committed_s43_fixtures_without_models` | Smoke over `api/tests/fixtures/prior`: status evaluated, `cost.calls == 0` |
| 4 | `test_autofix_suite.py::test_decision_agreement_with_label_mapping` | Per label: `not_yet_entered`/`future` give `park` and agree; `receipt_in_fusion` matched gives `matched` and agrees; expected values read from s43's mapping (no literal copy in the test beyond the assertion) |
| 4 | `test_autofix_suite.py::test_not_in_fusion_escalates_after_aging` | `decisions == ["park", "escalate"]` after the clock is advanced past aging and `AGED_OUT` is fed |
| 4 | `test_autofix_suite.py::test_no_model_calls_and_template_summary` | The workhorse replay is called and fails, the template is used, and the cost summary has `spent_usd == "0.00"` with no extraction calls |
| 5 | `test_cost.py::test_live_extraction_refused_without_confirm_spend` | `run_evals(EvalOptions(suites={EXTRACTION}, replay=False))` raises `SpendNotConfirmed`; the injected `llm_factory` (raises if called) is never called; the CLI exits 2 with the refusal text and no out dir is created |
| 5 | `test_cost.py::test_matching_and_autofix_need_no_confirm` | `--suite matching` with no `--replay` and no `--confirm-spend` exits 0 |
| 5 | `test_cost.py::test_cost_sums_metered_usage_with_prices` | `--confirm-spend` with an injected factory returning scripted clients with known `LlmUsage` (Opus and Haiku model ids): `input_tokens`/`output_tokens` sums and `spent_usd` equal Σ s36 cost; `by_role` split |
| 5 | `test_cost.py::test_unknown_model_price_listed_not_zeroed` | Usage on model `x-unknown` lands in `unknown_price_models`; its `cost_usd` is null |
| 5 | `test_cost.py::test_replay_spends_nothing` | Replay: `spent_usd == "0.00"`, `recorded_usage_usd > 0`, `mode == "replay"` |
| 6 | `test_gold_set.py::test_gold_set_size_and_coverage` | ≥ 5 files load as `GoldCase`, all `synthetic: true`; by content: a `-\d+$` suffix line, a line with `amount_paid` null, `currency_ambiguous` true with currency null, ≥ 2 `dates`, a BANK_FEE line or non-empty `bank_fees` |
| 6 | `test_gold_set.py::test_every_gold_case_has_artifact_and_recordings` | The artifact exists; recordings exist for the three purposes, with `verified_against_live: false` |
| 6 | `test_gold_set.py::test_no_identifiers_in_evals_dir` | s43 `scan_for_identifiers` structural patterns over every file in `api/evals/` give no findings |

## Assumptions / deviations

- **Station logic is reused without the database-bound runners.** The extraction suite calls the stations' request builders, clients and result constructors directly; it doesn't run `ExtractRunner`/`AdjudicateRunner` with work items, artifact rows and an outbox. The story says "same station code paths", and s09's plan lists "s24 (`AdjudicateRunner` with `ReplayLlmClient`)". Driving the runners would need seeded `ARTIFACT_PART` rows, object-store keys and `run_stage_once` (which is test support), and none of that touches extraction quality. The prompts, schemas, effort, models and fan-in rules (single reader → `single_reader_result`) are identical. The fan-in timeout is applied per reader with `wait_for(role.timeout_s)`.
- **The autofix suite uses in-memory aiosqlite**, which is a dev dependency, imported lazily with a clear error if it's missing. `uv run` installs the dev group by default. The engine is exercised through its real `FailureHandler.handle` entry point rather than private handler lookups. This tool never runs in a worker image.
- **`--runs`, `--gold`, `--prior`, `--recordings` and `--config` are added** to the AC1 command line, all optional. Defaults keep the AC1 call shape. `--config` lets a rule or model change be measured before it is saved (the story's goal), and it is validated through s28's `validate_value`.
- **Label agreement for matching:** `receipt_in_fusion` expects `matched`; the other three labels expect `none`, which is the `AWAITING_RECEIPT` path. The single-snapshot matcher can't tell them apart; the autofix suite separates `not_in_fusion` through aging.
- **The autofix error code is derived by replaying the matcher**, because s43's `failures.jsonl` carries no error code. A `matched` replay means the new matcher fixed it outright, and it is recorded as the decision `matched`.
- **Replay recordings are hand-authored synthetic outputs** (`verified_against_live: false`). They prove the harness, not model quality. Live outputs saved under `outputs/` can be promoted. `parts_digest` covers parts only, not the system prompt, so a prompt change does not invalidate a recording (see Risks).
- **Reports are gitignored** through `api/evals/reports/.gitignore`, so the root `.gitignore` is not edited.
- No `git` subprocess for a commit sha (ruff `S603`). The report carries `cashapp.__version__` and the prompt and schema versions instead.

## Risks

- **s13, s15, s18, s36 and s43 aren't planned yet.** The harness codes against their story ACs; the merger reconciles names:
  - s13: whether a `MatchContext` builder is exposed
  - s15: the per-step target status. s15 AC1 says "step status target" but `LineStep` lists no status field. If none is exposed, the harness derives `applied` / `applied-short-pay` / `applied-less-than-instruction` from the step amount, the balance and the stated amount using s15's own rule. That would be a second copy, so the coder should ask s15 to expose it instead.
  - s18: the `build_failure_handler` container needs
  - s36: the `UsageRecorder.record` signature and the cost function name
  - s43: the label mapping constant name
- **The replay key ignores the system prompt.** A prompt change replays stale outputs silently. Mitigation: the report records `prompt_versions`; the README says to re-record after a prompt bump; a test asserts the recordings' purposes exist, not their freshness.
- **Live cost:** each case costs two Opus calls (reader and adjudicator) plus a Cohere call, all at configured effort, and `--runs` multiplies that. The guard prints the case × run count; there's no budget cap inside the harness. The s36 daily budget alert doesn't fire, because usage is recorded in memory, not in `LLM_USAGE`.
- **The prior outcomes come from a build with known defects** (no cap, a misleading roll-up). Line-status agreement below 100% may mean the new rules are right, so the report names it agreement, not accuracy.
- **The `FakeFusionClient` is unverified against live.** Matching metrics measure rules against fixture shapes, not Fusion behaviour.
- **SQLite drops `FOR UPDATE SKIP LOCKED` and native JSON.** That's irrelevant to decision agreement, but s18 handlers that use Oracle-only SQL would fail here. The coder should keep the handlers ORM-portable (s02 rule).
