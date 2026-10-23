# s15-line-matching-apply: plan

Issue #15. Wave 5, the money path. Paths: `cashapp/` = `api/src/cashapp/`. No UI and no LLM in this story, so `python-llm-features`, `claude-api` and `nextjs-fullstack-standards` don't apply. The skill loaded is `python-web-app:building-python-web-apps`.

## Standards followed

- **CLAUDE.md layering.**
  - `services/matching/lines.py` is pure: no I/O, no SQLAlchemy, no Fusion client.
  - The stations orchestrate. Only `data/repositories/applications.py` touches the ORM.
  - Routers aren't touched.
- **CLAUDE.md *Lines* and *Idempotency*:**
  - credit memos first
  - zero-amount lines rejected
  - amount capped at `min(stated, balance, receipt remaining)`
  - currency and status checked
  - repeated invoices deduplicated
  - Fusion's existing applications checked before every apply
  - each line persisted as it happens
- **Reference doc §3:**
  - apply by ID (`ReceiptId`, `CustomerTrxId`), with a signed amount
  - accounting date = the later of payment date and today
  - parse fail-closed (s05 owns the parsing; this story trusts `ApplyResult.ok` only)
- **Reference doc §4 defects fixed here:** the missing cap, the missing idempotency and the dishonest roll-up. The roll-up comes only from s02's `roll_up`.
- **Shared code, imported and never re-implemented:**
  - s02: one status enum, one error-code enum, `to_money`/`money_eq`, `record_history`
  - s03: one `StageRunner` and `consumer_role`
  - s05: `accounting_date_for`, `WriteGuard`
- **Money** is `Decimal` (`to_money`, `ROUND_HALF_UP`), equality is `money_eq`, and every amount is stored as `MoneyNumeric`.
- **No PII in logs or `StageError.detail`:** only IDs, codes, amounts and line numbers. No payer names or artifact text.
- **Code gates during coding:** `uv run ruff check . && uv run ruff format --check .`, `uv run pyright` (strict on `src/`).

## Files to touch

All files are new, and none is owned by another story.

| Path | Content |
|---|---|
| `api/src/cashapp/services/matching/__init__.py` | Empty. s13 may create the same empty file; the merger keeps one. |
| `api/src/cashapp/services/matching/lines.py` | `plan_lines`, `index_transactions`, `reconcile_ledger`, `apply_outcome_status`, `is_active_application`, `OPEN_TRANSACTION_STATUSES`, and the dataclasses below. Pure. |
| `api/src/cashapp/domain/ledger.py` | `LedgerStatus` StrEnum and `idempotency_key()`. Kept in the domain so routers and reporting (s19, s20, s41) need no SQLAlchemy. |
| `api/src/cashapp/data/models/applications.py` | ORM models `LineResult` (`line_result`) and `ApplicationLedger` (`application_ledger`). `load_all_models()` picks them up, so `models/__init__.py` isn't edited. |
| `api/src/cashapp/data/repositories/applications.py` | `LineResultRepository`, `ApplicationLedgerRepository`. |
| `api/alembic/versions/s15_line_result_ledger.py` | One hand-written revision. See *Migrations*. |
| `api/src/cashapp/stations/match_lines/__init__.py` | Empty. |
| `api/src/cashapp/stations/match_lines/runner.py` | `MatchLinesRunner`. |
| `api/src/cashapp/stations/apply/__init__.py` | Empty. |
| `api/src/cashapp/stations/apply/runner.py` | `ApplyRunner`, `apply_one` (the seam s35 and s39 edit). |
| `api/src/cashapp/stations/apply/roles.py` | `ROLES` for both stations (AC8). It's the only module here that defines `ROLE` or `ROLES`, so s30's discovery sees each name once. |
| `api/tests/support/applications.py` | `seed_apply_item(...)`, `make_line(...)`, `KillAfterApplies` (a fake wrapper). |
| `api/tests/unit/services/matching/test_lines.py` | AC1 tests. |
| `api/tests/integration/data/test_applications_repository.py` | AC2 tests on SQLite. |
| `api/tests/integration/data/test_applications_migration_atp.py` | AC2 test on ATP (`-m atp`, skipped without `CASHAPP_TEST_ATP=1`). |
| `api/tests/integration/stations/test_match_lines_runner.py` | AC3 tests. |
| `api/tests/integration/stations/test_apply_runner.py` | AC4 tests. |
| `api/tests/unit/stations/test_apply_faults.py` | AC5 and AC7 tests. |
| `api/tests/unit/stations/test_apply_rollup.py` | AC6 tests. |
| `api/tests/unit/stations/test_apply_roles.py` | AC8 test. |

Not touched:
- `main.py`, the lockfiles, `tests/conftest.py`, `models/__init__.py`
- s02's `status.py`, `error_codes.py` and `work_item.py`
- s05's `integrations/fusion/*`
- s13's `reservations.py`
- s30's `apply_gate.py`
- s40's `locking.py`

## Design

### Pure planning (`services/matching/lines.py`)

```python
OPEN_TRANSACTION_STATUSES: Final = frozenset({"OPEN", "COMPLETE"})   # compared upper-cased; VERIFY values on the pod
INACTIVE_APPLICATION_STATUSES: Final = frozenset({"REVERSED", "UNAPP"})
APPLICABLE_LINE_KINDS: Final = frozenset({LineKind.INVOICE, LineKind.CREDIT_MEMO, LineKind.UNKNOWN})   # = s10 INVOICE_LIKE_KINDS
```

`plan_lines` checks each invoice-like line in this order and returns the **first** verdict that applies:

1. **Zero amount.** The stated amount is present and `money_eq(amount, 0)`: `ALLOCATION_ZERO_AMOUNT`, `ZERO_AMOUNT_LINE`.
2. **Not found.** The number is not in `transactions`: `ALLOCATION_INVOICE_NOT_FOUND`, `INVOICE_NOT_FOUND`. If the number is in `ambiguous`, the reason is "ambiguous transaction number".
3. **No bill-to.** `bill_to_customer_number` is None: `ALLOCATION_CUSTOMER_NOT_FOUND`, `CUSTOMER_NOT_FOUND`.
   - Additive, when `owners` is given: a bill-to outside `owners` gets the same status, with reason "bill-to outside anchor/related". See *Assumptions*.
4. **Currency mismatch.** Transaction currency ≠ `payment_currency`: `ALLOCATION_APPLY_FAILED`, `INVOICE_CURRENCY_MISMATCH`.
5. **Status.** `status.upper()` is not in `OPEN_TRANSACTION_STATUSES`: `ALLOCATION_APPLY_FAILED`, `INVOICE_STATUS_INVALID`.
6. **No remaining balance.** For an invoice, `balance <= 0.005`; for a credit memo, `balance >= -0.005`: `ALLOCATION_NO_REMAINING_BALANCE`, `INVOICE_CLOSED`.
7. **Already applied.** Any active application in `existing` with this `customer_trx_id` (this receipt's applications): `ALLOCATION_PREVIOUSLY_APPLIED`, no error code.
8. Otherwise the line is valid and gets a step.

**Dedupe.** It runs before the verdicts. Lines are grouped by the resolved `customer_trx_id`, or by `transaction_number.strip().upper()` when the number isn't found.
- The lowest `line_no` is the primary.
- The amount is the sum when every member states one, otherwise the primary's.
- Each other member gets a `LineResultDraft` that carries `merged_into=<primary>` and is given the primary's final status after apply.
- `LinePlan.duplicates` records `{primary: (others…)}`.

**Order and amounts.** Valid lines are sorted by `(0 if CREDIT_MEMO else 1, line_no)`. `remaining` starts at `receipt_remaining`.
- **Credit memo:**
  - `abs_amt = min(abs(stated) or abs(balance), abs(balance))`
  - `step.amount = -abs_amt`
  - `remaining += abs_amt`
- **Invoice:**
  - `amount = min(stated_or_balance, balance, remaining)`
  - `remaining -= amount`
  - `amount <= 0.005` (the receipt is exhausted) gives `ALLOCATION_APPLY_FAILED` + `AMOUNT_VARIANCE`, reason "receipt exhausted".
- **No stated amount:** the full balance is allowed only when the header reconciles: `header_amount` is given, `expected = Σ stated amounts (credit memos negative) + Σ balances of amountless lines`, and `|header_amount − expected| ≤ tolerance`. Otherwise the line gets `ALLOCATION_APPLY_FAILED` + `AMOUNT_VARIANCE`, reason "no line amount and header does not reconcile".
- **Target status:**
  - amount capped below stated (by balance or remaining) → `ALLOCATION_APPLIED_LESS_THAN_INSTRUCTION`
  - else `abs(amount) < abs(balance)` → `ALLOCATION_APPLIED_SHORT_PAY`
  - else `ALLOCATION_APPLIED`

**Non-invoice lines.** `BANK_FEE`, `TARIFF` and `DISCOUNT` lines produce no step and no draft. `LinePlan.ignored_line_nos` lists them for the history payload.

**`reconcile_ledger(rows, existing)`** is pure.
- Input: ledger rows with status PLANNED, or FAILED with `ERROR_CODE in {FUSION_ALREADY_APPLIED, FUSION_TRANSIENT}`.
- A row reconciles when there's an active application with the same `(receipt_id, customer_trx_id)` whose `application_id` isn't already claimed by an APPLIED ledger row.
- Output: `list[Reconciliation{ledger_id, application_id, amount_applied}]`.

### `MatchLinesRunner` (stage MATCH_LINES)

1. **Reservation.** `ReservationRepository.active_for_item(item.id)` (s13). If there's none, return `Advance(MATCH_RECEIPT, note="no active reservation")`. Otherwise `receipt_id`/`receipt_number` come from it.
2. **Inputs.**
   - `extraction = current_extraction(uow, item.id)` (s10's cleaned view). None → `StageError(EXTRACTION_FAILED)`.
   - `resolution = CustomerResolutionRepository.latest_for(item.id)` (s11). None → `StageError(CUSTOMER_NOT_FOUND)`.
3. **Fresh Fusion data**, one call each:
   - `find_transactions(unique numbers of applicable lines)`
   - `get_receipt(receipt_id)`, for `unapplied_amount` and currency
   - `list_receipt_applications(receipt_id)`

   A `FusionError` becomes `StageError(e.code, {"receipt_id", "op"})`.
4. **Reconcile on re-entry.**
   - `reconcile_ledger(ledger rows for item, existing)` → `mark(row, APPLIED, fusion_application_id, amount, applied_at, applied_by="system")`.
   - The matching `LINE_RESULT` gets its stored target status (`ALLOCATION_APPLIED*`).
   - One `DECISION` history row: `error_code=FUSION_ALREADY_APPLIED`, reasoning "reconciled against existing Fusion application", payload `{ledger_id, application_id}`.
5. **Plan.**
   - Lines whose ledger row is already APPLIED are excluded.
   - `transactions, ambiguous = index_transactions(found, lines, owners=resolution.owners())`.
   - `plan_lines(...)` is called with:
     - `existing` minus the application IDs owned by APPLIED ledger rows
     - `payment_currency = item.currency or receipt.currency`
     - `header_amount = item.payment_amount or extraction.payment_amount.value`
     - `tolerance = config.matching().tolerance_for(currency)`
     - `owners = resolution.owners()`
6. **Persist,** with no commit; the runner's outcome transaction commits.
   - `ApplicationLedgerRepository.upsert_planned(...)` for each step: amount, `apply_seq`, `discount_amount=step.discount`, and `REQUEST` set to None until apply.
   - Any PLANNED row for this item that is no longer in the plan → `mark(FAILED, error_code=None, reason="dropped on re-plan")`.
   - `LineResultRepository.upsert(...)` for every draft and step. A step gets `LINE_STATUS=None` (meaning pending apply) and `TARGET_STATUS` = the planned status.
   - One `DECISION` history row with the plan summary: counts, `ignored_line_nos`, `duplicates`, `receipt_remaining`.
7. **Outcome.** `Advance(APPLY, payload={"receipt_id": ..., "planned": n})`.

`index_transactions(found, lines, owners)` picks one transaction per number:
- If there's exactly one, use it.
- If there are several, prefer the kind that matches `line.kind` (CREDIT_MEMO → CREDIT_MEMO, INVOICE → INVOICE), then bill-to in `owners`.
- If it's still more than one, the number goes in `ambiguous` and is absent from the mapping.

### `ApplyRunner` (stage APPLY)

```python
class ApplyRunner(StageRunner):
    stage = Stage.APPLY
    def __init__(self, deps: RunnerDeps, *, fusion: FusionClient, gate: ReceiptApplyGate, guard: WriteGuard) -> None
    @classmethod
    def build(cls, c: Container) -> Self
        # fusion=c.resolve(FusionClient), gate=c.resolve(ReceiptApplyGate),
        # guard=WriteGuard.from_settings(c.settings, fusion.pod_name)
```

1. **Write guard first (AC7).** Call `guard.check("apply_receipt")`. On `FusionError(FUSION_WRITE_DISABLED)`, raise `StageError(FUSION_WRITE_DISABLED)` before any Fusion call. That code is POLICY and not retryable, so the default handler and s18 escalate it.
2. **Inputs.**
   - The reservation (none → `StageError(RECEIPT_NOT_YET_AVAILABLE)`).
   - `receipt = fusion.get_receipt(receipt_id)`.
   - `payment_date = item.payment_date or extraction.payment_date.value` (none → `StageError(MISSING_PAYMENT_DATE)`).
   - `today = ctx.clock.now().date()`.
   - `floor = item.fix_hints.get("gl_date_floor")`.
   - `accounting_date = max(accounting_date_for(payment_date, today), floor or date.min)`. `application_date` uses the same value.
3. **For each row in `ledger.planned_for(item.id)`**, in `apply_seq` order, call `apply_one(...)`:
   1. Enter `async with gate.slot(receipt_id):`.
   2. **Lock and claim heartbeat.** `ledger.reload_item(item)` (a `SELECT … FOR UPDATE` refresh). If `is_locked_for_automation(item, now)`, `ctx.uow.commit()` and raise `StageError(FUSION_LOCKED, {"cause": "item_locked", "ledger_id"})`. The runner's failure path then releases the claim: the decision sets the state off IN_PROGRESS, and the s03 claim skips the item while the lock is live. Otherwise set `item.claim_expires_at = now + claim_ttl`, so a long remittance never loses its claim mid-loop.
   3. **Idempotency.** Call `existing = fusion.list_receipt_applications(receipt_id)`. If there's an active application for `row.customer_trx_id` not owned by another APPLIED row: `mark(APPLIED, fusion_application_id, amount=fusion amount)`, `LINE_RESULT ← target status`, history `FUSION_WRITE` "already present; not re-applied", commit, and move to the next row. **No apply call is made.**
   4. **Apply.** Build `ApplyRequest(receipt_id, row.customer_trx_id, row.amount, receipt.currency, accounting_date, accounting_date, discount_amount=row.discount_amount)` and store it as `REQUEST` JSON. Then call `apply_receipt`.
   5. **Classify the result:**
      - `ok` → `APPLIED` (`fusion_application_id`, `applied_at=now`, `applied_by="system"`, `RESPONSE_MESSAGES`). `LINE_RESULT`: `LINE_STATUS` = target, `APPLIED_AMOUNT`, `RESIDUAL = stated − applied` (None when nothing was stated). A `FUSION_WRITE` history row (ids, amount, accounting date).
      - fault code in `{FUSION_OVERAPPLY, FUSION_ALREADY_APPLIED, FUSION_GL_DATE}` → the row stays PLANNED with `ERROR_CODE` and response saved, commit, then raise `StageError(code, {"ledger_id", "line_no", "receipt_id", "customer_trx_id", "fusion_code", "accounting_date"})`. s18 reroutes it (MATCH_LINES, MATCH_LINES, APPLY+`gl_date_floor`).
      - fault `FUSION_LOCKED` / `FUSION_TRANSIENT`, or a raised `FusionError` with `retryable` or `outcome_unknown` → the row stays PLANNED (`ERROR_CODE` set), commit, raise `StageError(code)`. The retry resumes at the first non-APPLIED row, and step 3 catches an apply whose outcome was unknown.
      - a raised `FusionError(FUSION_WRITE_DISABLED)` → commit, raise `StageError(FUSION_WRITE_DISABLED)`.
      - any other fault (`FUSION_FAULT`, `FUSION_DISCOUNT_REJECTED`, …) → `FAILED` with `ERROR_CODE`. `LINE_RESULT` gets `ALLOCATION_APPLY_FAILED`, `ERROR_CODE` and `REASON = fault.message[:500]`. Commit and **continue**.
   6. Each line ends with `await ctx.uow.commit()`, so the ledger row, `LINE_RESULT`, history and claim heartbeat land in one transaction per line.
4. **After the loop (AC6).**
   - Duplicate lines that were merged get their primary's final status.
   - `statuses = [r.line_status for r in line_results.for_item(item.id) if r.line_status]`.
   - `header = HeaderResult(customer_found=True, payment_date_present=True, receipt_found=True, applied_total=Σ signed APPLIED ledger amounts, total_due=header payment amount, else Σ signed stated amounts)`.
   - `item.payment_status = roll_up(header, statuses)`.
   - `ReservationRepository.consume(item.id)`.
   - A `DECISION` history row: payload `{"lines": [{line_no, transaction_number, status, applied, error_code}], "applied_total", "payment_status"}`.
   - Return `Advance(WRITE_BACK)`.

`apply_one(ctx, row, *, fusion, receipt, accounting_date, ...) -> None` is a module-level coroutine. s35 adds its dry-run branch there, and s39 sets `discount_amount` there. Neither needs to restructure the loop.

### Repositories (`data/repositories/applications.py`)

- Every method only flushes. Nothing commits.
- `upsert` looks up by `(work_item_id, line_no)`; it updates when found, otherwise it adds.
- `upsert_planned`:
  - Looks up by idempotency key and leaves an APPLIED row untouched (returns it).
  - Resets a FAILED or PLANNED row to PLANNED with the new amount and seq.
  - When the key's row is REVERSED (s38), creates a new row keyed `f"{base}#{n}"`, with n = the count of rows sharing the base.
- `reload_item(item)` is `session.refresh(item, with_for_update=True)`. It lives here so stations never touch the session.

## Interfaces provided (pinned)

```python
# cashapp/domain/ledger.py
class LedgerStatus(StrEnum): PLANNED="PLANNED"; APPLIED="APPLIED"; FAILED="FAILED"; REVERSED="REVERSED"; DRY_RUN="DRY_RUN"
def idempotency_key(item_id: int, receipt_id: int, customer_trx_id: int) -> str   # f"{item_id}:{receipt_id}:{customer_trx_id}"
APPLIED_BY_SYSTEM: Final = "system"

# cashapp/services/matching/lines.py
@dataclass(frozen=True, slots=True)
class LineStep:
    line_no: int
    transaction: FusionTransaction            # s05
    amount: Decimal                           # signed: negative for credit memos; never zero
    kind: TransactionKind                     # s05
    target_status: LineStatus                 # APPLIED | APPLIED_SHORT_PAY | APPLIED_LESS_THAN_INSTRUCTION
    stated_amount: Decimal | None
    balance_before: Decimal
    merged_line_nos: tuple[int, ...] = ()
    discount: Decimal | None = None           # s39 fills it; s15 always None

@dataclass(frozen=True, slots=True)
class LineResultDraft:
    line_no: int
    line_status: LineStatus
    reason: str
    error_code: ErrorCode | None = None
    transaction_number: str = ""
    customer_trx_id: int | None = None
    stated_amount: Decimal | None = None
    balance_before: Decimal | None = None
    merged_into: int | None = None            # dedupe: final status copied from this primary line

@dataclass(frozen=True, slots=True)
class LinePlan:
    steps: list[LineStep]                     # credit memos first, then invoices; stable by (kind, line_no)
    results: list[LineResultDraft]            # non-applicable verdicts + merged duplicates
    receipt_remaining_after: Decimal
    duplicates: dict[int, tuple[int, ...]]
    ignored_line_nos: tuple[int, ...]         # BANK_FEE / TARIFF / DISCOUNT

def plan_lines(lines: Sequence[ExtractedLine], transactions: Mapping[str, FusionTransaction],
               receipt_remaining: Decimal, existing: Sequence[FusionApplication], payment_currency: str, *,
               header_amount: Decimal | None = None, tolerance: Decimal = Decimal("0.00"),
               owners: Collection[str] | None = None, ambiguous: Collection[str] = ()) -> LinePlan
    # keys of `transactions` are transaction_number.strip().upper()
def index_transactions(found: Sequence[FusionTransaction], lines: Sequence[ExtractedLine],
                       owners: Collection[str]) -> tuple[dict[str, FusionTransaction], frozenset[str]]
def is_active_application(a: FusionApplication) -> bool
@dataclass(frozen=True, slots=True)
class Reconciliation: ledger_id: int; application_id: int; amount_applied: Decimal
def reconcile_ledger(rows: Sequence[LedgerRowView], existing: Sequence[FusionApplication]) -> list[Reconciliation]
class LedgerRowView(Protocol):   # satisfied by the ORM row; keeps lines.py ORM-free
    id: int; receipt_id: int; customer_trx_id: int; status: LedgerStatus
    error_code: ErrorCode | None; fusion_application_id: int | None
```

```python
# cashapp/data/models/applications.py
class LineResult(Base):                       # table line_result -> LINE_RESULT
    id: int (identity_pk); work_item_id: int (FK work_item.id, FK_LINE_RESULT_WI, not null); line_no: int
    transaction_number: str | None (String(100)); customer_trx_id: int | None (BigInteger)
    kind: str | None (String(20): INVOICE | CREDIT_MEMO | UNKNOWN)
    stated_amount, balance_before, applied_amount, discount_amount, residual: Decimal | None (MoneyNumeric)
    line_status: LineStatus | None (StrEnumType)       # None = planned, apply pending
    target_status: LineStatus | None (StrEnumType)     # additive: status apply will write on success
    merged_into: int | None                            # additive: dedupe primary line_no
    error_code: ErrorCode | None (StrEnumType); reason: str | None (String(1000))
    updated_at: datetime (UtcDateTime, default/onupdate utcnow)
    # UQ_LINE_RESULT_ITEM_LINE (work_item_id, line_no)

class ApplicationLedger(Base):                # table application_ledger -> APPLICATION_LEDGER
    id: int (identity_pk); work_item_id: int (FK, FK_APP_LEDGER_WI); line_no: int
    receipt_id: int (BigInteger); receipt_number: str | None (String(100))   # additive: s38 confirmation
    customer_trx_id: int (BigInteger); apply_seq: int                       # additive: apply order
    amount: Decimal (MoneyNumeric, signed); discount_amount: Decimal | None (MoneyNumeric)
    idempotency_key: str (String(120), UQ_APP_LEDGER_IDEM_KEY)
    status: LedgerStatus (StrEnumType); fusion_application_id: int | None (BigInteger)
    error_code: ErrorCode | None; request: dict | None (JsonDoc); response_messages: list | None (JsonDoc)
    applied_at: datetime | None; applied_by: str | None (String(255))
    reversed_at: datetime | None; reversed_by: str | None (String(255)); reversal_reason: str | None (String(1000))
    created_at, updated_at: datetime (UtcDateTime)
    # IX_APP_LEDGER_ITEM_STATUS (work_item_id, status); IX_APP_LEDGER_RECEIPT (receipt_id)

# cashapp/data/repositories/applications.py
class LineResultRepository(BaseRepository[LineResult]):
    async def upsert(self, item_id: int, line_no: int, **cols: Any) -> LineResult    # unknown col -> AttributeError
    async def for_item(self, item_id: int) -> list[LineResult]                       # ordered line_no
class ApplicationLedgerRepository(BaseRepository[ApplicationLedger]):
    async def planned_for(self, item_id: int) -> list[ApplicationLedger]             # STATUS=PLANNED, ordered apply_seq, id
    async def mark(self, row: ApplicationLedger, status: LedgerStatus, **cols: Any) -> ApplicationLedger
    async def for_item(self, item_id: int) -> list[ApplicationLedger]                # all statuses, ordered apply_seq, id
    async def upsert_planned(self, item_id: int, *, line_no: int, receipt_id: int, receipt_number: str | None,
                             customer_trx_id: int, amount: Decimal, apply_seq: int,
                             discount_amount: Decimal | None = None) -> ApplicationLedger
    async def applied_for(self, item_id: int) -> list[ApplicationLedger]             # STATUS=APPLIED (s38, s17)
    async def reload_item(self, item: WorkItem) -> WorkItem                           # refresh FOR UPDATE (stations' lock re-check)
```

```python
# cashapp/stations/match_lines/runner.py
class MatchLinesRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.MATCH_LINES
    def __init__(self, deps: RunnerDeps, *, fusion: FusionClient) -> None
    @classmethod
    def build(cls, c: Container) -> Self                       # fusion=c.resolve(FusionClient)
    async def process(self, ctx: StageContext) -> StageOutcome # Advance(APPLY, payload={"receipt_id", "planned"})

# cashapp/stations/apply/runner.py
class ApplyRunner(StageRunner):                                # signature in Design
    stage: ClassVar[Stage] = Stage.APPLY
    async def process(self, ctx: StageContext) -> StageOutcome # Advance(WRITE_BACK)
async def apply_one(ctx: StageContext, row: ApplicationLedger, *, fusion: FusionClient, gate: ReceiptApplyGate,
                    receipt: FusionReceipt, accounting_date: date, claim_ttl: timedelta) -> None   # s35/s39 seam

# cashapp/stations/apply/roles.py
ROLES: list[RoleSpec] = [consumer_role(MatchLinesRunner), consumer_role(ApplyRunner)]   # names "match-lines", "apply"
```

**StageError contracts for s18:**
- `FUSION_OVERAPPLY` and `FUSION_ALREADY_APPLIED` → `Reroute(MATCH_LINES)`. Detail: `{ledger_id, line_no, receipt_id, customer_trx_id, fusion_code, accounting_date}`.
- `FUSION_GL_DATE` → `Reroute(APPLY)` with `gl_date_floor`. The detail has the same keys, plus `receipt_gl_date` only when the fault text yields one. Otherwise s18 must decide the floor.
- `FUSION_LOCKED` with `detail.cause == "item_locked"` means a person holds the lock. s18 must treat it as a no-op (no escalation needed).
- `FUSION_WRITE_DISABLED` → escalate.

**Effects on `WORK_ITEM` that dependents rely on:** `PAYMENT_STATUS` is set before `Advance(WRITE_BACK)`, and s17 finishes with it.

## Migrations

- One revision, `api/alembic/versions/s15_line_result_ledger.py`, `revision = "s15_line_result_ledger"`, hand-written.
- **Expected parent:** s13's `RECEIPT_RESERVATION`/`MATCH_CANDIDATE` revision, the head when s13 merges first. There's no FK into s13's tables, so any single head works. The merger re-points `down_revision` and checks that `alembic heads` returns one head.
- **Upgrade:**
  - `LINE_RESULT` and `APPLICATION_LEDGER` as above:
    - identity PKs
    - `NUMBER(18,2)` money
    - native `JSON` for `REQUEST`/`RESPONSE_MESSAGES`
    - `VARCHAR2` enums
  - Constraints: `UQ_LINE_RESULT_ITEM_LINE`, `UQ_APP_LEDGER_IDEM_KEY`, `FK_LINE_RESULT_WI`, `FK_APP_LEDGER_WI`.
  - Indexes: `IX_APP_LEDGER_ITEM_STATUS`, `IX_APP_LEDGER_RECEIPT`.
  - Every identifier is upper snake case and ≤ 30 characters.
- **Downgrade** drops both tables.
- **DEV ATP only during the run.**

## TEST PLAN (written and run only at step 5)

| AC | Test | Asserts |
|---|---|---|
| 1 | `api/tests/unit/services/matching/test_lines.py::test_verdict_order_per_line` | Parametrized, one row per verdict: zero → `allocation-zero-amount` (zero wins even when the number is also missing); missing → `allocation-invoice-not-found`; no bill-to → `allocation-customer-not-found`; currency ≠ → `allocation-apply-failed` + `INVOICE_CURRENCY_MISMATCH`; status "Closed" → `INVOICE_STATUS_INVALID`; balance 0 → `allocation-no-remaining-balance`; credit memo balance 0 / +5 → no-remaining (sign-aware); existing active application → `allocation-previously-applied`; a REVERSED existing application doesn't count. |
| 1 | `…::test_plan_lines_is_pure` | Plain `def`; inputs deep-equal after the call; two calls give equal plans. |
| 1 | `…::test_duplicate_lines_deduped_and_recorded` | INV-1 100 + INV-1 50 → one step of 150 (capped by balance), a draft for line 2 with `merged_into=1`, `duplicates == {1: (2,)}`. With one amount missing, the primary's amount is used. |
| 1 | `…::test_credit_memos_first_stable_order` | Lines [INV(1), CM(2), INV(3), CM(4)] → steps ordered CM2, CM4, INV1, INV3. |
| 1 | `…::test_amount_capped_at_min_stated_balance_remaining` | Stated 120 / balance 100 → 100, less-than-instruction. Stated 80 / balance 100 → 80, short-pay. Remaining 50 → 50, less-than-instruction. Exact → `allocation-applied`. |
| 1 | `…::test_credit_memo_signed_negative_increases_remaining` | Remaining 0, CM -40 and INV 40 → steps -40 and +40, `receipt_remaining_after == 0`. A positive stated credit memo amount is normalised. |
| 1 | `…::test_amountless_line_full_balance_only_when_header_reconciles` | Header 300, lines INV-1 (no amount, balance 100) + INV-2 200 → 100 applied. Header 350 with tolerance 0.10 → line 1 `allocation-apply-failed` + `AMOUNT_VARIANCE`. Within ±0.10 → applied. |
| 1 | `…::test_receipt_exhausted_is_amount_variance` | Remaining 0 with one invoice → apply-failed + `AMOUNT_VARIANCE`; never a zero step. |
| 1 | `…::test_non_invoice_lines_ignored` | BANK_FEE/TARIFF lines → no step or draft, listed in `ignored_line_nos`. |
| 1 | `…::test_index_transactions_prefers_kind_then_owner` | Same number as invoice and credit memo picked by `line.kind`; two invoices with only one owned → the owned one; otherwise in `ambiguous` and planned as not-found with reason "ambiguous". |
| 2 | `api/tests/integration/data/test_applications_repository.py::test_line_result_upsert_unique_per_line` | A second upsert updates the row; `for_item` is ordered by line_no; an unknown column → AttributeError. |
| 2 | `…::test_ledger_planned_mark_for_item_and_key_unique` | `upsert_planned` twice with the same key gives one row; an APPLIED row isn't reset; `planned_for` is ordered by `apply_seq`; a duplicate raw insert of the key → IntegrityError; a REVERSED row → new `#1` key. |
| 2 | `…::test_repositories_never_commit` | A rollback after the calls leaves no rows. |
| 2 | `api/tests/integration/data/test_applications_migration_atp.py::test_upgrade_downgrade_atp` (`-m atp`) | Columns, native JSON, identity PKs, both uniques and FKs, the indexes; the downgrade drops them; `alembic heads` is one head. |
| 3 | `api/tests/integration/stations/test_match_lines_runner.py::test_plans_from_fresh_fusion_and_advances_to_apply` | `FusionScenario` (INV-1 100, CM-1 -30, receipt 70, reservation) → `run_stage_once` gives `Advance(APPLY)`; one `find_transactions` call, one `get_receipt` call and one `list_receipt_applications` call; two PLANNED rows (CM seq 0); drafts written; DECISION history. |
| 3 | `…::test_balances_from_fusion_not_resolution_snapshot` | The resolution says balance 100; Fusion now says 60 → planned 60. |
| 3 | `…::test_reentry_reconciles_already_applied_row` | A PLANNED row exists and the fake already holds that application → the row is APPLIED with the Fusion application id, `LINE_RESULT` gets the target status, history has `FUSION_ALREADY_APPLIED` reconciled, and the line isn't re-planned. |
| 3 | `…::test_no_reservation_advances_to_match_receipt` | — |
| 4 | `api/tests/integration/stations/test_apply_runner.py::test_applies_rows_in_order_with_accounting_date` | Credit memo before invoice; `ApplyRequest` has the ids, signed amounts, `accounting_date = max(payment_date, today)`; ledger APPLIED with `fusion_application_id`; `LINE_RESULT` statuses set. |
| 4 | `…::test_gl_date_floor_hint_raises_accounting_date` | `fix_hints.gl_date_floor` later than today → used. |
| 4 | `…::test_existing_application_marks_applied_without_call` | The fake has the application → zero `apply_receipt` calls for that row. |
| 4 | `…::test_kill_mid_loop_resumes_without_reapplying` | `KillAfterApplies(n=3)` raises after the third apply has landed in the fake → lines 1–2 APPLIED in the DB, line 3 PLANNED; second run → exactly one Fusion application per transaction, 5/5 APPLIED, `apply_receipt` called 5 times in total. |
| 4 | `…::test_person_lock_aborts_and_keeps_done_lines` | The lock is set after line 1 (a fake hook) → `StageError(FUSION_LOCKED, cause=item_locked)`, line 1 APPLIED, the rest PLANNED, no further apply calls. |
| 4 | `…::test_gate_slot_entered_per_line` | A recording gate sees one `slot(receipt_id)` per apply. |
| 5 | `api/tests/unit/stations/test_apply_faults.py::test_business_fault_marks_line_and_continues` | `FUSION_FAULT` on line 2 → line 2 `allocation-apply-failed` with code, lines 1 and 3 applied, and the runner advances. |
| 5 | `…::test_transient_and_locked_raise_after_persisting_earlier_lines` | Parametrized over FUSION_TRANSIENT (FusionError) and FUSION_LOCKED (fault) on line 2 → StageError(code); line 1 APPLIED is committed; line 2 is still PLANNED; the retry run applies from line 2 only. |
| 5 | `…::test_reroute_codes_raise_with_detail` | Parametrized over OVERAPPLY, ALREADY_APPLIED and GL_DATE → StageError(code), detail keys present, no PII. |
| 5 | `…::test_outcome_unknown_resolved_by_idempotency_check` | A timeout `FusionError(outcome_unknown=True)` after the fake applied → retry marks it APPLIED without a second call. |
| 6 | `api/tests/unit/stations/test_apply_rollup.py::test_payment_status_derived_and_reservation_consumed` | All applied and equal to the header → `payment-success`; reservation CONSUMED; DECISION history lists every line; `Advance(WRITE_BACK)`. |
| 6 | `…::test_nothing_applied_never_success` | All lines failed or not found → status not in `SUCCESS_STATUSES`; with `receipt_found=False` inputs, `roll_up` gives `receipt-not-found`, never success. |
| 6 | `…::test_short_pay_rolls_up_less_than_total_due` | — |
| 6 | `…::test_merged_duplicate_gets_primary_status` | — |
| 7 | `api/tests/unit/stations/test_apply_faults.py::test_write_disabled_raises_before_any_fusion_call` | `WriteGuard(write_enabled=False, …)` → StageError(FUSION_WRITE_DISABLED); the fake's `calls == []`; with the default handler the item is ESCALATED; ledger rows still PLANNED; `payment_status` None. |
| 8 | `api/tests/unit/stations/test_apply_roles.py::test_roles_declared_and_discoverable` | `ROLES` names `["match-lines", "apply"]`, kind "consumer"; `discover_roles()` contains both exactly once; `build(FakeContainer)` returns `StageConsumer` objects. |

## Risks

- **Fusion `InvoiceStatus` values** ("Open"/"Complete") are unverified. `OPEN_TRANSACTION_STATUSES` is one constant to correct after a `fusion_rest_get` probe on the non-production pod.
- **The GL date floor.** `FusionReceipt` carries no GL date, so `FUSION_GL_DATE` detail may lack `receipt_gl_date`. s18 has to choose a floor (for example the next open day) when it's absent.
- **The `item_locked` cause rides on `FUSION_LOCKED`** because s03 has no "release claim without outcome" path. s18 must special-case `detail.cause`. With the default handler the item escalates, which is harmless because a person already holds it.
- **The row lock during the Fusion call.** Holding the item row `FOR UPDATE` across the roughly 6-second call makes an s40 `acquire` wait. It then gets `ItemBusy` because the claim is live, which is the intended behaviour, but the HTTP request is slow. The claim heartbeat keeps a long remittance from expiring mid-loop.
- **Unique idempotency key after a reversal.** It's handled with a `#n` suffix. s38 must create the new row through `upsert_planned` and never through a raw insert.
- **s13 and s15 both create `services/matching/__init__.py`.** It's empty, so the merge is trivial.
- **Everything is built against `FakeFusionClient`.** `apply_receipt` behaviour on a real pod is s05's VERIFY item.

## Assumptions and deviations

- **`plan_lines` gains keyword-only parameters:** `header_amount`, `tolerance`, `owners` and `ambiguous`. They're additive; the positional signature matches AC1.
  - `header_amount` and `tolerance` are needed for the "amountless line" rule.
  - `owners` adds the reference doc §4.3 relationship check: never apply cash to an unrelated customer's invoice.
- **The stated amount** is `ExtractedLine.amount_paid`. `gross_amount` isn't treated as the paid amount.
- **Additive columns:**
  - `LINE_RESULT`: `TARGET_STATUS` and `MERGED_INTO`. `LINE_STATUS` is nullable and means "apply pending".
  - `APPLICATION_LEDGER`: `RECEIPT_NUMBER` (s38's confirmation), `APPLY_SEQ`, `CREATED_AT`, `UPDATED_AT`.
- **`ROLES` lives in `stations/apply/roles.py`.** The two runner modules define no `ROLE`, which avoids a double discovery.
- **No active reservation at MATCH_LINES** → `Advance(MATCH_RECEIPT)`. At APPLY it's `StageError(RECEIPT_NOT_YET_AVAILABLE)`.
- **AC6 is followed literally:** the item advances to WRITE_BACK even when nothing applied, and the derived failure status travels with it. Escalation of failed payments is s18's and s20's concern.
