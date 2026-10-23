# Plan: s12-spike-receipt-signal-study

Issue #12. Wave 4. Read-only spike, built against fakes (research.md: "#12 is planned against fakes").
Paths: `cashapp/` = `api/src/cashapp/`. Owns `cashapp/tools/receipt_signal_study/` and
`docs/spikes/receipt-signals.md`. No migration, no settings change, no runtime-config change, no
lockfile edit (typer, defusedxml pinned by s01).

**Open question (blocks the real run, not this story):** which Fusion pod has real cash activity.
Until Jonathan names it, the tool runs on `FakeFusionClient` scenarios and the s43 synthetic prior
fixtures, and every weight is marked "provisional — not yet measured".

## Standards followed

- CLAUDE.md *Fusion integration*: all traffic through the one `FusionClient` (s05); no new HTTP
  code; BIP through `FusionClient.run_report`; XML parsed with `defusedxml`. Never OIC.
- CLAUDE.md *Conventions*: money is `Decimal` (`cashapp.domain.money.to_money`, `money_equal`
  `|a-b| ≤ 0.005`); no customer/client names, account numbers, receipt or invoice numbers in output,
  logs or docs. Output is aggregate counts and rates only.
- CLAUDE.md non-negotiable 7 (DRY): the write-refusing wrapper is s05's `read_only(client)`, not a
  second one; tolerances and the date window come from s02's config-key defaults
  (`MATCHING_TOLERANCES`, `MATCHING_DATE_WINDOW_DAYS`) via `MatchingConfig`-equivalent values read
  from `ConfigKey.default` (the tool has no DB), overridable by CLI flags; the identifier scanner is
  s43's `scan_for_identifiers`.
- `python-web-app:building-python-web-apps`: the CLI is a thin typer shell over pure functions
  (`collect` → `measure` → `write_report`); Fusion client is passed in, never built inside the logic;
  settings only touched in `__main__.py` (via s27 `aload_settings()` + s05 `FusionClientFactory`).
- pyright strict, ruff. Frozen slotted dataclasses for study records (tooling, not API contracts).
- Read-only: the tool never calls a write method; it wraps every client in `read_only()` before
  passing it on, and a test proves the wrapper raises.

## Files to touch

All new; file-disjoint from every other story.

| Path | Contents |
|---|---|
| `api/src/cashapp/tools/receipt_signal_study/__init__.py` | re-exports `run_study`, `StudyResult`, `SIGNALS`, `PROPOSED_SCORER_WEIGHT_KEYS` |
| `api/src/cashapp/tools/receipt_signal_study/__main__.py` | typer app: `--pod`, `--from`, `--to`, `--out`, optional `--prior <dir>`, `--signals-report <bip path>`, `--date-window-days`, `--limit-receipts`; builds client with `FusionClientFactory(settings).for_pod(pod)`, wraps in `read_only`, `asyncio.run(run_study(...))`, writes output, closes client; exit 0/1/2 (ok / study error / bad args) |
| `api/src/cashapp/tools/receipt_signal_study/models.py` | `SignalName` StrEnum, `StudyReceipt`, `StatementSignals`, `StudyCase`, `SignalStat`, `StudyResult`, `SkippedSignal` |
| `api/src/cashapp/tools/receipt_signal_study/collect.py` | `collect_receipts`, `collect_applications`, `collect_statement_signals`, `collect_relationships`, `build_cases_from_fusion`, `build_cases_from_prior` |
| `api/src/cashapp/tools/receipt_signal_study/signals.py` | one predicate per signal: `candidate_matches(signal, case, receipt, ctx) -> bool | None` (None = signal absent for this case) |
| `api/src/cashapp/tools/receipt_signal_study/measure.py` | `measure(cases, pool, ctx) -> list[SignalStat]` (presence, precision, ambiguity, miss) |
| `api/src/cashapp/tools/receipt_signal_study/report.py` | `write_report(result, out_dir)`: `signals.csv`, `signals.json`, `run.json` (parameters, counts, skipped signals, `provisional` flag); templates are constants here |
| `api/src/cashapp/tools/receipt_signal_study/run.py` | `run_study(client, *, date_from, date_to, ...) -> StudyResult` (orchestration) |
| `docs/spikes/receipt-signals.md` | the proposal (AC4), open question at the top |
| `api/tests/fixtures/receipt_signal_study/scenario.json` | `FusionScenario` JSON (s05 pinned shape): ~12 receipts across 3 anonymised customers incl. duplicate amounts, a receipt created a day after its receipt date, a related-customer receipt, references on some receipts, applications as truth |
| `api/tests/fixtures/receipt_signal_study/receipt_signals.xml` | BIP report output in the row shape pinned below (anonymised, hashed bank accounts) |
| `api/tests/unit/tools/test_receipt_signal_study.py` | AC1–AC4 tests |
| `api/tests/unit/tools/test_receipt_signal_study_scan.py` | AC5 |

Not touched: `cashapp/integrations/fusion/*` (s05), `fusion/bip/*` (s32 writes `receipt_signals.sql`
to the row shape below), `cashapp/domain/config_keys.py` (s02), `cashapp/tools/anonymise/*` (s43),
`api/tests/test_no_identifiers.py` (s43).

## Design

### Reading (AC1)

All reads go through the `read_only(FusionClient)` wrapper:

1. **Receipts**: page `receipts_created_since(since=date_from 00:00Z, limit=500)`, advancing `since`
   to the last `creation_date`, deduping on `receipt_id`, until a page is short or
   `creation_date > date_to + 1 day`. Creation time is used (CLAUDE.md watcher rule); receipts whose
   `receipt_date` falls in `[from, to]` are the study set, others with creation in range form the
   wider candidate pool. Carries `remittance_references` and `comments`.
2. **Applications (truth)**: `list_receipt_applications(receipt_id)` per receipt, bounded by an
   `asyncio.Semaphore(4)`. Only `status == "APP"` rows count. A receipt with ≥1 active application is a
   truth-bearing receipt.
3. **Transactions**: `find_transactions(all remittance references ∪ prior-case invoice numbers)` →
   map number → `customer_trx_id`, so invoice-set overlap compares on IDs (applications carry IDs
   only).
4. **Relationships**: `customer_relationships(owner account numbers)` for the related-customer signal.
5. **Statement-line signals** (statement reference, addenda text, payer name, payer bank account):
   `run_report(signals_report_path, {"P_CREATION_FROM": iso, "P_CREATION_TO": iso})` when
   `--signals-report` is given, parsed with defusedxml. When it is not given, or the report raises
   `FusionError`, those four signals are recorded in `skipped` with reason
   `"no receipt_signals report (s32 catalog)"` and reported as `presence=null, precision=null`.
   Bank account values are SHA-256-hashed in memory on parse; the raw value is never kept.

### Cases (the remittance side)

- **`--prior <dir>`** (s43 format: `prior/day/messages.jsonl` + `prior/day/fusion.json`): one case
  per message whose outcome has applied lines; remittance facts from the extraction (`payment_amount`,
  `currency`, `payment_date`, `remittance_reference`, `payer_name`, `payer_bank_account`, line
  `transaction_number`s); anchor = bill-to of the first found transaction; truth = the receipt whose
  applications cover those transactions. When `fusion.json` is given and `--pod` is `fake`, the fake
  is seeded from it.
- **Fusion-only** (default, real pod without remittances): one case per truth-bearing receipt; the
  "remittance" is reconstructed from the truth (amount = sum of active applications, currency,
  anchor = bill-to of applied transactions, invoice set = applied IDs, payment date = receipt date).
  This measures how *discriminating* each receipt attribute is inside the candidate pool. Signals that
  would be circular in this mode (`amount_exact`, `date_receipt_window`, `currency`) are still
  computed but flagged `circular: true` in the output; `run.json` records `case_source`.

### Signals and measures (AC2)

`SIGNALS` (pinned, order = CSV order): `amount_exact`, `amount_tolerance`, `date_receipt_window`,
`date_creation_window`, `currency`, `customer_anchor`, `customer_related`, `remittance_reference`,
`statement_reference`, `addenda_text`, `payer_name`, `payer_bank_account`, `comments`,
`invoice_set_overlap`.

Predicates (case, candidate receipt): amounts on `unapplied_amount + amount applied to this case`
(i.e. original amount for truth receipts), exact = `money_equal`, tolerance = `tolerance_for(currency)`;
date windows `|receipt_date − payment_date| ≤ W` and `|creation_date.date() − payment_date| ≤ W`;
references compared after normalisation (upper-case, strip spaces/leading zeros, s13 to reuse the
same rule — see doc); addenda/comments: contains the case's remittance reference or any invoice
number; payer name: case-folded token-set equality; bank account: hash equality; invoice-set overlap:
≥1 shared transaction ID between candidate references and the case's invoice set.

Per signal, over cases in which the signal is *present* (case has the value AND the truth receipt
has it):
- `presence_rate = present / cases`
- `precision = cases where {receipts in pool matching the signal} == {truth} / present`
- `ambiguous_rate` (truth among ≥2 matches), `miss_rate` (truth not matched)
- `date_distance` histogram buckets (0, 1, 2, 3–5, >5 days) for both date bases.

Output (`--out`): `signals.csv` (columns `signal,present,cases,presence_rate,precision,ambiguous_rate,
miss_rate,circular,skipped_reason`), `signals.json` (same rows + histograms), `run.json` (`pod`,
`from`, `to`, `case_source`, receipt/case/pool counts, `date_window_days`, `tolerances`,
`provisional: true` unless `--pod` is a configured non-fake pod and `case_source == "prior"` or
`"fusion"`, `generated_at`). No identifiers: rows are keyed by signal name only; the pod name is the
settings key (e.g. `dev`), not a host.

## Interfaces provided (pinned)

```python
# cashapp/tools/receipt_signal_study/models.py
class SignalName(StrEnum):
    AMOUNT_EXACT = "amount_exact"; AMOUNT_TOLERANCE = "amount_tolerance"
    DATE_RECEIPT_WINDOW = "date_receipt_window"; DATE_CREATION_WINDOW = "date_creation_window"
    CURRENCY = "currency"; CUSTOMER_ANCHOR = "customer_anchor"; CUSTOMER_RELATED = "customer_related"
    REMITTANCE_REFERENCE = "remittance_reference"; STATEMENT_REFERENCE = "statement_reference"
    ADDENDA_TEXT = "addenda_text"; PAYER_NAME = "payer_name"; PAYER_BANK_ACCOUNT = "payer_bank_account"
    COMMENTS = "comments"; INVOICE_SET_OVERLAP = "invoice_set_overlap"
SIGNALS: tuple[SignalName, ...]

@dataclass(frozen=True, slots=True)
class SignalStat:
    signal: SignalName; present: int; cases: int
    presence_rate: float | None; precision: float | None
    ambiguous_rate: float | None; miss_rate: float | None
    circular: bool; skipped_reason: str | None

@dataclass(frozen=True, slots=True)
class StudyResult:
    pod: str; date_from: date; date_to: date; case_source: Literal["fusion", "prior"]
    receipts: int; pool: int; cases: int; date_window_days: int
    stats: tuple[SignalStat, ...]
    date_distance: Mapping[Literal["receipt_date", "creation_date"], Mapping[str, int]]
    provisional: bool

# cashapp/tools/receipt_signal_study/run.py
async def run_study(client: FusionClient, *, date_from: date, date_to: date,
                    date_window_days: int | None = None,             # None → MATCHING_DATE_WINDOW_DAYS default
                    tolerances: Mapping[str, Decimal] | None = None,  # None → MATCHING_TOLERANCES default
                    signals_report_path: str | None = None,
                    prior_dir: Path | None = None,
                    limit_receipts: int = 20_000) -> StudyResult
    # wraps client in read_only() itself (idempotent if already wrapped)

# cashapp/tools/receipt_signal_study/report.py
def write_report(result: StudyResult, out_dir: Path) -> list[Path]   # signals.csv, signals.json, run.json

# cashapp/tools/receipt_signal_study/__init__.py
PROPOSED_SCORER_WEIGHT_KEYS: tuple[str, ...] = (
    "remittance_reference", "statement_reference", "invoice_set_overlap",
    "payer_bank_account", "date_distance", "alias_reference_pattern", "customer_history",
)   # the keys s13 implements for MATCHING_SCORER_WEIGHTS; hard filters carry no weight
```

**BIP row shape for s32's `fusion/bip/receipt_signals.sql`** (parameters `P_CREATION_FROM`,
`P_CREATION_TO`, ISO timestamps; one row per receipt × statement line; UNVERIFIED cash-management
source tables, s32 confirms on the pod):

```xml
<DATA_DS><G_1>
  <RECEIPT_ID>500001</RECEIPT_ID><STATEMENT_LINE_REFERENCE>…</STATEMENT_LINE_REFERENCE>
  <ADDENDA_TEXT>…</ADDENDA_TEXT><PAYER_NAME>…</PAYER_NAME><PAYER_BANK_ACCOUNT>…</PAYER_BANK_ACCOUNT>
</G_1>…</DATA_DS>
```

**Proposal pinned for s13** (in `docs/spikes/receipt-signals.md`, fenced ```json block, provisional):

```json
{"matching.scorer_weights": {"remittance_reference": 0.35, "invoice_set_overlap": 0.30,
  "statement_reference": 0.15, "payer_bank_account": 0.10, "date_distance": 0.05,
  "alias_reference_pattern": 0.03, "customer_history": 0.02},
 "matching.min_score": 0.15}
```

Weights sum to 1.0; each soft signal contributes `weight × strength (0..1)`; `min_score` is the
margin the winner must beat the runner-up by under `FIX_HINTS.narrow` (s13 AC3). Hard filters
(currency, amount tolerance/bank-fee band, date window, owner anchor/related) are filters, not
weights. The doc also states: reference normalisation rule, the per-signal rationale from reference
doc §4/§6 (timing: creation-date window; duplicates: amount alone is ambiguous), and the procedure to
re-run on the named pod and replace the numbers (update via the configuration screen, s21, with a
CONFIG_CHANGE reason citing the study run).

## Migrations

None.

## TEST PLAN (written and run only at step 5)

| AC | Test (file::name) |
|---|---|
| 1 | `test_receipt_signal_study.py::test_cli_parses_pod_from_to_out_and_runs` (typer `CliRunner`, `--pod fake` seeded from the fixture scenario via a monkeypatched factory; exit 0; three files written) |
| 1 | `test_receipt_signal_study.py::test_tool_wrapper_raises_on_every_write_method` (parametrised over s05 `WRITE_METHODS`: the client `run_study` uses is `read_only`-wrapped; each write raises `FusionError(FUSION_WRITE_DISABLED)`) |
| 1 | `test_receipt_signal_study.py::test_study_calls_only_read_methods` (after a full run, every `FakeFusionClient.calls` method ∉ `WRITE_METHODS`; reads include `receipts_created_since`, `list_receipt_applications`, `find_transactions`, `customer_relationships`, `run_report`) |
| 1 | `test_receipt_signal_study.py::test_receipts_paged_by_creation_time_and_deduped` (limit forces 3 pages; boundary receipt counted once; receipt created a day after its receipt date is included) |
| 1 | `test_receipt_signal_study.py::test_statement_signals_skipped_without_report` (no `--signals-report` and missing-report `FusionError` → four signals `skipped_reason` set, null rates) |
| 2 | `test_receipt_signal_study.py::test_presence_and_precision_per_signal` (hand-computed expectations on the scenario: `amount_exact` precision < 1 because of duplicate amounts; `remittance_reference` precision 1.0; `date_creation_window` catches the late-created receipt that `date_receipt_window` misses) |
| 2 | `test_receipt_signal_study.py::test_tolerance_uses_currency_specific_value` (INR 0.49 qualifies, USD 0.49 does not; Decimal only) |
| 2 | `test_receipt_signal_study.py::test_output_csv_and_json_are_aggregate_only` (CSV header pinned; rows keyed by signal; no receipt/transaction/account number from the scenario appears in any output file) |
| 2 | `test_receipt_signal_study.py::test_bank_account_hashed_on_parse` (parsed `StatementSignals` holds no raw value) |
| 3 | `test_receipt_signal_study.py::test_end_to_end_on_fake_and_prior_fixtures` (`run_study` on the scenario in fusion mode and on s43 `prior/` fixtures in prior mode → `StudyResult` with all 14 signals, `provisional=True`, `write_report` files parse) |
| 4 | `test_receipt_signal_study.py::test_spike_doc_proposes_weights_for_s13` (doc's first heading section contains "Open question" and "pod"; the fenced JSON parses; keys of `matching.scorer_weights` == `PROPOSED_SCORER_WEIGHT_KEYS`; values ≥ 0 and sum to 1.0 ± 1e-9; `matching.min_score` is a float in [0, 1]; the word "provisional — not yet measured" appears; values validate against s02's `MATCHING_SCORER_WEIGHTS`/`MATCHING_MIN_SCORE` key types via s28 `validate_value`) |
| 5 | `test_receipt_signal_study_scan.py::test_doc_and_output_templates_have_no_identifiers` (scans `docs/spikes/receipt-signals.md`, the CSV/JSON templates in `report.py`, and a generated output dir: s43 `scan_for_identifiers` when importable, else a regex for emails, IBAN-like strings and runs of ≥8 digits not prefixed by an anonymised marker; zero findings) |

## Risks

- **Real data unavailable.** All numbers are provisional; the doc and `run.json` say so. The real
  run needs the named pod and (for statement signals) s32's report deployed there.
- **`list_receipt_applications` may be BIP-backed** (s05 risk). The method signature is fixed, so the
  tool is unaffected.
- **`receipts_created_since` volume** on a busy pod: `--limit-receipts` caps it; reads are paged and
  semaphore-bounded so the pod is never flooded.
- **Fusion-only mode is partly circular**; flagged per signal so nobody reads `amount_exact` precision
  as remittance evidence. Prior mode gives the true measure.
- **Cash-management table names** for statement lines/addenda are UNVERIFIED; owned by s32's SQL.
- **s43 lands in the same wave**; the scan test falls back to its own regex if the scanner is not
  merged yet (story AC5 allows this), and `build_cases_from_prior` codes to the s43 story's pinned
  format.

## Assumptions / deviations

- The "client wrapper that raises on any write" is s05's `read_only()` (s05 plan: provided once for
  s12 and s32), not a tool-local class.
- Tolerances and the date window default to the s02 config-key defaults (the tool has no DB access
  and must not need ATP); CLI flags override. `MatchingConfig` from s28 is not constructed.
- CLI flags added beyond the AC (`--prior`, `--signals-report`, `--date-window-days`,
  `--limit-receipts`); the AC's four flags are unchanged.
- The study measures "precision" as uniqueness of the truth receipt among the pool for that signal
  alone; the pool is every receipt created in `[from − W, to + W + 1 day]`.
- `PROPOSED_SCORER_WEIGHT_KEYS` names the soft signals; s13 owns its own constants and is expected to
  use these names (its plan should pin them). The pinned weights are not written to runtime config by
  this story (s02 default `{}` stays; s13 decides whether to seed them).
- Payer bank accounts are hashed (SHA-256, unkeyed) only in memory; nothing per-account is output.
