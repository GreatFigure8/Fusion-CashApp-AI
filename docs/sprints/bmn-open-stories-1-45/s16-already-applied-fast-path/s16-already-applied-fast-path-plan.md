# Plan: s16-already-applied-fast-path

The fast path runs right after customer resolution. If every invoice-like line on the remittance points at a Fusion transaction that is already closed, and the receipt(s) that closed each one can be determined, the station attaches the remittance to those receipts through s17's `write_back(mode="already_applied")`. It then records every line as `allocation-previously-applied` and finishes the item as `payment-previously-applied`. In every other case it hands the item to the normal path (`Advance(MATCH_RECEIPT)`) without writing to Fusion. It never applies anything. No migration and no LLM.

## Standards followed

- **CLAUDE.md layering.** The decision rules live in `cashapp/services/fast_path.py`: async, with no ORM, no `Request`, and Fusion reached only through the `FusionClient` Protocol. The runner only loads, calls the service, persists and returns an outcome. Repositories are reached only through `ctx.uow`.
- **One StageRunner (s03).** `FastPathRunner` subclasses `StageRunner` and implements `process` only. Claiming, idempotency, the STAGE_TRANSITION history row, the outbox event and failure routing all stay in the base. Failures are typed `StageError`s, so s18 gets an `ErrorCode`.
- **One status enum and one error-code enum (s02).** The station uses `LineStatus.ALLOCATION_PREVIOUSLY_APPLIED`, `PaymentStatus.PAYMENT_PREVIOUSLY_APPLIED` and `ErrorCode.WRITE_BACK_FAILED`, and defines no status strings of its own. The payment status comes from `roll_up(...)`, not a hard-coded value, so the roll-up stays strictly derived (CLAUDE.md *Matching and apply rules*).
- **Write-back exists once (non-negotiable 7).** All attaching and note writing goes through s17's `write_back`. This story contains no Fusion write call. The only Fusion calls made directly are reads: `list_transaction_applications`, and `find_transactions` on retries.
- **Money (s02).** `Decimal` and `money_eq` throughout. A balance counts as closed when `money_eq(abs(balance), Decimal("0"))`, which is sign-aware for credit memos.
- **Auditability (CLAUDE.md).** A DECISION history row records the closing receipt(s), the per-transaction evidence and the reason. Each write-back records a FUSION_WRITE row. A fall-through records its reason in the `Advance` note and payload, which s03 writes as the STAGE_TRANSITION row.
- **PII (CLAUDE.md, s29).** History payloads, `StageError.detail` and logs carry ids, transaction numbers, amounts and codes only. They never carry payer names or artifact text.
- **python-web-app (building-python-web-apps).** Logic sits in services and the station stays thin. The external SDK is isolated behind `FusionClient`.
- **Fail closed.** Any doubt, such as an unknown application status, an ambiguous transaction match, a missing receipt id or an unmatched line, falls through to the normal path. It never takes the fast path.
- LLM skills aren't loaded: the station makes no LLM call.

## Files to touch

All files are new. The owned paths are `cashapp/stations/fast_path/` and `cashapp/services/fast_path.py`. They are file-disjoint from s11, s13, s15 and s17.

| Path | Content |
|---|---|
| `api/src/cashapp/services/fast_path.py` | `ACTIVE_APPLICATION_STATUSES`, `LineTransaction`, `LineMatch`, `match_line_transactions`, `ClosingReceipts`, `find_closing_receipts`, `closing_reason` |
| `api/src/cashapp/stations/__init__.py` | empty; create only if absent |
| `api/src/cashapp/stations/fast_path/__init__.py` | re-exports `ROLE` |
| `api/src/cashapp/stations/fast_path/runner.py` | `FastPathRunner(StageRunner)`, `build(container)`, `ROLE` |
| `api/tests/services/test_fast_path.py` | unit tests for AC1 and AC5's reason text |
| `api/tests/stations/fast_path/__init__.py` | empty, only if the test layout needs it |
| `api/tests/stations/fast_path/test_fast_path_runner.py` | runner tests for AC2–AC5 (sqlite `uow_factory`, `FakeFusionClient` through `FusionScenario`) |
| `api/tests/stations/fast_path/test_role.py` | AC6 |

Not touched: `main.py`, lockfiles, `conftest.py`, s02 enums and `config_keys.py`, s11/s15/s17 files (consumed only), and Alembic.

## Design

### Inputs

- `resolution = await ctx.uow.repo(CustomerResolutionRepository).latest_for(item.id)` (s11). If it is missing, raise `StageError(ErrorCode.CUSTOMER_NOT_FOUND, {"reason": "no_resolution"})`. That can only happen after a manual re-drive that skipped resolve.
- `extraction = await current_extraction(ctx.uow, item.id)` (s10). This is the cleaned view: numbers trimmed and zero-amount lines dropped. If it is `None`, raise `StageError(ErrorCode.EXTRACTION_FAILED, {"reason": "no_extraction"})`.
- **Lookup lines** are `extraction.lines` sorted by `line_no`, with `kind in INVOICE_LIKE_KINDS` (s10) and a non-empty `transaction_number`. This matches s11's definition. Adjustment lines (BANK_FEE, TARIFF, DISCOUNT) don't take part and get no `LINE_RESULT`.
- **Transactions.** On the first attempt (`ctx.attempt == 0`), use `resolution.transactions`, so no second lookup is needed (s11 AC3). On any retry (`ctx.attempt > 0`, for example after a write-back failure), refetch with one batched `fusion.find_transactions(lookup numbers)`, because a balance may have reopened since. A `FusionError` becomes `StageError(e.code, {"op": "find_transactions", "fusion_code": e.fusion_code})`, the same mapping as s11.

### `match_line_transactions(lines, transactions) -> LineMatch` (pure)

For each lookup line, candidates are transactions whose `number.strip() == line.transaction_number`:
- INVOICE and CREDIT_MEMO lines prefer the same `TransactionKind`. If nothing of that kind matches, they use number-only matches. That tolerates a mislabelled kind; `kind` on the result comes from Fusion.
- An UNKNOWN line uses number-only matches.
- Exactly one candidate means matched. No candidate goes into `unmatched_line_nos`. More than one candidate (an invoice and a credit memo sharing a number) goes into `ambiguous_line_nos`.

`LineMatch` also dedupes transactions by `customer_trx_id`, because two lines can point at the same transaction.

### `find_closing_receipts(transactions, fusion, *, unmatched_line_nos=(), ambiguous_line_nos=()) -> ClosingReceipts`

1. If there are no transactions, or `unmatched_line_nos` or `ambiguous_line_nos` is non-empty, return `all_closed=False, complete=False` with **no Fusion call**.
2. If any transaction has `not money_eq(abs(balance), 0)`, return `all_closed=False, complete=False` listing `open_numbers`, with **no Fusion call**. All balances are checked before any applications are fetched.
3. Otherwise, for each transaction in `customer_trx_id` order, call `await fusion.list_transaction_applications(customer_trx_id)`. Active applications are those whose `status.upper()` is in `ACTIVE_APPLICATION_STATUSES = frozenset({"APP"})`. This is UNVERIFIED and fail-closed: an unknown status is not counted. A transaction's closing receipts are `{a.receipt_id for a in active}`. An empty set puts its number in `undetermined_numbers`.
4. `receipt_ids` is the union. `complete` is `all_closed and not undetermined_numbers and bool(receipt_ids)`. When `complete` is False, `receipt_ids` still reports what was found, for the history note. Callers act only on `complete`.
5. A `FusionError` from step 3 becomes `StageError(e.code, {"op": "list_transaction_applications", "customer_trx_id": id, "fusion_code": e.fusion_code})`, so transient errors retry through s18.

### `FastPathRunner.process(ctx)`

1. Load the inputs and get transactions as above. Run `match_line_transactions`, then `find_closing_receipts`.
2. **Not all closed:** return `Advance(Stage.MATCH_RECEIPT, note="fast path not taken: <n> of <m> transactions open/unmatched", payload={"fast_path": "not_eligible", "open": [...], "unmatched_line_nos": [...], "ambiguous_line_nos": [...]})`. There is no Fusion write and no `LINE_RESULT`.
3. **All closed but `complete` is False (AC3):** return `Advance(Stage.MATCH_RECEIPT, note="fast path not taken: closing receipt undetermined for <numbers>", payload={"fast_path": "undetermined", "undetermined": [...], "receipt_ids": [...]})`. There is no Fusion write.
4. **Complete:**
   1. For each `receipt_id` in sorted order, call `result = await write_back(ctx.uow, item, receipt_id, mode="already_applied")` (s17). Any `StageError` whose code is not already `WRITE_BACK_FAILED`, any `FusionError` and any other `Exception` from `write_back` are re-raised as `StageError(ErrorCode.WRITE_BACK_FAILED, {"receipt_id": id, "attached_receipt_ids": [done so far], "cause": <code or exception type name>, "stage": "FAST_PATH"})`. A `StageError(WRITE_BACK_FAILED)` from s17 is re-raised with `stage` and `attached_receipt_ids` merged into its detail. The runner then rolls back the outcome transaction and hands the error to s18, which retries the FAST_PATH stage (s17 is idempotent, so receipts already attached aren't re-attached) or escalates. No `LINE_RESULT`, `APPLICATION_LEDGER` or reservation is touched (AC4).
   2. After each successful call, record a `FUSION_WRITE` history row: `payload={"receipt_id", "mode": "already_applied", "note_written", "attachment_id"}`.
   3. For each matched line, `LineResultRepository.upsert(item.id, line.line_no, transaction_number=t.number, customer_trx_id=t.customer_trx_id, kind=t.kind.value, stated_amount=line.amount_paid, balance_before=t.balance, applied_amount=Decimal("0.00"), line_status=LineStatus.ALLOCATION_PREVIOUSLY_APPLIED, error_code=None, reason=f"closed by receipt(s) {ids}")` (s15).
   4. `status = roll_up(HeaderResult(customer_found=True, payment_date_present=item.payment_date is not None, receipt_found=True, applied_total=Decimal("0.00"), total_due=<sum of stated line amounts, 0 if none>), [ALLOCATION_PREVIOUSLY_APPLIED] * n)`. By s02's rule 1 this is `PAYMENT_PREVIOUSLY_APPLIED`. Assert that it is; anything else is a programming error, raised as `StageError(SYSTEM_DEAD_LETTER)`.
   5. Record a `DECISION` history row: `reasoning=closing_reason(...)`, which reads like "all 3 invoices already closed by receipts 500001, 500002; remittance attached". Its `payload={"fast_path": "taken", "receipt_ids": [...], "transactions": [{"line_no", "transaction_number", "customer_trx_id", "kind", "receipt_ids"}], "line_count": n}` (AC5).
   6. Return `Finish(status, note="already applied; remittance attached to <k> receipt(s)")`. s03 sets `STAGE=DONE, STATE=DONE, PAYMENT_STATUS`.

All DB writes from step 4 are in the outcome transaction, so the state change, history and line results commit together. Fusion writes come before that commit. A crash in between leaves the item claimed, and the retry re-runs `write_back` idempotently (see Risks).

## Interfaces provided (pinned)

```python
# cashapp/services/fast_path.py
ACTIVE_APPLICATION_STATUSES: Final[frozenset[str]] = frozenset({"APP"})   # UNVERIFIED; fail-closed

@dataclass(frozen=True, slots=True)
class LineTransaction:
    line_no: int
    line: ExtractedLine              # s08
    transaction: FusionTransaction   # s05

@dataclass(frozen=True, slots=True)
class LineMatch:
    matched: tuple[LineTransaction, ...]        # by line_no
    unmatched_line_nos: tuple[int, ...]
    ambiguous_line_nos: tuple[int, ...]
    def transactions(self) -> list[FusionTransaction]   # deduped by customer_trx_id, sorted by it

def match_line_transactions(lines: Sequence[ExtractedLine],
                            transactions: Sequence[FusionTransaction]) -> LineMatch

@dataclass(frozen=True, slots=True)
class ClosingReceipts:
    receipt_ids: set[int]
    complete: bool                                   # True only when the fast path may be taken
    all_closed: bool = False
    by_transaction: Mapping[int, tuple[int, ...]] = field(default_factory=dict)   # customer_trx_id -> receipt ids
    open_numbers: tuple[str, ...] = ()
    undetermined_numbers: tuple[str, ...] = ()

async def find_closing_receipts(transactions: Sequence[FusionTransaction], fusion: FusionClient, *,
                                unmatched_line_nos: Sequence[int] = (),
                                ambiguous_line_nos: Sequence[int] = ()) -> ClosingReceipts
    # raises StageError(e.code, ...) for a FusionError; never a raw FusionError

def closing_reason(match: LineMatch, closing: ClosingReceipts) -> str

# cashapp/stations/fast_path/runner.py
class FastPathRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.FAST_PATH
    def __init__(self, deps: RunnerDeps, *, fusion: FusionClient) -> None
    async def process(self, ctx: StageContext) -> StageOutcome
        # Advance(MATCH_RECEIPT, payload={"fast_path": "not_eligible"|"undetermined", ...})
        # | Finish(PAYMENT_PREVIOUSLY_APPLIED)
def build(container: Container) -> Runnable      # StageConsumer(FastPathRunner(RunnerDeps.from_container(c),
                                                 #   fusion=c.resolve(FusionClient)), c.bus, consumer_group)
ROLE: RoleSpec = RoleSpec("fast-path", "consumer", build)
```

The effects on the work item that dependents rely on (s19, s20, s41):
- When the fast path is taken: `PAYMENT_STATUS = payment-previously-applied`, `STATE = DONE`, one `LINE_RESULT` per lookup line with `allocation-previously-applied` and `applied_amount = 0`, one FUSION_WRITE history row per receipt, and one DECISION row.
- When it isn't taken: the history payload has `fast_path` set to `"not_eligible"` or `"undetermined"`. s41 can count fast-path hits from that key.

## Consumed interfaces (code against these; merger reconciles)

- s11: `CustomerResolutionRepository.latest_for(item_id) -> CustomerResolution | None`, `CustomerResolution.transactions`.
- s10: `current_extraction(uow, item_id)`, `INVOICE_LIKE_KINDS`.
- s05: `FusionClient.list_transaction_applications`, `find_transactions`, `FusionError`, `FakeFusionClient`, `FusionScenario.application(...)`.
- s17: `write_back(uow, item, receipt_id, *, mode: Literal["applied","already_applied"]) -> WriteBackResult{note_written: bool, attachment_ref: AttachmentRef | None}` from `cashapp/services/write_back.py`. If s17's pinned plan adds keyword-only dependencies (fusion, object store, config, clock), the runner passes them from `ctx` and from its own `build` (`c.resolve(ObjectStore)`). That adds a constructor keyword, not a second write path.
- s15: `LineResultRepository.upsert(item_id, line_no, **cols)` with the AC2 column names in lower case.
- s02: `roll_up`, `HeaderResult`, `LineStatus`, `PaymentStatus`, `money_eq`, `record_history`, `HistoryEntry`, `HistoryAction`.
- s03: `StageRunner`, `StageContext`, `Advance`, `Finish`, `StageError`, `RunnerDeps`, `StageConsumer`, `RoleSpec`.

## Migrations

None. `LINE_RESULT` belongs to s15. This story adds no table, column or revision, so it doesn't move the Alembic head.

## TEST PLAN (written and run in step 5 only)

Unit tests use `FakeFusionClient` built from `FusionScenario`. Runner tests use the s02 sqlite `uow_factory`, s03's `make_runner_deps` and `run_stage_once`, and a stub `write_back` patched at `cashapp.stations.fast_path.runner.write_back`, so the test asserts the call contract without depending on s17's internals. One test uses the real s17 `write_back` with the fake once both have merged.

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `api/tests/services/test_fast_path.py::test_all_closed_returns_closing_receipts_complete` | 2 invoices at balance 0 with applications from R1 and R2 → `receipt_ids == {R1, R2}`, `complete`, and `by_transaction` mapped |
| 1 | `…::test_any_open_balance_not_closed_and_no_application_lookup` | 1 open invoice → `all_closed=False`, `complete=False`, and `fake.calls` has no `list_transaction_applications` |
| 1 | `…::test_credit_memo_zero_balance_sign_aware` | A credit memo at `-0.00` or `-0.004` counts as closed; at `-5.00` it is open |
| 1 | `…::test_unmatched_or_ambiguous_line_not_eligible` | A line with no transaction, or a number shared by an invoice and a credit memo on an UNKNOWN line → not complete, with no Fusion call |
| 1 | `…::test_no_active_application_marks_undetermined` | Balance 0, but the only application is `REVERSED` (or there are none) → `complete=False`, number in `undetermined_numbers` |
| 1 | `…::test_unknown_application_status_fail_closed` | Status `"XYZ"` is not counted |
| 1 | `…::test_fusion_error_becomes_stage_error` | `fail_next("list_transaction_applications", FusionError(FUSION_TRANSIENT))` → `StageError(FUSION_TRANSIENT)` with `op` in the detail |
| 1 | `…::test_match_line_transactions_prefers_kind_and_dedupes` | Kind-preferred match, number-only fallback, two lines on one transaction deduped |
| 2 | `api/tests/stations/fast_path/test_fast_path_runner.py::test_not_all_closed_advances_to_match_receipt_without_write` | `Advance(MATCH_RECEIPT)`, `write_back` not called, no `LINE_RESULT` rows, no Fusion write in `fake.calls`, item `stage=MATCH_RECEIPT state=PENDING` with an outbox event |
| 2 | `…::test_all_closed_writes_back_each_receipt_and_finishes_previously_applied` | `write_back` called once per receipt with `mode="already_applied"`; `Finish`; item `STAGE=DONE STATE=DONE PAYMENT_STATUS=payment-previously-applied`; every lookup line has `LINE_RESULT.line_status == allocation-previously-applied` with `applied_amount == 0`; adjustment lines have no row; one FUSION_WRITE history row per receipt |
| 2 | `…::test_real_write_back_attaches_to_fake_receipt` | With s17's real `write_back` and the fake: `fake.attachments(R1)` has one entry and `fake.comments(R1)` contains "already applied". Skipped until s17 is importable. |
| 2 | `…::test_retry_refetches_transactions` | With `attempt > 0`, `find_transactions` is called once. A balance that has reopened → `Advance(MATCH_RECEIPT)` |
| 3 | `…::test_undetermined_closing_receipt_falls_through_with_note` | Balance 0 and no receipt application → `Advance(MATCH_RECEIPT)`; the STAGE_TRANSITION history `reasoning` names the undetermined number; payload `fast_path == "undetermined"`; no `write_back` call |
| 4 | `…::test_write_back_failure_raises_write_back_failed_without_line_results` | Stub raises `FusionError(FUSION_TRANSIENT)` on the second receipt → the failure handler gets `StageError(WRITE_BACK_FAILED)` with `attached_receipt_ids=[R1]`; item not DONE; `LINE_RESULT` empty; no apply call in `fake.calls`; `last_error_code == WRITE_BACK_FAILED` |
| 4 | `…::test_write_back_disabled_escalates` | Fake with `WriteGuard(write_enabled=False)` and the real s17 `write_back` (or a stub raising `StageError(WRITE_BACK_FAILED, {"cause": "FUSION_WRITE_DISABLED"})`) → escalated by the default handler; `PAYMENT_STATUS` not set |
| 5 | `…::test_decision_history_records_receipts_and_reason` | One DECISION row; reasoning starts "all 2 invoices already closed by receipts"; payload has `receipt_ids` and per-transaction `receipt_ids`; no payer name in the payload |
| 5 | `api/tests/services/test_fast_path.py::test_closing_reason_text` | Deterministic text, receipt ids sorted, correct invoice/credit-memo counts |
| 6 | `api/tests/stations/fast_path/test_role.py::test_role_spec` | `ROLE.name == "fast-path"`, `kind == "consumer"`, `ROLE.build(FakeContainer(...register FusionClient))` returns a `StageConsumer` whose runner stage is `FAST_PATH` |

## Risks

- **Closing-receipt evidence is UNVERIFIED.** The `list_transaction_applications` field shape and the active status value (`"APP"`) come from s05's fake. If the real pod reports applications differently, the fast path falls through (fail-closed). It never mis-attaches. Confirm on the dev pod when credentials exist.
- **Credit memos closed against an invoice, not a receipt,** have no receipt application. Under AC1 as written they make the item undetermined, so it falls through. That's safe, but it lowers the hit rate on remittances that include credit memos. A follow-up could exempt zero-balance credit memos when at least one invoice has a determined receipt. That needs Jonathan's ruling.
- **Fusion write before DB commit.** If the process dies after `write_back` but before the outcome commit, the claim expires and the item re-runs FAST_PATH. That depends on s17's idempotency: the attachment title is checked by a list call, and the note is appended only when the marker is missing. If s17 relies only on the history `attachment_ref`, which is rolled back here, a duplicate attachment is possible. The merger must confirm that s17 checks Fusion.
- **s17 signature drift.** s17 is in the same wave and its plan isn't written yet. The call site is one line. Extra keyword-only dependencies are threaded through `build` (see Consumed interfaces).
- **Stale resolution transactions on the first attempt.** A reversal in the seconds between resolve and fast path can't be excluded. The worst case is a note and attachment on a receipt that has just been unapplied, with no money moved. Retries always refetch.
- **Several receipts closed one invoice.** The remittance is attached to each of them, per the story's assumption.

## Assumptions and deviations

- **D1.** `find_closing_receipts` takes the keyword-only arguments `unmatched_line_nos` and `ambiguous_line_nos`, so that "every line's transaction was found" is enforced inside the AC1 function. `ClosingReceipts` gains the defaulted fields `all_closed`, `by_transaction`, `open_numbers` and `undetermined_numbers`, so the AC1 shape is a subset.
- **D2.** Lines come from s10's `current_extraction` (the cleaned view), not from the raw adjudication. Zero-amount lines are already dropped, and only invoice-like lines with a transaction number take part, the same set s11 looks up.
- **D3.** An UNKNOWN-kind line matching both an invoice and a credit memo is ambiguous, so the item falls through.
- **D4.** The payment status comes from `roll_up` rather than being hard-coded, and is asserted to equal `PAYMENT_PREVIOUSLY_APPLIED`.
- **D5.** A write-back failure keeps the item at FAST_PATH, so s18's retry re-runs this stage. It isn't advanced to WRITE_BACK, because s17's `WriteBackRunner` uses `mode="applied"`.
