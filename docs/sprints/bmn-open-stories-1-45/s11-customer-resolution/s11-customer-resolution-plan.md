# s11-customer-resolution: plan

Issue #11. Wave 3 (waves.json index 2). Python only, with no web files and no UI. Paths: `cashapp/` = `api/src/cashapp/`.

## Standards followed

- **CLAUDE.md, Matching and apply rules / Customer.** The anchor is the `BillToCustomerNumber` of the first invoice found. Pay-on-behalf relationships (one hop, both directions) only widen the receipt search and are never a failure. A payer that maps to several accounts is never auto-assigned. Ambiguous `$` is resolved from the customer's account currency. A dual-currency payer always goes to a person (`DUAL_CURRENCY` is `always_person` in s02).
- **Reference doc §4.2–4.4 and §2.** Both invoices and credit memos are looked up in one batched call (s05 `find_transactions` already queries both resources). Invoice numbers stay strings end to end. "No anchor" means customer-not-found, and nothing is applied.
- **CLAUDE.md layering and `python-web-app:building-python-web-apps`.**
  - Only `data/` imports SQLAlchemy.
  - `services/customer.py` is pure business logic and takes `AliasLookup` and `FusionClient` as plain arguments, so s24's eval harness can call it without a database.
  - The runner owns the transaction through `ctx.uow`. Repositories never commit.
  - One ORM model module and one repository subclass of `BaseRepository`.
- **Non-negotiable 7 (DRY).**
  - Statuses, flags and error codes are imported from s02's `status.py` and `error_codes.py`. No new strings are defined here.
  - History rows go through `record_history` only.
  - Events go out only through the s03 runner's `Advance`; this story calls no `emit`.
  - Transactions come from s05's `FusionTransaction`. They are not re-modelled.
- **Auditability (CLAUDE.md conventions).** One `DECISION` history row explains the anchor choice: method, anchor line, alias ids, related accounts, currency source, flags and per-line findings.
- **PII.** Logs carry only counts, codes and ids, never payer names or bank accounts (s29 redaction applies). The DECISION payload holds account numbers, transaction numbers and ids only.
- **research.md.** The Fusion fake is the test double (`FusionScenario`). Nothing here is "confirmed against live": s05 owns the probes.

## Files to touch

All files are new. This story owns these paths, and they don't overlap with any other story's files.

| Path | Content |
|---|---|
| `cashapp/domain/customer.py` | `ResolutionMethod`, `LineFindingStatus`, `LineCustomerFinding`, `CustomerResolution` (frozen dataclasses), plus `transaction_to_json`/`transaction_from_json` |
| `cashapp/services/customer.py` | `resolve_customer(...)`, plus re-exports of `CustomerResolution`, `ResolutionMethod`, `LineCustomerFinding` and `LineFindingStatus` |
| `cashapp/data/models/customer_resolution.py` | ORM `CustomerResolutionRow` (table `customer_resolution`); picked up by s02's `load_all_models()` |
| `cashapp/data/repositories/customer_resolution.py` | `CustomerResolutionRepository(BaseRepository[CustomerResolutionRow])` |
| `cashapp/stations/resolve_customer/__init__.py` | exposes `ROLE` |
| `cashapp/stations/resolve_customer/runner.py` | `ResolveCustomerRunner(StageRunner)`, `build(container)`, `ROLE`, `default_alias_lookup` |
| `api/alembic/versions/<rev>_s11_customer_resolution.py` | the one revision (see Migrations) |
| `api/tests/unit/services/test_customer_resolution.py` | step 5 |
| `api/tests/unit/stations/test_resolve_customer_role.py` | step 5 |
| `api/tests/integration/stations/test_resolve_customer_runner.py` | step 5 |
| `api/tests/integration/data/test_customer_resolution_repo.py` | step 5 |
| `api/tests/integration/migrations/test_s11_customer_resolution_migration.py` | step 5 |

Not touched:
- `cashapp/stations/__init__.py` and `cashapp/services/__init__.py`. They are created by earlier stories; create them empty only if absent.
- `main.py`, lockfiles, `config_keys.py` and `status.py`. Every flag and code used already exists in s02.
- s37's `aliases.py`, s05's `fusion/*` and s09's `adjudication.py`. These are consumed only.

## Design

### Inputs

- **The extraction** is `AdjudicationRepository.latest_for(item_id)` (s09), passed through `RemittanceExtraction.model_validate(row.final)`. The ORM `final` is the JSON dict. If s09 hands back a model, `model_validate` still accepts it.
  - If there is no adjudication row, the runner raises `StageError(EXTRACTION_FAILED, {"reason": "no_adjudication"})`.
- **Lookup lines** are `extraction.lines` sorted by `line_no` whose `kind` is INVOICE, CREDIT_MEMO or UNKNOWN and whose `transaction_number.strip()` is non-empty.
  - BANK_FEE, TARIFF and DISCOUNT lines, and empty numbers, are never looked up and get no finding.
  - Numbers are compared exactly after `strip()`. Normalisation is the auto-fix engine's job (s18).
- **References for aliases** are `remittance_reference.value`, followed by the lookup lines' transaction numbers, with `None` values dropped and order kept.

### `resolve_customer` algorithm

The algorithm is pure. It raises `StageError` and never touches the database.

1. **Human hint.** If `human_customer_number` is given:
   - Call `fusion.get_customer_account(hint)`. If that raises `FusionError(CUSTOMER_NOT_FOUND)`, raise `StageError(CUSTOMER_NOT_FOUND, {"source": "human_hint"})`.
   - The anchor is the hint, with `method=HUMAN` and no alias call.
2. **Aliases.** Otherwise, call `aliases.lookup(payer_name.value, payer_bank_account.value, references)`. Take the distinct `customer_numbers`, keeping their order:
   - More than one: raise `StageError(CUSTOMER_MULTIPLE_ACCOUNTS, {"alias_ids": [...], "customer_count": n})`. Account numbers stay out of the detail; they are in the alias table.
   - Exactly one: the anchor is that customer, with `method=ALIAS`, the `alias_ids` recorded and `InfoFlag.ALIAS_USED` added.
   - None: go to the invoice path.
3. **Transactions.** Make one `fusion.find_transactions(unique lookup numbers)` call. It always runs, on every path, because s13, s15 and s16 reuse the result.
   - If there are no lookup numbers, make no call and use `[]`.
   - A `FusionError` becomes `StageError(e.code, {"op": "find_transactions", "fusion_code": e.fusion_code})`.
4. **Candidates for each line.** These are the transactions whose `number` equals the line's number.
   - A CREDIT_MEMO line prefers `kind=CREDIT_MEMO`, and an INVOICE line prefers `kind=INVOICE`. The preferred subset is used when it's non-empty; otherwise all candidates are used.
5. **Invoice-path anchor.** This step runs only when there is no anchor yet. Walk the lookup lines in `line_no` order. The anchor is the `bill_to_customer_number` of the first line whose candidates have exactly one distinct non-null bill-to; that line is recorded as `anchor_line_no`. Lines with no bill-to, or with candidates billed to several accounts, are skipped for anchoring.
   - If no lookup line has any candidate, raise `StageError(INVOICE_NOT_FOUND, {"lines": n})`. This also covers the case where there are no lookup lines at all, which gives `{"lines": 0}`.
   - If candidates were found but none gives an anchor, raise `StageError(CUSTOMER_NOT_FOUND, {"found_lines": k})`.
6. **Relationships.** Call `fusion.customer_relationships([anchor])` and take `related_account_number` values, de-duplicated, with the anchor removed, then sorted.
   - Any `FusionError`, or an empty result, gives `()`, with a WARNING log of the code only. It's never an error.
   - s05 already merges the INBOUND and OUTBOUND rows. The de-duplication here is a defensive guard.
7. **Line findings.** For each lookup line, the owners are `{anchor} ∪ related`:

   | Condition | `status` | `candidate_status` |
   |---|---|---|
   | No candidates | `NOT_FOUND` | `LineStatus.ALLOCATION_INVOICE_NOT_FOUND` |
   | Candidates exist but none has a bill-to | `NO_BILL_TO` | `ALLOCATION_CUSTOMER_NOT_FOUND` |
   | Any candidate is billed to an owner | `FOUND` | `None` |
   | Otherwise | `CUSTOMER_MISMATCH` | `ALLOCATION_CUSTOMER_NOT_FOUND` |

   - Each finding keeps the `customer_trx_ids` of its candidates and their `bill_to_customer_numbers`.
   - These findings never fail the item.
   - If any finding is `CUSTOMER_MISMATCH`, the found transactions span two or more accounts with no relationship, so add `InfoFlag.MULTIPLE_ACCOUNTS_SAME_RECEIPT`.
8. **Currency.**
   - If `extraction.currency.value` is set and `currency_ambiguous` is false, use it, with `currency_source="extraction"` and no Fusion call.
   - Otherwise, take the `currency_codes` from `fusion.get_customer_account(anchor)`, de-duplicated and upper-cased. The human path reuses the account from step 1.
     - Exactly one code: use it, with `currency_source="customer"` and `InfoFlag.CURRENCY_RESOLVED_FROM_CUSTOMER`.
     - Two or more: raise `StageError(DUAL_CURRENCY, {"currency_count": n})`.
     - None: fall back to the anchor-owned found transactions. If they carry exactly one distinct currency, use it, with `currency_source="anchor_transactions"` and the same flag. Otherwise, raise `StageError(INVALID_CURRENCY, {"reason": "unresolved"})`. This is an assumption.
     - A `FusionError` becomes a `StageError`, mapped as in step 3.
   - Invoice currencies that disagree with the payment currency are left for s15. They are not checked here.
9. **Result.** Return `CustomerResolution`. `transactions` holds every transaction returned by step 3, in Fusion's order.

### Runner (`ResolveCustomerRunner`, stage `RESOLVE_CUSTOMER`)

`process(ctx)` does the following, in `ctx.uow`, as one transaction owned by the s03 runner:

1. Load the extraction (see Inputs).
2. Read `hint = (ctx.item.human_hints or {}).get("customer_number")`.
3. `aliases = self._alias_factory(ctx.uow)`. The default is `default_alias_lookup(uow)`, which builds s37's `AliasService` on that unit of work. `lookup` increments USES, so the write must be in this transaction.
4. Call `resolve_customer(extraction, aliases=..., fusion=self._fusion, human_customer_number=hint, log=ctx.log)`.
5. `repo.add_resolution(item_id, resolution, now=ctx.clock.now())`.
6. `uow.work_items.update(item, customer_account_number=anchor, currency=resolution.currency or item.currency, info_flags=merged)`. The merged flags are the existing ones plus the new ones, in order and without duplicates.
7. Write the DECISION history row with `record_history(ctx.uow, item.id, HistoryEntry(action=DECISION, reasoning=<text>, payload=<dict>))`. Actor fields stay at the system defaults. When the method is human, the reasoning text says that a person's choice from requeue was honoured.
   - Example reasoning: "Anchor customer 1001 from invoice INV-1 (line 1, first line whose transaction was found); 2 related accounts widen the receipt search; currency USD from the extraction."
   - Payload: `{method, anchor_customer_number, anchor_line_no, anchor_transaction_number, alias_ids, related_customer_numbers, currency, currency_source, flags, line_findings:[{line_no, transaction_number, status, candidate_status}], transactions_found, resolution_id}`.
8. Return `Advance(Stage.FAST_PATH, note="customer resolved", payload={"resolution_id": id})`.

A `StageError` propagates to s03, so nothing is persisted, and the failure handler (s18) decides what happens next.

`build(container)` returns `cls(RunnerDeps.from_container(container), fusion=container.resolve(FusionClient))`. `ROLE = RoleSpec("resolve-customer", "consumer", build)`, which wraps `consumer_role`'s StageConsumer construction. The coder uses `consumer_role(ResolveCustomerRunner, "resolve-customer")` if s03's builder matches; the ROLE value is the same either way.

## Interfaces provided (pinned)

```python
# cashapp/domain/customer.py   (re-exported by cashapp/services/customer.py)
class ResolutionMethod(StrEnum): ALIAS = "alias"; INVOICE = "invoice"; HUMAN = "human"
class LineFindingStatus(StrEnum): FOUND = "FOUND"; NOT_FOUND = "NOT_FOUND"; NO_BILL_TO = "NO_BILL_TO"; CUSTOMER_MISMATCH = "CUSTOMER_MISMATCH"
CurrencySource = Literal["extraction", "customer", "anchor_transactions"]

@dataclass(frozen=True, slots=True)
class LineCustomerFinding:
    line_no: int
    transaction_number: str
    status: LineFindingStatus
    candidate_status: LineStatus | None        # s02 enum; s15 uses it as the line's pre-verdict
    customer_trx_ids: tuple[int, ...]
    bill_to_customer_numbers: tuple[str, ...]  # distinct, non-null, sorted

@dataclass(frozen=True, slots=True)
class CustomerResolution:
    anchor_customer_number: str
    related_customer_numbers: tuple[str, ...]  # sorted, deduped, anchor excluded
    method: ResolutionMethod                   # compares equal to "alias"|"invoice"|"human"
    alias_ids: tuple[int, ...]
    transactions: list[FusionTransaction]      # s05 dataclass; everything find_transactions returned
    currency: str | None
    flags: set[InfoFlag]                       # s02 enum
    anchor_line_no: int | None = None          # None for alias/human
    currency_source: CurrencySource | None = None
    line_findings: tuple[LineCustomerFinding, ...] = ()
    def owners(self) -> tuple[str, ...]        # (anchor, *related): the receipt-search owners for s13/s14
    def transactions_for(self, number: str) -> list[FusionTransaction]   # exact match on strip()

def transaction_to_json(t: FusionTransaction) -> dict[str, Any]          # money as "0.00" strings
def transaction_from_json(d: Mapping[str, Any]) -> FusionTransaction     # to_money(); kind -> TransactionKind
```

```python
# cashapp/services/customer.py
async def resolve_customer(
    extraction: RemittanceExtraction, *,
    aliases: AliasLookup,                  # s37 Protocol
    fusion: FusionClient,                  # s05 Protocol
    human_customer_number: str | None = None,
    log: logging.Logger | logging.LoggerAdapter[logging.Logger] | None = None,
) -> CustomerResolution
    # raises StageError(code) with code in {CUSTOMER_MULTIPLE_ACCOUNTS, INVOICE_NOT_FOUND, CUSTOMER_NOT_FOUND,
    #   DUAL_CURRENCY, INVALID_CURRENCY, FUSION_TRANSIENT, FUSION_LOCKED, FUSION_FAULT}; never a raw FusionError
```

```python
# cashapp/data/models/customer_resolution.py   (table customer_resolution -> CUSTOMER_RESOLUTION)
class CustomerResolutionRow(Base):
    id: Mapped[int]                         # identity_pk()
    work_item_id: Mapped[int]               # FK work_item.id, not null
    anchor_customer_number: Mapped[str]     # String(100)
    related_customer_numbers: Mapped[list[str]]   # JsonDoc
    method: Mapped[ResolutionMethod]        # StrEnumType, VARCHAR2(40)
    alias_ids: Mapped[list[int]]            # JsonDoc
    currency: Mapped[str | None]            # CHAR(3)
    transactions: Mapped[list[dict[str, Any]]]    # JsonDoc of transaction_to_json
    flags: Mapped[list[str]]                # JsonDoc (additive column)
    line_findings: Mapped[list[dict[str, Any]]]   # JsonDoc (additive column)
    anchor_line_no: Mapped[int | None]      # (additive column)
    currency_source: Mapped[str | None]     # String(30) (additive column)
    created_at: Mapped[datetime]            # UtcDateTime, default utcnow

# cashapp/data/repositories/customer_resolution.py
class CustomerResolutionRepository(BaseRepository[CustomerResolutionRow]):
    async def add_resolution(self, item_id: int, resolution: CustomerResolution, *, now: datetime) -> CustomerResolutionRow
    async def latest_row_for(self, item_id: int) -> CustomerResolutionRow | None    # ORDER BY created_at DESC, id DESC
    async def latest_for(self, item_id: int) -> CustomerResolution | None           # THE accessor for s13/s15/s16/s20/s24
    async def latest_for_items(self, item_ids: Sequence[int]) -> dict[int, CustomerResolution]
        # s14's candidates_for: related customers per item without SQL JSON predicates (chunks of 500 ids)
```

```python
# cashapp/stations/resolve_customer/runner.py
AliasFactory = Callable[[UnitOfWork], AliasLookup]
def default_alias_lookup(uow: UnitOfWork) -> AliasLookup     # s37 AliasService bound to the uow (coder adapts to s37's ctor)
class ResolveCustomerRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.RESOLVE_CUSTOMER
    def __init__(self, deps: RunnerDeps, *, fusion: FusionClient,
                 alias_factory: AliasFactory = default_alias_lookup) -> None
    async def process(self, ctx: StageContext) -> StageOutcome   # Advance(FAST_PATH, payload={"resolution_id": int})
def build(container: Container) -> Runnable
ROLE: RoleSpec = RoleSpec("resolve-customer", "consumer", build)
```

The effects on `WORK_ITEM` that dependents rely on:
- `CUSTOMER_ACCOUNT_NUMBER` is the anchor.
- `CURRENCY` is the resolved currency.
- `INFO_FLAGS` gains `alias-used`, `currency-resolved-from-customer` and `multiple-accounts-same-receipt` as applicable.

## Migrations

There is one hand-written revision: `api/alembic/versions/<rev>_s11_customer_resolution.py`, with `revision = "s11_customer_resolution"`.

- **Expected parent:** the current head when it's coded. That will be the wave-2 head, s08's `extraction_reading`, or whichever of s09, s10, s37 or s14 merges first in this wave. The merger re-points `down_revision` and checks that `alembic heads` returns exactly one head.
- **Destination:** DEV ATP only.
- **Upgrade** creates `CUSTOMER_RESOLUTION`:

  | Column | Type | Null |
  |---|---|---|
  | `ID` | NUMBER identity | PK `PK_CUSTOMER_RESOLUTION` |
  | `WORK_ITEM_ID` | NUMBER | NOT NULL; FK `FK_CUSTRES_WORK_ITEM` to `WORK_ITEM.ID` |
  | `ANCHOR_CUSTOMER_NUMBER` | VARCHAR2(100) | NOT NULL |
  | `RELATED_CUSTOMER_NUMBERS` | JSON | NOT NULL |
  | `METHOD` | VARCHAR2(40) | NOT NULL |
  | `ALIAS_IDS` | JSON | NOT NULL |
  | `CURRENCY` | CHAR(3) | NULL |
  | `TRANSACTIONS` | JSON | NOT NULL |
  | `FLAGS` | JSON | NOT NULL |
  | `LINE_FINDINGS` | JSON | NOT NULL |
  | `ANCHOR_LINE_NO` | NUMBER(10) | NULL |
  | `CURRENCY_SOURCE` | VARCHAR2(30) | NULL |
  | `CREATED_AT` | TIMESTAMP WITH TIME ZONE | NOT NULL |

  - The table has one index, `IX_CUSTRES_ITEM_CREATED` on `(WORK_ITEM_ID, CREATED_AT)`.
  - No CHECK constraint is put on `METHOD`, following s02's rule for enum columns.
- **Downgrade** drops the table.
- **Types** follow s02: `JsonDoc`, `UtcDateTime`, `identity_pk`, and the naming convention with names of at most 30 characters.

## TEST PLAN (written and run only at step 5)

- Unit tests use s05's `FusionScenario` (`fusion_scenario` fixture), s08's `make_extraction(...)`, and a test-local stub `_StubAliases(customer_numbers, alias_ids)` that satisfies `AliasLookup` and records its calls.
- Integration tests use s02's aiosqlite `uow_factory` and s03's `make_runner_deps`, `run_stage_once` and `drain_outbox`.

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/unit/services/test_customer_resolution.py::test_resolution_shape_and_types` (all fields present and correctly typed; `method == "invoice"`; transactions are `FusionTransaction`; `owners()`) |
| 1 | `…::test_transaction_json_roundtrip_keeps_strings_and_decimals` (`"2598014-1"` stays a str; a negative credit-memo balance survives) |
| 2 | `…::test_single_alias_customer_anchors_with_alias_flag` (`method="alias"`, `ALIAS_USED`, `alias_ids` recorded; the stub received payer, bank account and references) |
| 2 | `…::test_alias_multiple_customers_raises_multiple_accounts` (`StageError.code == CUSTOMER_MULTIPLE_ACCOUNTS`; `find_transactions` never called) |
| 2 | `…::test_no_alias_falls_through_to_invoice_path` |
| 3 | `…::test_invoice_path_one_batched_lookup_both_kinds` (one `find_transactions` FakeCall with the unique numbers; an invoice and a credit memo are both found) |
| 3 | `…::test_anchor_is_first_found_line_by_line_no` (lines given out of order; line 1 unmatched; line 2 found → anchor from line 2, `anchor_line_no == 2`) |
| 3 | `…::test_no_transactions_found_raises_invoice_not_found` |
| 3 | `…::test_found_without_bill_to_raises_customer_not_found` |
| 3 | `…::test_bank_fee_and_empty_numbers_not_looked_up` |
| 3 | `…::test_transactions_kept_on_resolution` |
| 4 | `…::test_unrelated_bill_to_recorded_as_customer_mismatch_and_flagged` (`candidate_status == ALLOCATION_CUSTOMER_NOT_FOUND`, `MULTIPLE_ACCOUNTS_SAME_RECEIPT` set, no exception) |
| 4 | `…::test_related_bill_to_is_found_not_flagged` |
| 5 | `…::test_relationships_one_hop_both_directions_deduped_anchor_excluded` (scenario `relationship()` both ways plus a self row → sorted unique tuple) |
| 5 | `…::test_relationship_lookup_failure_is_empty_not_error` (`fail_next("customer_relationships", FusionError(FUSION_FAULT, ...))` → `()`, warning logged with no account names) |
| 5 | `…::test_relationship_empty_result_is_empty` |
| 6 | `…::test_ambiguous_dollar_resolved_from_single_account_currency` (`CURRENCY_RESOLVED_FROM_CUSTOMER`, `currency_source="customer"`) |
| 6 | `…::test_dual_currency_customer_raises_dual_currency` (and `ErrorCode.DUAL_CURRENCY.spec.always_person`) |
| 6 | `…::test_explicit_currency_skips_customer_lookup` (no `get_customer_account` call) |
| 6 | `…::test_invoice_currency_mismatch_left_for_line_matching` (a CAD invoice with a USD payment → no error, no flag) |
| 6 | `…::test_no_account_currency_falls_back_to_anchor_transactions` (assumption A3) |
| 7 | `api/tests/integration/migrations/test_s11_customer_resolution_migration.py::test_upgrade_creates_table_and_downgrade_drops` (`@pytest.mark.atp`; DEV schema; columns and the index checked through the inspector) |
| 7 | `…::test_single_alembic_head` (script directory heads == 1; no database) |
| 7 | `api/tests/integration/data/test_customer_resolution_repo.py::test_add_and_latest_for_roundtrip` (aiosqlite; the domain object is equal after the round trip, including Decimals and findings) |
| 7 | `…::test_latest_for_returns_newest_and_none_when_absent` |
| 7 | `…::test_latest_for_items_batches` |
| 8 | `api/tests/integration/stations/test_resolve_customer_runner.py::test_runner_stores_resolution_updates_item_and_advances_to_fast_path` (CUSTOMER_ACCOUNT_NUMBER, CURRENCY and INFO_FLAGS set; one `StageEvent(FAST_PATH)` in the outbox) |
| 8 | `…::test_runner_writes_decision_history_explaining_anchor` (action DECISION; the reasoning names the method and anchor line; the payload has `alias_ids` and `line_findings`; no payer name in the payload) |
| 8 | `…::test_human_hint_customer_number_wins_with_method_human` (the alias stub is never called; `method == "human"`) |
| 8 | `…::test_human_hint_unknown_customer_raises_customer_not_found` |
| 8 | `…::test_stage_error_persists_nothing` (multi-account alias → no `CUSTOMER_RESOLUTION` row, the item is unchanged, the s03 failure path runs) |
| 8 | `…::test_missing_adjudication_raises_extraction_failed` |
| 9 | `api/tests/unit/stations/test_resolve_customer_role.py::test_role_spec_name_kind_and_build` (`ROLE == RoleSpec("resolve-customer", "consumer", build)`; `build(FakeContainer)` with a registered `FakeFusionClient` returns a Runnable) |
| layering | `…::test_service_imports_no_sqlalchemy_or_fastapi` (ast check over `services/customer.py` and `domain/customer.py`) |

## Risks

- **Several transactions can share a number** across business units, or as an invoice plus a credit memo. The anchor skips a line whose candidates are billed to more than one account, and the kind preference decides between invoice and credit memo. A tenant with heavy number reuse could still pick the wrong anchor. s15's per-line customer check limits the damage, because a mismatched line is not applied.
- **s37's `AliasService` constructor isn't pinned yet** (same wave). `default_alias_lookup` adapts to it. If `lookup` doesn't write, the factory can ignore the unit of work. The merger reconciles this; no local stand-in alias implementation is created (non-negotiable 7).
- **s09's `Adjudication.final` type** (dict or model) is unpinned. `model_validate` handles both.
- **Stale transactions.** Balances in `TRANSACTIONS` are a snapshot. s15 must re-read the balance before applying (CLAUDE.md idempotency). This story only provides the snapshot.
- **The dual-currency rule is applied only when the currency is ambiguous**, as the AC states. A payer with an explicit currency whose account has two currencies is not escalated here. CLAUDE.md's "always a person: dual-currency payers" could be read more broadly. Flagged for Jonathan; the rule is easy to tighten later.
- **The relationships report must exist in each tenant** (s32 preflight). Until it does, every lookup logs a warning and the receipt search uses only the anchor. That is by design, never a failure.

## Assumptions and deviations

- **A1, extra columns.** `CUSTOMER_RESOLUTION` gets four additive columns beyond AC7: `FLAGS`, `LINE_FINDINGS`, `ANCHOR_LINE_NO` and `CURRENCY_SOURCE`. Without them, `latest_for` couldn't rebuild the full `CustomerResolution`, and the per-line findings that AC4 requires to be "recorded per line" would have nowhere to live. `METHOD` is VARCHAR2(40) rather than a narrower type, following s02's enum-column rule.
- **A2, `CustomerResolution` additions.** The dataclass gains `anchor_line_no`, `currency_source`, `line_findings` (all defaulted, so the AC1 shape is a subset), and `method` also allows `"human"` for AC8. `method` is a StrEnum, which compares equal to the AC's literal strings. `resolve_customer` gains the keyword arguments `human_customer_number` and `log`.
- **A3, currency fallback.** When the account has no currency codes, the currency is taken from the anchor-owned found transactions if they agree on one; otherwise the item fails with `INVALID_CURRENCY`. The AC doesn't cover this case.
- **A4, alias and human paths.** On these paths, transactions are still looked up, but "no transaction found" isn't raised: the customer is already known, and s15 grades the lines `allocation-invoice-not-found`. `INVOICE_NOT_FOUND` and `CUSTOMER_NOT_FOUND` are raised only on the invoice path, as AC3 states.
- **A5, `HUMAN_HINTS["customer_number"]`.** The hint is read and not cleared. It stays the person's standing choice until s18 changes it. It's validated through `get_customer_account`.
- **A6, layering.** The domain dataclasses live in `cashapp/domain/customer.py` (a new file, outside the story's listed dirs) so that the repository in `data/` doesn't import from `services/`. `domain/customer.py` imports s05's pure-dataclass `integrations/fusion/models.py`. That module does no IO, so the coupling is accepted.
- **A7, error mapping.** The service turns `FusionError` into `StageError` with the same `ErrorCode`, so the eval harness (s24) and the runner see one error type. The relationship lookup is the only exception: its errors are swallowed.
