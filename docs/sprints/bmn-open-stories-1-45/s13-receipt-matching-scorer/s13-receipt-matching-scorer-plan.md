# Plan: s13-receipt-matching-scorer

Receipt matching station: a pure multi-signal scorer, a `MATCH_CANDIDATE` audit trail for every
receipt looked at, and a `RECEIPT_RESERVATION` that stops two remittances taking one receipt.
Ambiguity is an error, never "first wins". Re-matching after a partial apply resumes on the same
receipt. No LLM is involved (pure code), so the LLM skills don't apply.

## Standards followed

- CLAUDE.md *Matching and apply rules*: one receipt per payment; same currency; amount within the
  per-currency tolerance (or a configured bank-fee band); receipt date within the one shared window
  (`matching.date_window_days`, used for both the Fusion query and the matcher); anchor-owned
  first, then related; more than one qualifier → `RECEIPT_AMBIGUOUS`; reserve before applying;
  match on the receipt's *remaining* unapplied amount. Money is `Decimal` via s02 `to_money` /
  `money_eq`; tolerances widen the match only.
- Reference doc §4.5 + defects fixed: no first-wins, reservation added, partly applied receipts
  re-match (AC7), the creation-date window (§6: 21% of failures were receipts created a day late).
- Layering (CLAUDE.md, s02): the scorer is a pure function in `services/`; the only ORM code is in
  `data/models/receipt_matching.py` and `data/repositories/{reservations,match_candidates}.py`;
  repositories never commit; services and the runner never import SQLAlchemy; services receive no
  `Request`. Every threshold comes from `ctx.config.matching()` (s28) and `item.fix_hints` (s18).
- One `StageRunner` (s03): `MatchReceiptRunner` implements only `process`; the transition, history
  and outbox event are written by s03. Mid-process `ctx.uow.commit()` is used once, so the
  `MATCH_CANDIDATE` trail survives a `StageError` (s03 rule "stations may commit mid-process").
- One status/error vocabulary: only s02 `ErrorCode` members are raised (`RECEIPT_NOT_YET_AVAILABLE`,
  `RECEIPT_AMBIGUOUS`, `RECEIPT_RESERVED`, `AMOUNT_VARIANCE`, `CUSTOMER_NOT_FOUND`,
  `MISSING_PAYMENT_DATE`). `StageError.detail` carries ids, codes and amounts only (no PII).
- s02 data rules: lowercase SQLAlchemy names, upper snake physical names, identity PKs, enum
  columns `VARCHAR2(40)` without CHECK, explicit names ≤ 30 chars, `JsonDoc` for JSON,
  `MoneyNumeric` for money, `UtcDateTime` for timestamps.
- Integrations behind interfaces: only `FusionClient` (s05) is called; tests use
  `FakeFusionClient` / `FusionScenario`. The fake stays "unverified against live".
- PII (CLAUDE.md, s29): logs carry `work_item_id`, receipt ids and counts only; never payer names,
  bank accounts or references. Bank accounts are not stored in `MATCH_CANDIDATE` (only the signal
  strength).
- `python-web-app:building-python-web-apps`: logic in services, SDKs isolated in integrations.
- Gates for the coder: `uv run ruff check . && uv run ruff format --check .` and `uv run pyright`.

## Files to touch (all new; file-disjoint from other stories)

All paths under `api/` unless absolute.

| Path | Content |
|---|---|
| `src/cashapp/domain/receipt_matching.py` | `ReservationStatus`, `DecidedBy`, `MatchOutcome` StrEnums (pure) |
| `src/cashapp/data/models/receipt_matching.py` | `ReceiptReservation`, `MatchCandidate` ORM models (picked up by s02's `load_all_models()`) |
| `src/cashapp/data/repositories/reservations.py` | `ReservationRepository`, `ReservationConflict` |
| `src/cashapp/data/repositories/match_candidates.py` | `MatchCandidateRepository` |
| `src/cashapp/services/matching/__init__.py` | empty. s15 may create the same empty file; identical content, so the merger keeps one |
| `src/cashapp/services/matching/receipts.py` | `MatchContext`, `Candidate`, `ScoredCandidates`, `ReceiptEvidence`, `normalise_reference`, `score_candidates`, `SOFT_SIGNALS` |
| `src/cashapp/services/matching/evidence.py` | `RECEIPT_SIGNALS_REPORT_PATH`, `fetch_receipt_evidence` (BIP rows from s12's pinned shape; failure → empty, never an error) |
| `src/cashapp/services/matching/reservations.py` | `ReservationService.claim` (own release, stale-holder release, reserve) |
| `src/cashapp/stations/match_receipt/__init__.py` | `ROLE` |
| `src/cashapp/stations/match_receipt/runner.py` | `MatchReceiptRunner` |
| `alembic/versions/s13_receipt_matching.py` | the one revision (see Migrations) |
| tests in the TEST PLAN | written in step 5 only |

Not touched: s02's `FixHints` (`narrow` is read with `.get`, see Assumptions), `main.py`, the
lockfiles, `config_keys.py`, s05/s11/s37 modules.

## Design

### Pure scorer (`services/matching/receipts.py`)

`score_candidates(ctx, receipts, config, aliases, *, evidence=None)` (sync, no I/O):

1. **Pool**: receipts deduplicated by `receipt_id` (the runner may pass the union of the
   receipt-date and creation-date searches).
2. **Effective payment amount per receipt**: `ctx.payment_amount − ctx.resume_applied.get(receipt_id, 0)`
   (AC7). For other receipts it is `ctx.payment_amount`.
3. **Hard filters** (each failure adds a reason string; all must pass for `qualifies=True`):
   - `currency`: `receipt.currency == ctx.currency` (upper-cased) → reason `currency_mismatch`.
   - `amount`: `diff = receipt.unapplied_amount − effective`; `|diff| ≤ config.tolerance_for(currency)`
     → signal `amount_exact` (1.0 when `money_eq`) or `amount_tolerance`; else when
     `effective − unapplied` (the fee the bank kept) falls in a `bank_fee_bands` band for the currency
     (or `"*"`) → signal `bank_fee_band`; else reason `amount_outside_tolerance` (diff recorded).
     A resumed receipt whose effective amount is ≤ 0.005 qualifies with signal `resume_fully_applied`
     (s15/s16 then reconcile as previously applied).
   - `window`: window `W = config.date_window_days + fix_hints.get("widen_window_days", 0)`;
     `|receipt_date − payment_date| ≤ W` → signal `date_receipt_window`; else when
     `fix_hints.get("match_on_creation_date")` and `|creation_date.date() − payment_date| ≤ W` →
     `date_creation_window`; else reason `outside_window`.
   - `owner`: `customer_account_number == ctx.anchor` → `owner_anchor`; in `ctx.related` →
     `owner_related`; else reason `not_owner` (unidentified receipts never qualify).
4. **Soft signals** (strength 0..1, key names = s12 `PROPOSED_SCORER_WEIGHT_KEYS`):
   - `remittance_reference`: 1.0 when a normalised `ctx.references` value equals one of the receipt's
     normalised `remittance_references` (or appears in `comments` as a whole token).
   - `statement_reference`: 1.0 when `evidence[receipt_id].statement_reference` equals a reference.
   - `invoice_set_overlap`: `|invoices ∩ receipt refs| / |invoices|` (normalised; 0 when either empty).
   - `payer_bank_account`: 1.0 when `evidence[...].payer_bank_account` equals `ctx.payer_bank_account`
     (normalised: upper, whitespace removed).
   - `date_distance`: `1 − d / (W + 1)` with `d` the smaller qualifying day distance.
   - `alias_reference_pattern`: 1.0 when `aliases` is given and the receipt owner is in
     `aliases.customer_numbers`.
   - `customer_history`: 1.0 for an anchor-owned receipt, 0.5 for a related one (see Assumptions).
   - `score = Σ config.scorer_weights.get(k, 0.0) × strength[k]`, rounded to 6 dp. Hard-filter
     markers are kept in `signals` too (value 1.0) but carry no weight.
5. **Decision** (never first-wins):
   1. *Outright*: qualifying candidates with an **exact reference** (`remittance_reference` or
      `statement_reference` = 1.0) or an **exact invoice set** (non-empty invoice set equal to the
      receipt's reference set). Exactly one → `matched`. More than one → continue below using only
      those (they stay ambiguous unless narrowed).
   2. *Tiered by owner*: anchor-owned qualifiers first; if none, related qualifiers. Exactly one in
      the first non-empty tier → `matched`. More than one → `ambiguous`, unless
      `fix_hints.get("narrow")` and `best.score > runner_up.score` and
      `best.score − runner_up.score ≥ config.min_score` → `matched`.
   3. *No qualifier*: `variance` when some candidate failed **only** the amount filter **and** is
      grounded (any of `remittance_reference`, `statement_reference`, `payer_bank_account` = 1.0 or
      `invoice_set_overlap` > 0); otherwise `none`.
   - `candidates` are ordered for display: qualifies desc, anchor first, score desc, `|diff|` asc,
     `receipt_id` asc. `winner` is set only for `matched`.

`normalise_reference(s)`: strip, upper-case, drop whitespace and a leading `#`; `-` is kept
(`2598014-1` is a credit memo, not `25980141`).

### Evidence (`services/matching/evidence.py`)

`fetch_receipt_evidence(fusion, receipts, *, log)` → `dict[int, ReceiptEvidence]`: one
`fusion.run_report(RECEIPT_SIGNALS_REPORT_PATH, {"P_CREATION_FROM": iso(min creation), "P_CREATION_TO": iso(max creation)})`,
parsed with `defusedxml` against s12's pinned row shape, filtered to the pool's receipt ids. Any
`FusionError` or parse error → `{}` plus one warning (`receipt_signals_unavailable`). Never raises.
Bank account and statement reference stay in memory only.

### Reservation service (`services/matching/reservations.py`)

`ReservationService(clock).claim(uow, *, item, receipt_id, receipt_number, now) -> ReservationClaim`:

1. `own = repo.active_for_item(item.id)`. Same receipt → return it (idempotent re-run). Different
   receipt → `repo.release(item.id, "rematched to receipt <n>")` and a DECISION history row.
2. `holder = repo.active_for_receipt(receipt_id)` (`SELECT … FOR UPDATE SKIP LOCKED`).
   - `holder` belongs to another item: load that item (`uow.work_items.get`). It is **stale** when its
     state is `ESCALATED` or `ARCHIVED` **and** it has no live person lock (s40
     `is_locked_for_automation`). Stale → `repo.release_row(holder, reason)` plus DECISION history on
     **both** items. Not stale → `StageError(RECEIPT_RESERVED, {"receipt_id", "holder_item_id"})`.
3. `repo.reserve(receipt_id, item.id, receipt_number=…, now=now)`. `ReservationConflict` (unique index
   hit because a concurrent transaction holds the row) → `StageError(RECEIPT_RESERVED, {"receipt_id", "contended": True})`.

### Station (`stations/match_receipt/runner.py`)

`MatchReceiptRunner(StageRunner)`, `stage = Stage.MATCH_RECEIPT`;
`__init__(deps, *, fusion: FusionClient, alias_lookup: Callable[[UnitOfWork], AliasLookup] | None = None)`;
`build(c)` → `cls(RunnerDeps.from_container(c), fusion=c.resolve(FusionClient))`.

`process(ctx)`:

1. `resolution = CustomerResolutionRepository.latest_for(item.id)` (s11); none → `StageError(CUSTOMER_NOT_FOUND)`.
2. Payment fields from the work item (`payment_amount`, `currency` set by s11, `payment_date`);
   missing date → `StageError(MISSING_PAYMENT_DATE)`. References, invoice numbers, payer name and bank
   account from `AdjudicationRepository.latest_for(item.id)` (s09) parsed as `RemittanceExtraction` (s08).
3. `matching = ctx.config.matching()`; `hints = item.fix_hints or {}`; `W` as above.
4. Prior receipt: `res.active_for_item(item.id)` else `MatchCandidateRepository.last_chosen(item.id)`.
   If present: `apps = fusion.list_receipt_applications(prior)`;
   `resume_applied[prior] = Σ amount_applied` for apps with `status != "REVERSED"` whose
   `customer_trx_id` is in `resolution.transactions` (AC7).
5. Search: `fusion.find_receipts(customer_numbers=[anchor, *related], date_from=pd−W, date_to=pd+W, by="receipt_date")`,
   plus `by="creation_date"` when `hints.match_on_creation_date`; the prior receipt is added through
   `fusion.get_receipt(prior)` when it isn't in the result (a `FusionError` there is ignored).
6. Aliases: `alias_lookup(ctx.uow).lookup(payer_name, payer_bank_account, references)` (s37); any
   exception → `None` and a warning (aliases only add score).
7. Evidence (above), then `scored = score_candidates(...)`.
8. **Human hint**: `item.human_hints.get("receipt_id")`. The receipt (from the pool, else
   `get_receipt`) must have the item's currency and `unapplied_amount > 0.005`, else
   `StageError(AMOUNT_VARIANCE, {"human_receipt_id", "reason": "currency_mismatch"|"no_unapplied"})`.
   It becomes the winner with `decided_by=HUMAN` regardless of the score.
9. Persist **every** candidate: `MatchCandidateRepository.add_round(item.id, rows)` with
   `attempt = next_attempt(item.id)`, `CHOSEN=1` only on the winner. Then `await ctx.uow.commit()`.
10. Outcome → error: `none` → `RECEIPT_NOT_YET_AVAILABLE`; `ambiguous` → `RECEIPT_AMBIGUOUS`
    (detail: qualifying receipt ids, best/runner-up score); `variance` → `AMOUNT_VARIANCE`
    (detail: receipt id, diff).
11. `ReservationService.claim(...)`, then one DECISION history row ("why this receipt"):
    `payload={receipt_id, receipt_number, decided_by, outcome_rule ("outright"|"single"|"tier_anchor"|"tier_related"|"narrowed"|"human"), score, runner_up_score, signals, reasons, alias_ids, window_days, basis, resume_applied, match_attempt}`.
12. Return `Advance(Stage.MATCH_LINES, note="receipt <number>", payload={"receipt_id": id})`.

## Interfaces provided (pinned)

```python
# cashapp/domain/receipt_matching.py
class ReservationStatus(StrEnum): ACTIVE = "ACTIVE"; CONSUMED = "CONSUMED"; RELEASED = "RELEASED"
class DecidedBy(StrEnum): SYSTEM = "system"; HUMAN = "human"
class MatchOutcome(StrEnum): MATCHED = "matched"; NONE = "none"; AMBIGUOUS = "ambiguous"; VARIANCE = "variance"
```

```python
# cashapp/services/matching/receipts.py
SOFT_SIGNALS: tuple[str, ...]   # == s12 PROPOSED_SCORER_WEIGHT_KEYS (asserted by a test; not imported from tools/)

@dataclass(frozen=True, slots=True)
class MatchContext:
    payment_amount: Decimal
    currency: str
    payment_date: date
    anchor: str
    related: tuple[str, ...] = ()
    references: tuple[str, ...] = ()          # remittance reference(s) from the extraction
    invoice_numbers: tuple[str, ...] = ()     # INVOICE / CREDIT_MEMO transaction numbers
    payer_bank_account: str | None = None
    fix_hints: Mapping[str, Any] = MappingProxyType({})   # s02 FixHints (+ "narrow": bool from s18)
    resume_applied: Mapping[int, Decimal] = MappingProxyType({})   # additive: receipt_id -> already applied (AC7)

@dataclass(frozen=True, slots=True)
class ReceiptEvidence:
    receipt_id: int; statement_reference: str | None = None; payer_bank_account: str | None = None

@dataclass(frozen=True, slots=True)
class Candidate:
    receipt: FusionReceipt
    qualifies: bool
    score: float
    signals: dict[str, float]      # soft strengths + hard markers (amount_exact|amount_tolerance|bank_fee_band|
                                   # resume_fully_applied, date_receipt_window|date_creation_window, owner_anchor|owner_related)
    reasons: list[str]             # failed hard filters, e.g. "currency_mismatch", "amount_outside_tolerance:-12.40"
    amount_diff: Decimal           # additive: unapplied - effective payment amount
    owner_tier: Literal["anchor", "related", "other"]   # additive

@dataclass(frozen=True, slots=True)
class ScoredCandidates:
    candidates: list[Candidate]    # display order (see Design)
    winner: Candidate | None       # set only when outcome == "matched"
    outcome: Literal["matched", "none", "ambiguous", "variance"]
    rule: str | None = None        # additive: "outright" | "single" | "tier_anchor" | "tier_related" | "narrowed"

def normalise_reference(value: str) -> str
def score_candidates(ctx: MatchContext, receipts: Sequence[FusionReceipt], config: MatchingConfig,
                     aliases: AliasMatch | None, *,
                     evidence: Mapping[int, ReceiptEvidence] | None = None) -> ScoredCandidates
```

s24 calls `score_candidates` with the four positional arguments; `evidence` is optional.

```python
# cashapp/services/matching/evidence.py
RECEIPT_SIGNALS_REPORT_PATH: Final = "/Custom/CashApp/ReceiptSignals.xdo"   # s32 may re-point; one constant
async def fetch_receipt_evidence(fusion: FusionClient, receipts: Sequence[FusionReceipt], *,
                                 log: logging.Logger | logging.LoggerAdapter[logging.Logger]) -> dict[int, ReceiptEvidence]

# cashapp/services/matching/reservations.py
@dataclass(frozen=True, slots=True)
class ReservationClaim:
    reservation: ReceiptReservation
    released_own_receipt_id: int | None
    released_stale_holder_item_id: int | None
class ReservationService:
    def __init__(self, clock: Clock) -> None
    async def claim(self, uow: UnitOfWork, *, item: WorkItem, receipt_id: int,
                    receipt_number: str | None, now: datetime) -> ReservationClaim   # raises StageError(RECEIPT_RESERVED)
STALE_HOLDER_STATES: Final[frozenset[ItemState]] = frozenset({ItemState.ESCALATED, ItemState.ARCHIVED})
```

```python
# cashapp/data/models/receipt_matching.py
class ReceiptReservation(Base):      # __tablename__ = "receipt_reservation"
    id: int (identity PK); receipt_id: int (BigInteger, not null); receipt_number: str | None (String(100))
    work_item_id: int (FK work_item.id "FK_RR_WORK_ITEM", not null); status: ReservationStatus (not null)
    reserved_at: datetime (UtcDateTime, not null); released_at: datetime | None; reason: str | None (String(1000))
    # Index("UX_RR_ACTIVE_RECEIPT", case((status == 'ACTIVE', receipt_id)), unique=True)  -- function-based on Oracle,
    #   expression index on SQLite (same definition); Index("IX_RR_ITEM_STATUS", work_item_id, status)
class MatchCandidate(Base):          # __tablename__ = "match_candidate"
    id: int (identity PK); work_item_id: int (FK "FK_MC_WORK_ITEM", not null); attempt: int (not null)
    receipt_id: int (BigInteger, not null); receipt_number: str | None (String(100))
    qualifies: bool (not null); score: float (Float, not null); signals: dict[str, float] (JsonDoc, not null)
    chosen: bool (not null, default False); decided_by: DecidedBy (not null, default SYSTEM)
    created_at: datetime (UtcDateTime, not null, default utcnow)
    # additive (nullable): reasons JsonDoc list[str]; customer_account_number String(100); currency CHAR(3);
    #   receipt_date Date; unapplied_amount MoneyNumeric
    # Index("IX_MC_ITEM_ATTEMPT", work_item_id, attempt)
```

```python
# cashapp/data/repositories/reservations.py
class ReservationConflict(Exception):
    receipt_id: int
class ReservationRepository(BaseRepository[ReceiptReservation]):
    async def reserve(self, receipt_id: int, item_id: int, *, receipt_number: str | None = None,
                      now: datetime | None = None) -> ReceiptReservation
        # INSERT ACTIVE inside session.begin_nested(); unique-index IntegrityError -> ReservationConflict
    async def active_for_item(self, item_id: int) -> ReceiptReservation | None
    async def active_for_receipt(self, receipt_id: int) -> ReceiptReservation | None   # FOR UPDATE SKIP LOCKED
    async def consume(self, item_id: int, *, now: datetime | None = None) -> ReceiptReservation | None
        # s15: ACTIVE -> CONSUMED, released_at=now, reason="consumed"; None (no-op) when nothing active
    async def release(self, item_id: int, reason: str, *, now: datetime | None = None) -> ReceiptReservation | None
        # s13/s38: ACTIVE -> RELEASED, released_at, reason (truncated 1000); None (no-op) when nothing active
    async def release_row(self, row: ReceiptReservation, reason: str, *, now: datetime | None = None) -> ReceiptReservation
    # now=None -> s02 utcnow()

# cashapp/data/repositories/match_candidates.py
@dataclass(frozen=True, slots=True)
class CandidateRow:
    receipt_id: int; receipt_number: str | None; qualifies: bool; score: float
    signals: Mapping[str, float]; reasons: Sequence[str]; chosen: bool; decided_by: DecidedBy
    customer_account_number: str | None; currency: str | None; receipt_date: date | None
    unapplied_amount: Decimal | None
class MatchCandidateRepository(BaseRepository[MatchCandidate]):
    async def next_attempt(self, item_id: int) -> int                       # max(attempt) + 1, starting at 1
    async def add_round(self, item_id: int, attempt: int, rows: Sequence[CandidateRow], *,
                        now: datetime | None = None) -> list[MatchCandidate]
    async def for_item(self, item_id: int, *, attempt: int | None = None) -> list[MatchCandidate]
        # attempt=None -> latest round; ordered chosen desc, score desc, id      (s19/s20)
    async def last_chosen(self, item_id: int) -> MatchCandidate | None      # newest CHOSEN row across rounds
```

```python
# cashapp/stations/match_receipt/runner.py
class MatchReceiptRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.MATCH_RECEIPT
    def __init__(self, deps: RunnerDeps, *, fusion: FusionClient,
                 alias_lookup: Callable[[UnitOfWork], AliasLookup] | None = None,
                 reservations: ReservationService | None = None) -> None
    @classmethod
    def build(cls, container: Container) -> Self
    async def process(self, ctx: StageContext) -> StageOutcome
    # success: Advance(Stage.MATCH_LINES, note=..., payload={"receipt_id": int}); the ACTIVE reservation is the
    # durable hand-off to s15 (ReservationRepository.active_for_item), not the event payload

# cashapp/stations/match_receipt/__init__.py
ROLE: RoleSpec = consumer_role(MatchReceiptRunner, "match-receipt")   # RoleSpec("match-receipt", "consumer", build)
```

DECISION history payload keys (s19/s20 read them): `receipt_id`, `receipt_number`, `decided_by`,
`rule`, `score`, `runner_up_score`, `signals`, `alias_ids`, `window_days`, `basis`
(`receipt_date`|`creation_date`), `resume_applied` (string money), `match_attempt`.

## Migrations

- One hand-written revision `api/alembic/versions/s13_receipt_matching.py`, `revision = "s13_receipt_matching"`.
  **Expected parent: the head when it merges** (written against the latest wave-3/4 head, e.g. s11's
  `CUSTOMER_RESOLUTION` revision). There is no FK to s11's table, so any head works. The merger
  re-points `down_revision` and checks that `alembic heads` returns exactly one head.
- `upgrade()`: `RECEIPT_RESERVATION` (ID identity PK, RECEIPT_ID NUMBER(19), RECEIPT_NUMBER
  VARCHAR2(100), WORK_ITEM_ID FK → WORK_ITEM.ID, STATUS VARCHAR2(40), RESERVED_AT, RELEASED_AT
  TIMESTAMP WITH TIME ZONE, REASON VARCHAR2(1000)); function-based unique index
  `op.create_index("UX_RR_ACTIVE_RECEIPT", "receipt_reservation", [sa.text("CASE WHEN STATUS = 'ACTIVE' THEN RECEIPT_ID END")], unique=True)`;
  `IX_RR_ITEM_STATUS`. `MATCH_CANDIDATE` (ID, WORK_ITEM_ID FK, ATTEMPT, RECEIPT_ID, RECEIPT_NUMBER,
  QUALIFIES NUMBER(1), SCORE BINARY_DOUBLE/Float, SIGNALS JSON, CHOSEN NUMBER(1), DECIDED_BY
  VARCHAR2(40), CREATED_AT, plus the additive REASONS JSON, CUSTOMER_ACCOUNT_NUMBER, CURRENCY CHAR(3),
  RECEIPT_DATE DATE, UNAPPLIED_AMOUNT NUMBER(18,2)); `IX_MC_ITEM_ATTEMPT`.
- `downgrade()`: drop the indexes, then both tables.
- DEV ATP only (via `-m atp` tests). Never production outside a release.

## TEST PLAN (written and run in step 5 only)

Unit tests are pure or on aiosqlite (s02 fixtures); runner tests use `FusionScenario` /
`FakeFusionClient` (s05), `run_stage_once` and `make_runner_deps` (s03), `make_config_snapshot`
/ `make_runtime_config` (s28) and `FrozenClock`. Synthetic data only: customers `C-1001` (anchor) and
`C-2002` (related), invoices `INV-10001…`, payer "Example Payer Co". `-m atp` tests prove the
Oracle-specific index and SKIP LOCKED behaviour on DEV ATP.

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `api/tests/unit/services/matching/test_receipt_scorer.py::test_signature_and_result_shape` | Returns `ScoredCandidates` with one `Candidate` per distinct receipt (`receipt`, `qualifies`, `score`, `signals`, `reasons`), `winner`, `outcome` in the 4 literals; `MatchContext` has the pinned fields; dedupes by `receipt_id`. |
| 1 | `…::test_soft_signal_keys_equal_s12_proposal` | `SOFT_SIGNALS == PROPOSED_SCORER_WEIGHT_KEYS`. |
| 2 | `…::test_currency_mismatch_disqualifies` | Reason `currency_mismatch`. |
| 2 | `…::test_amount_tolerance_per_currency_boundary` | USD diff 0.10 qualifies, 0.11 not; INR 0.49 qualifies, 0.50 not; `money_eq` sets `amount_exact`. |
| 2 | `…::test_bank_fee_band_qualifies_with_signal` | Payment 1000.00, unapplied 985.00, band USD 10–20 → qualifies, `bank_fee_band`; band `"*"` fallback. |
| 2 | `…::test_receipt_date_window_and_widen_hint` | ±W inclusive; W+1 fails; `widen_window_days=2` admits W+2. |
| 2 | `…::test_creation_date_window_only_when_hinted` | Receipt date outside, creation date inside: fails without hint, qualifies with `match_on_creation_date` and signal `date_creation_window`. |
| 2 | `…::test_owner_anchor_related_other` | Anchor → `owner_anchor`, related → `owner_related`, other/None → `not_owner`. |
| 2 | `…::test_soft_signals_and_weighted_score` | Reference, invoice overlap (fractional), bank account via evidence, date distance, alias, customer history strengths; score = Σ weight × strength with s12's provisional weights; missing weight → 0. |
| 2 | `…::test_normalise_reference_keeps_credit_memo_suffix` | `" #inv 1 "` → `"INV1"`; `"2598014-1" != "25980141"`. |
| 3 | `…::test_duplicate_amount_is_ambiguous` | Two anchor receipts, same amount and date, no reference → `ambiguous`, `winner is None`. |
| 3 | `…::test_duplicate_amount_with_matching_reference_matches` | Same pair, one carries the remittance reference → `matched`, rule `outright`. |
| 3 | `…::test_exact_invoice_set_wins_outright` | Receipt references == invoice set → matched over a higher-score peer. |
| 3 | `…::test_two_outright_candidates_stay_ambiguous` | Both carry the reference → `ambiguous` (never first-wins). |
| 3 | `…::test_single_qualifier_matches` | One qualifier among non-qualifiers → `matched`, rule `single`. |
| 3 | `…::test_anchor_tier_beats_related_tier` | One anchor + one related qualifier → anchor matched (`tier_anchor`); two related only → ambiguous. |
| 3 | `…::test_narrow_hint_requires_min_score_margin` | `narrow` + margin ≥ `min_score` → matched (`narrowed`); margin below or equal scores → ambiguous; no hint → ambiguous. |
| 3 | `…::test_grounded_amount_near_miss_is_variance` | Only candidate fails amount but carries the reference → `variance`. |
| 3 | `…::test_ungrounded_amount_miss_is_none` | In-window receipt of another amount, no grounding → `none` (keeps the await-receipt path). |
| 3 | `…::test_nothing_in_window_is_none` | Empty pool or all out of window → `none`. |
| 4 | `api/tests/unit/data/test_receipt_matching_schema.py::test_models_columns_and_indexes` | Exact AC4 columns (+ additive ones), FKs, `UX_RR_ACTIVE_RECEIPT` unique expression index, names ≤ 30 chars. |
| 4 | `…::test_migration_matches_models_and_single_head` | Offline Oracle SQL of the revision contains both tables, the `CASE WHEN STATUS = 'ACTIVE'` unique index; `alembic heads` == 1. |
| 4 | `…::test_second_active_reservation_rejected_sqlite` | Two ACTIVE rows for one receipt → `ReservationConflict`; ACTIVE + RELEASED allowed. |
| 4 | `api/tests/integration/test_receipt_matching_atp.py::test_upgrade_downgrade_and_function_index_atp` (`atp`) | Upgrade/downgrade round-trip on DEV ATP; second ACTIVE insert raises ORA-00001; SIGNALS round-trips as native JSON. |
| 4 | `…::test_active_for_receipt_skip_locked_atp` (`atp`) | Two sessions: the second sees `None` while the first holds the row lock. |
| 5 | `api/tests/integration/stations/test_match_receipt_runner.py::test_happy_path_reserves_logs_and_advances` | Advance(MATCH_LINES, payload receipt_id); one ACTIVE reservation; every searched receipt in `MATCH_CANDIDATE` (one `CHOSEN`, `DECIDED_BY=system`); DECISION history payload has signals and `alias_ids`. |
| 5 | `…::test_candidates_persisted_when_ambiguous` | `RECEIPT_AMBIGUOUS` raised via the failure handler; `MATCH_CANDIDATE` rows still committed; no reservation. |
| 5 | `…::test_none_raises_receipt_not_yet_available_and_variance_raises_amount_variance` | Parametrized error codes and detail keys. |
| 5 | `…::test_creation_date_search_when_hinted` | `FakeFusionClient.calls` has `find_receipts(..., by="creation_date")` only with the hint; window = config + `widen_window_days`. |
| 5 | `…::test_human_hint_receipt_chosen_and_recorded_human` | `HUMAN_HINTS.receipt_id` wins over the scorer; `DECIDED_BY=human`; wrong currency or zero unapplied → `AMOUNT_VARIANCE`. |
| 5 | `…::test_releases_own_earlier_reservation_on_rematch` | Item held receipt R1, now matches R2 → R1 RELEASED with reason, R2 ACTIVE, history row. |
| 5 | `…::test_reserved_by_active_item_raises_receipt_reserved` | Another PENDING item holds the receipt → `RECEIPT_RESERVED` with `holder_item_id`; holder's reservation untouched. |
| 5 | `…::test_stale_holder_released_with_history_on_both` | Holder ESCALATED (no live lock) → released; DECISION rows on both items; new reservation ACTIVE. Holder ESCALATED **with** a live person lock → `RECEIPT_RESERVED`. |
| 5 | `…::test_missing_resolution_or_payment_date` | No `CUSTOMER_RESOLUTION` → `CUSTOMER_NOT_FOUND`; null payment date → `MISSING_PAYMENT_DATE`. |
| 5 | `…::test_alias_lookup_failure_does_not_fail_match` | Raising alias lookup → still matched; `alias_ids` empty. |
| 5 | `…::test_evidence_report_missing_is_ignored` | No report in the fake → matched on the other signals; one warning, no PII in the log record. |
| 5 | `…::test_redelivery_after_advance_is_noop` | Second delivery skipped by s03; one reservation, one candidate round. |
| 6 | `api/tests/unit/data/test_reservation_repository.py::test_reserve_and_active_for_item` | Row ACTIVE with `reserved_at`; `active_for_item` returns it. |
| 6 | `…::test_consume_and_release_are_idempotent` | `consume` → CONSUMED, `released_at`; `release(item, reason)` → RELEASED with reason; second call returns `None`; never commits. |
| 6 | `…::test_release_row_and_active_for_receipt` | `release_row` frees the receipt for another item. |
| 6 | `api/tests/unit/data/test_match_candidate_repository.py::test_rounds_latest_and_last_chosen` | `next_attempt` 1, 2…; `for_item` latest round order; `last_chosen` across rounds. |
| 7 | `api/tests/unit/services/matching/test_receipt_scorer.py::test_resume_applied_adjusts_effective_amount` | Payment 1000.00, receipt 1000.00 half-applied (unapplied 500.00), `resume_applied={R: 500.00}` → qualifies; without it → amount miss. |
| 7 | `api/tests/integration/stations/test_match_receipt_runner.py::test_retry_after_partial_apply_matches_same_receipt` | Scenario: receipt R half-applied to this remittance's invoice (`FusionScenario.application`), item holds ACTIVE reservation on R → re-run matches R again, reservation kept (not duplicated), `resume_applied` in DECISION payload; reversed applications ignored. |
| 7 | `…::test_prior_receipt_from_match_candidate_when_no_reservation` | No reservation but a `CHOSEN` candidate row → same resume behaviour; prior receipt fetched with `get_receipt` when outside the search. |
| 8 | `api/tests/unit/stations/test_match_receipt_role.py::test_role_spec` | `ROLE.name == "match-receipt"`, `ROLE.kind == "consumer"`, `ROLE.build(FakeContainer(...))` yields a `StageConsumer` around `MatchReceiptRunner` (FusionClient registered). |
| layering | `…::test_scorer_is_pure_and_no_sqlalchemy_outside_data` | `services/matching/*.py` and `stations/match_receipt/*.py` import no `sqlalchemy`; `receipts.py` imports no `cashapp.data` or `cashapp.integrations` beyond `fusion.models`. |

## Assumptions and deviations

- **Signature additions (additive only):** `MatchContext.resume_applied`, `Candidate.amount_diff`/
  `owner_tier`, `ScoredCandidates.rule`, keyword-only `evidence=` on `score_candidates`, and `now=` /
  `receipt_number=` keywords on the repository. The AC call shapes still work unchanged.
- **Anchor first is a tier, not a tie-break.** Exactly one anchor-owned qualifier matches even if
  related customers also have a qualifying receipt. More than one in the tier is ambiguous. This
  follows CLAUDE.md ("anchor-owned receipts first, then related") and §4.5's ordered passes, without
  first-wins inside a tier.
- **AMOUNT_VARIANCE requires grounding.** A near miss counts only when the receipt carries a
  reference, invoice overlap or bank-account match for this remittance. Otherwise the outcome is
  `none` → `RECEIPT_NOT_YET_AVAILABLE`, so a customer's unrelated receipts in the window don't
  escalate items that should wait for their receipt (the 71% timing case). This narrows AC3's wording.
- **Weights come only from config.** s02's default `matching.scorer_weights` is `{}`. Until an admin
  sets s12's provisional proposal on the configuration screen, every score is 0. Narrowing can then
  never succeed, and ambiguous items escalate. That's safe, but less automated. No weights are
  hard-coded (a second copy would be a defect).
- **`customer_history`** is computed from ownership for now (anchor 1.0, related 0.5). Real payer
  history (which receipts this payer's past remittances took) needs s12's live study. The key and
  weight are already in place.
- **FIX_HINTS `narrow`** isn't in s02's `FixHints` TypedDict. It's read with `.get("narrow")`; s18
  appends the key. `widen_window_days` and `match_on_creation_date` are already pinned.
- **Human-hint rejection** (wrong currency, nothing unapplied) raises `AMOUNT_VARIANCE` with a
  `reason`, because s18 escalates that code straight to a person. No new error code is added.
- **Stale holder:** ESCALATED/ARCHIVED *and* no live person lock (s40). A holder a person is working
  on is never released behind them (CLAUDE.md "never act on an item a person is working"), so it
  raises `RECEIPT_RESERVED`.
- **Statement reference and payer bank account** come from s12's BIP receipt-signals report
  (`RECEIPT_SIGNALS_REPORT_PATH`; s32 creates it in each tenant). When it's missing, the signals are 0
  and matching continues. This is UNVERIFIED against a live pod.
- **Dependencies not yet planned** (coded against the story Deps; the merger reconciles names):
  `CustomerResolutionRepository.latest_for(item_id)` → `anchor_customer_number`,
  `related_customer_numbers`, `alias_ids`, `transactions: list[FusionTransaction]` (s11);
  `AdjudicationRepository.latest_for(item_id).final` parsed with `RemittanceExtraction.model_validate`
  (s09/s08); `AliasLookup.lookup(payer_name, bank_account, references) -> AliasMatch` (s37). The
  default `alias_lookup` factory is `lambda uow: AliasService(uow)`. If s37 pins another constructor,
  only that one line changes. Whether `lookup` is sync or async is detected with
  `inspect.isawaitable`.
- `MATCH_CANDIDATE.ATTEMPT` is the match round for the item (1, 2, …), not `WORK_ITEM.ATTEMPTS`.
- `SCORE` is a float (as the AC types it), not money.
- `Advance.payload` only reaches the history row (s03). s15 finds the receipt through
  `ReservationRepository.active_for_item`.
- PO/SO/ERS-only and prepayment policy checks belong to s10/s18 (`policy_check`) and are not repeated
  here.

## Risks

- **The function-based unique index on ATP** (`CASE WHEN … END`) and SQLAlchemy's
  `Index(case(...))` render differently. The model and the migration are both checked by the offline
  SQL test, and the `atp` test proves ORA-00001. If DEV ATP rejects the expression, the fallback is a
  virtual column `ACTIVE_RECEIPT_ID` with a plain unique index. It would be recorded here.
- **Savepoint plus IntegrityError on Oracle:** `begin_nested` is needed so a lost race doesn't poison
  the stage transaction. The `atp` test covers it.
- **Mid-process commit** releases the item's `FOR UPDATE` row lock before reserving. s03's claim
  (state `IN_PROGRESS` plus claim expiry) still excludes other workers. The reservation and the
  transition commit together at the end.
- **Empty weights reduce automation** (see Assumptions). Flag it to Jonathan: set s12's proposal via
  s21 at go-live.
- **Fusion `standardReceipts` field names** (remittance references, creation date) are UNVERIFIED
  (s05). The scorer depends only on `FusionReceipt`, so a field mapping fix stays in s05.
- **Cross-item contention** on one receipt (split payments funded by one receipt) always goes to a
  person (`RECEIPT_RESERVED`), as the story assumes. That may be common for some payers. It's
  measured once the flow monitor shows it.
