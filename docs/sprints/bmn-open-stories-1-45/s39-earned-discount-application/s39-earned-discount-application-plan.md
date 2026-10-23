# Plan: s39-earned-discount-application

Issue #39. Wave 5, on the money path. Paths below are written as `cashapp/`, meaning `api/src/cashapp/`.

This story owns `cashapp/services/matching/discount.py`. It also makes planned edits to s15's line planner and its two runners, and to s05's Fusion package: s05's plan says "s39 edits this package".

The feature is built behind `discount.enabled` (s02 registry, default `false`) and works against the fake. The live probes (AC1) confirm the Fusion contract. Until they have run, every new Fusion name carries `# UNVERIFIED:` and has a row in `CONTRACTS.md`.

There is no LLM call and no UI in this story.

## Standards followed

- **CLAUDE.md *Matching and apply rules*.**
  - "Never invent a discount. Take one only when the remittance references it and the payment terms earned it."
  - A tolerance widens the *match* only. The amounts actually sent are real amounts, and the residual is recorded.
  - Each line's result is persisted as it happens.
  - Fusion's existing applications are checked before every apply.
- **CLAUDE.md *Fusion integration*.**
  - All traffic goes through the one `FusionClient`.
  - "Never guess an endpoint, payload or field name." The payment-terms resource, its fields, `DiscountTaken`, and the Fusion fault code for a rejected discount are all UNVERIFIED until the `-m live` probes confirm them. The coder looks for the resource with `aix-greenlight` `fusion_rest_describe` and doesn't guess.
- **Reference doc §4, "Agreed but not built".** The rule is: receipt ≈ balance − discount within tolerance, and `DiscountTaken` goes on the same apply call.
- **One status enum (non-negotiable 7).** `LineStatus.ALLOCATION_APPLIED_WITH_DISCOUNT`, `InfoFlag.DISCOUNT_REJECTED_BY_FUSION` and `ErrorCode.FUSION_DISCOUNT_REJECTED` are imported from s02. This story defines no status strings of its own.
- **Money.** It is `Decimal` throughout. `to_money` gives 2 dp with `ROUND_HALF_UP`, and comparisons use `money_eq` or `abs(a - b) <= tolerance`. Floats are never used.
- **`python-web-app:building-python-web-apps`.**
  - Logic lives in `services/`, and `earned_discount` is pure.
  - The Fusion SDK surface stays in `integrations/fusion/`.
  - Runners only orchestrate.
  - pyright strict and ruff apply. Nothing is imported from SQLAlchemy outside the data layer.
- **research.md.** There are exactly two Fusion implementations, real and fake, and the fake is never presented as a confirmed contract. No third variant is added: the flag is runtime configuration, not a code path fork.

## Files to touch

| Path | New/edit | Contents |
|---|---|---|
| `cashapp/services/matching/discount.py` | new (owned) | `DiscountReason`, `DiscountDecision`, `DiscountContext`, `earned_discount(...)`, `load_payment_terms(...)`, `discount_audit(...)` |
| `cashapp/services/matching/lines.py` | edit (s15) | `plan_lines(..., *, discount: DiscountContext \| None = None)`; `LineStep.discount_amount`, `LineStep.discount_reason`; with-discount target status |
| `cashapp/stations/match_lines/runner.py` | edit (s15) | when `cfg.discount().enabled`: load the terms, build `DiscountContext`, pass it to `plan_lines`; PLANNED ledger rows carry `DISCOUNT_AMOUNT`; the DECISION history payload carries the per-line discount audit |
| `cashapp/stations/apply/runner.py` | edit (s15) | `ApplyRequest.discount_amount` from the ledger row; handling for `FUSION_DISCOUNT_REJECTED`, which falls back to cash only through s15's existing per-line apply helper |
| `cashapp/integrations/fusion/models.py` | edit (s05) | `DiscountTier`, `PaymentTerms`; `FusionTransaction.transaction_date: date \| None = None`; `FusionApplication.discount_amount: Decimal \| None = None` |
| `cashapp/integrations/fusion/query.py` | edit (s05) | `FIELDS_PAYMENT_TERMS*`, `PAYMENT_TERMS_RESOURCE*`; add `TransactionDate*` to the invoice fields |
| `cashapp/integrations/fusion/client.py` | edit (s05) | `get_payment_terms` on the `FusionClient` Protocol and on `HttpFusionClient`; parse `transaction_date` |
| `cashapp/integrations/fusion/errors.py` | edit (s05) | `DISCOUNT_REJECT_CODES*` feeds `FUSION_CODE_MAP` → `FUSION_DISCOUNT_REJECTED`; precedence slot placed after ALREADY_APPLIED |
| `cashapp/integrations/fusion/guard.py` | edit (s05), only if `read_only()` proxies methods explicitly | pass `get_payment_terms` through as a read |
| `cashapp/integrations/fusion/fake.py` | edit (s05) | `payment_terms=` constructor kwarg, `get_payment_terms`, and discount-aware `apply_receipt` and `unapply_receipt` (see the fake behaviour section) |
| `cashapp/integrations/fusion/CONTRACTS.md` | edit (s05) | rows for the payment-terms resource and fields, `TransactionDate`, `DiscountTaken`, the discount reject codes and the application's discount field |
| `api/tests/support/fusion.py` | edit (s05) | `FusionScenario.payment_terms(name, tiers, *, term_id=None)`; `invoice(..., transaction_date: date \| None = None)`; JSON shape gains `"payment_terms": [...]` and `"transaction_date"` |
| `api/tests/unit/services/matching/test_discount.py` | new | AC2 |
| `api/tests/unit/services/matching/test_lines_discount.py` | new | AC3 |
| `api/tests/unit/fusion/test_fusion_payment_terms.py` | new | AC1 unit side (respx and fake) |
| `api/tests/integration/stations/test_apply_discount.py` | new | AC4, AC5 |
| `api/tests/live/fusion/test_fusion_discount_live.py` | new | AC1 live probes (`@pytest.mark.live`) |

**Not touched:**
- `domain/status.py`, `domain/error_codes.py` and `domain/config_keys.py`: s02 already defines every member this story needs.
- `services/config*.py`: s28 already has `DiscountConfig` and `discount()`.
- `soap.py`: s05 already writes `DiscountTaken` when `discount_amount` is not None.
- The Alembic tree, `main.py` and the lockfiles.

## Design

### `earned_discount` (pure; `services/matching/discount.py`)

```python
class DiscountReason(StrEnum):
    EARNED = "earned"
    NOT_CLAIMED = "not-claimed"                  # remittance doesn't reference a discount on this line
    INVALID_CLAIM = "invalid-claim"              # claimed <= 0 or >= balance
    NOT_AN_INVOICE = "not-an-invoice"            # credit memos never take a discount
    NO_STATED_AMOUNT = "no-stated-amount"
    NO_TERMS = "no-terms"                        # transaction has no terms, or terms not found
    TERMS_HAVE_NO_DISCOUNT = "terms-have-no-discount"
    NO_TRANSACTION_DATE = "no-transaction-date"
    PAYMENT_BEFORE_INVOICE = "payment-before-invoice"
    NOT_EARNED = "not-earned"                    # paid after every tier's days
    CLAIM_MISMATCH = "claim-mismatch"            # no earned tier's computed discount ≈ claimed
    AMOUNTS_DONT_RECONCILE = "amounts-dont-reconcile"   # stated + discount not ≈ balance
    RECEIPT_REMAINING_SHORT = "receipt-remaining-short" # set by plan_lines (cash would be capped)
    DISABLED = "disabled"                        # set by plan_lines when discount.enabled is false
```

`earned_discount(transaction, terms, payment_date, claimed, stated_amount, tolerance)` applies these checks in order and returns at the first one that fails, always with a reason:

1. Is a discount claimed at all (`claimed` present)?
2. Is the transaction an invoice?
3. Is there a stated amount?
4. Is the claim valid (greater than 0 and less than the balance)?
5. Are the terms present, and do they carry tiers?
6. Is there a transaction date?
7. Compute `elapsed = (payment_date - transaction_date).days`. If it is negative, the result is `PAYMENT_BEFORE_INVOICE`.
8. Find the earned tiers: those with `elapsed <= tier.days`, sorted by days ascending. If there are none, the result is `NOT_EARNED`.
9. For each earned tier in that order, compute `computed = to_money(balance * percent / 100)`. The first tier with `|computed - claimed| <= tolerance` is chosen. If no tier qualifies, the result is `CLAIM_MISMATCH`.
10. Set `amount = min(claimed, computed)`, so the discount is never more than the customer claimed and never more than was earned. Then require `|stated_amount + amount - balance| <= tolerance`, otherwise the result is `AMOUNTS_DONT_RECONCILE`.
11. If every check passes, the result is `EARNED`, with `amount`, `tier` and `computed`.

`balance` is the transaction's current Fusion balance, which is what AC2 says. `tolerance` is `cfg.matching().tolerance_for(currency)`.

### `plan_lines` (s15) with a discount

- The new keyword is `discount: DiscountContext | None = None`. `None` means disabled: `plan_lines` behaves exactly as in s15 and never sets `discount_amount`.
- A disabled run in which a line claims a discount gets reason text in `LineResultDraft.reason` ("discount claimed; discount application disabled"). Its status is unchanged, so it is a short pay as before.
- When enabled, the planner decides the discount for each *valid* invoice line, after s15's verdict chain and dedupe, and before the cap. If the decision is `EARNED`:
  - It computes `cash = min(stated, balance - discount, receipt_remaining)`.
  - If `cash < stated` (the receipt is short), it drops the discount with `RECEIPT_REMAINING_SHORT` and falls back to s15's normal cap and status. Otherwise the step gets `amount = stated`, `discount_amount = discount` and `target_status = ALLOCATION_APPLIED_WITH_DISCOUNT`.
- Receipt-remaining accounting subtracts only the cash; the discount isn't receipt money.
- `residual = balance - cash - discount` is recorded on the draft. It is close to 0 and lies within tolerance.
- Duplicate lines are summed by s15. Their claimed discounts are summed only when *every* duplicate states one. Otherwise `claimed=None`, giving `NOT_CLAIMED`, so a discount is never inferred.
- Every step carries `discount_reason`, and `discount_audit(steps)` turns these into the per-line audit payload.

### MatchLinesRunner (s15) edit

```python
cfg = await self.config.snapshot()
ctx = None
if cfg.discount().enabled:
    names = {t.payment_terms for t in transactions.values() if t.payment_terms and <some line claims on t>}
    terms = await load_payment_terms(self.fusion, names)     # deduped; None results omitted
    ctx = DiscountContext(payment_date=item.payment_date, terms=terms,
                          tolerance=cfg.matching().tolerance_for(item.currency))
plan = plan_lines(..., discount=ctx)
```

- `load_payment_terms`:
  - A retryable `FusionError` (transient or locked) propagates as a `StageError` through s15's normal runner path, so the item retries.
  - A non-retryable error, or terms that aren't found, leaves that name out, and the affected lines get `NO_TERMS`, which makes them short pays.
- PLANNED `APPLICATION_LEDGER` rows set `DISCOUNT_AMOUNT = step.discount_amount`, and `REQUEST` JSON includes it as a string.
- The DECISION history row's payload gains `discounts: discount_audit(plan.steps)`. Each entry has the line number, reason, claimed, computed, tier and amount, which answers "why did the system take this discount?".

### ApplyRunner (s15) edit

1. The `ApplyRequest` comes from the ledger row as before, plus `discount_amount=row.discount_amount`. That is a positive amount, never set on a credit memo. Cash and discount go on one call.
2. On success:
   - The ledger row becomes APPLIED with `DISCOUNT_AMOUNT`.
   - The `LINE_RESULT` gets status `ALLOCATION_APPLIED_WITH_DISCOUNT`, `DISCOUNT_AMOUNT` and `RESIDUAL`.
   - A FUSION_WRITE history row's payload includes `discount_amount`.
   - All of this is persisted in the line's own transaction, as s15 does.
3. On `result.fault.code == FUSION_DISCOUNT_REJECTED`, two transactions follow.
   - **Transaction A:**
     - A FUSION_WRITE history row records attempt 1, with error code `FUSION_DISCOUNT_REJECTED`, the Fusion messages and the discount sent.
     - The ledger row stays PLANNED but its `DISCOUNT_AMOUNT` is set to null, and `RESPONSE_MESSAGES` becomes `{"attempts": [<attempt-1 messages>]}`.
     - `item.info_flags` is reassigned to a merged list (existing values in order, then `discount-rejected-by-fusion`, deduplicated), the same merge pattern s10 and s11 use. Then it commits.
     - Because this is committed first, a crash afterwards resumes as a plain cash-only PLANNED row and never re-sends the rejected discount.
   - **Transaction B:** the same row goes through s15's existing per-line apply helper again: the idempotency re-check of existing applications, then `apply_receipt` without a discount. This is not a second apply path.
     - On success, the `LINE_RESULT` is `ALLOCATION_APPLIED_SHORT_PAY` if `cash < balance`, using s15's own rule, with reason "discount rejected by Fusion; applied cash only". A second FUSION_WRITE history row records attempt 2, and `RESPONSE_MESSAGES.attempts` is appended.
     - A fault on the cash-only call is handled exactly as s15 handles any fault on a line.
4. Any other fault on a discounted call (OVERAPPLY, ALREADY_APPLIED, GL_DATE, LOCKED and so on) takes s15's existing route unchanged.

### Fusion edits (s05 package)

```python
# models.py
@dataclass(frozen=True, slots=True)
class DiscountTier: days: int; percent: Decimal          # percent as 2.00 for 2%
@dataclass(frozen=True, slots=True)
class PaymentTerms: term_id: int | None; name: str; discount_tiers: tuple[DiscountTier, ...]   # sorted by days asc
# FusionTransaction gains (last, defaulted): transaction_date: date | None = None   # invoices: TransactionDate*
# FusionApplication gains (last, defaulted): discount_amount: Decimal | None = None  # earned discount on the application*
```

- `get_payment_terms(term: int | str) -> PaymentTerms | None`:
  - An `int` is a term id and a `str` is a name.
  - The call is a REST GET on the resource the live probe confirms, using `q=Name=<q_literal>` or the id path. Tiers come from its discount child or fields, all UNVERIFIED.
  - It returns `None` when there is no such term. Transport errors raise `FusionError` as usual.
- Fake behaviour (pinned):
  - `get_payment_terms` looks terms up by id or name from the `payment_terms=` kwarg or the scenario.
  - `apply_receipt` with `discount_amount` set:
    - A credit memo gets fault `FUSION_DISCOUNT_REJECTED`.
    - If the transaction has no terms or no `transaction_date`, if `application_date` is past every tier, or if `discount > to_money(balance × best earned percent) + 0.005`, the fault is `FUSION_DISCOUNT_REJECTED`.
    - If `amount + discount > balance`, the fault is `FUSION_OVERAPPLY`.
    - On success, `balance` drops by `amount + discount` and the receipt's `unapplied` drops by `amount` only. `FusionApplication.discount_amount` is set.
    - The fake's faults for discount rejection carry `fusion_code=None` until the probe records the real code.
  - `unapply_receipt` restores `amount + discount` to the balance.
  - `fail_next("apply_receipt", FusionFault(FUSION_DISCOUNT_REJECTED, ...))` also works.
- In `errors.py`, `DISCOUNT_REJECT_CODES: frozenset[str]` starts empty and is UNVERIFIED. The live probe adds the real code, or codes, and each maps to `FUSION_DISCOUNT_REJECTED` in `FUSION_CODE_MAP`. In `fault_from_messages`, the precedence becomes OVERAPPLY > ALREADY_APPLIED > DISCOUNT_REJECTED > GL_DATE > LOCKED. Until the code is confirmed, a rejection arrives as `FUSION_FAULT`, so the line fails and goes to a person. That is fail-closed, and it is one reason `discount.enabled` stays false.

## Interfaces provided (pinned)

```python
# cashapp/services/matching/discount.py
class DiscountReason(StrEnum): ...            # members as listed above
@dataclass(frozen=True, slots=True)
class DiscountDecision:
    amount: Decimal | None                    # None => no discount (treat as short pay)
    reason: DiscountReason
    tier: DiscountTier | None = None
    computed: Decimal | None = None
    claimed: Decimal | None = None
@dataclass(frozen=True, slots=True)
class DiscountContext:
    payment_date: date
    terms: Mapping[str, PaymentTerms]         # keyed by FusionTransaction.payment_terms
    tolerance: Decimal
def earned_discount(transaction: FusionTransaction, terms: PaymentTerms | None, payment_date: date,
                    claimed: Decimal | None, stated_amount: Decimal | None, tolerance: Decimal) -> DiscountDecision
async def load_payment_terms(fusion: FusionClient, names: Iterable[str]) -> dict[str, PaymentTerms]
def discount_audit(steps: Sequence[LineStep]) -> list[dict[str, str | int | None]]   # Decimal as str

# cashapp/services/matching/lines.py  (s15 types, fields added by s39; defaults keep s15 callers valid)
class LineStep: ...; discount_amount: Decimal | None = None; discount_reason: DiscountReason | None = None
class LineResultDraft: ...; discount_amount: Decimal | None = None
def plan_lines(lines, transactions, receipt_remaining, existing, payment_currency, *,
               discount: DiscountContext | None = None) -> LinePlan

# cashapp/integrations/fusion
class DiscountTier; class PaymentTerms                    # as above
class FusionClient(Protocol):
    async def get_payment_terms(self, term: int | str) -> PaymentTerms | None: ...
FusionTransaction.transaction_date: date | None = None
FusionApplication.discount_amount: Decimal | None = None
DISCOUNT_REJECT_CODES: frozenset[str]
# tests/support/fusion.py
FusionScenario.payment_terms(name: str, tiers: Sequence[tuple[int, str | Decimal]], *, term_id: int | None = None) -> Self
FusionScenario.invoice(..., transaction_date: date | None = None)
```

Consumers:
- **s17:** the write-back note can read `LINE_RESULT.DISCOUNT_AMOUNT` and the `discount-rejected-by-fusion` flag.
- **s20:** the workbench shows `DISCOUNT_AMOUNT`.
- **s38:** reversal compares `FusionApplication.amount_applied`, and `discount_amount` is now available to it.
- **s23:** may use `transaction_date` and terms.

## Migrations

None. s15's revision already creates `LINE_RESULT.DISCOUNT_AMOUNT` and `APPLICATION_LEDGER.DISCOUNT_AMOUNT`. The `discount.enabled` key is s02's, stored through s28's tables. The expected Alembic head is unchanged; `alembic heads` must still return one head.

## Test plan

These tests are written and run only in step 5. Paths are under `api/tests/`.

| AC | Test | Asserts |
|---|---|---|
| 1 | `unit/fusion/test_fusion_payment_terms.py::test_get_payment_terms_by_name_parses_tiers` | respx: `REST-Framework-Version: 4`, `onlyData=true`, explicit `fields=`, `q=` escaped; tiers become `DiscountTier(days:int, percent:Decimal)` sorted ascending; no floats |
| 1 | `…::test_get_payment_terms_by_id_and_unknown_returns_none` | id path used for an `int`; an empty result gives `None` |
| 1 | `…::test_find_transactions_reads_transaction_date` | invoice `TransactionDate` is parsed to `date`; a missing value gives `None` |
| 1 | `…::test_apply_envelope_carries_discount_taken_with_cash` | one envelope holds both `AmountApplied` and `DiscountTaken` (`"20.00"`) |
| 1 | `…::test_discount_reject_codes_map_to_fusion_discount_rejected` | every code in `DISCOUNT_REJECT_CODES` → `FUSION_DISCOUNT_REJECTED`; precedence below ALREADY_APPLIED, above GL_DATE |
| 1 | `…::test_fake_payment_terms_and_discount_apply` | fake: an earned discount decrements balance by cash+discount and unapplied by cash; unearned and credit memo give `FUSION_DISCOUNT_REJECTED`; unapply restores both |
| 1 | `…::test_contracts_md_has_discount_rows` | `CONTRACTS.md` lists payment-terms resource, fields, `TransactionDate`, `DiscountTaken`, reject codes (s05's marker test also covers the new `# UNVERIFIED:` tags) |
| 1 | `live/fusion/test_fusion_discount_live.py::test_live_get_payment_terms` (`-m live`) | resource and field names confirmed on the non-prod pod; `record_confirmation` updates `CONTRACTS.md` |
| 1 | `…::test_live_apply_with_discount_taken` (`-m live`, needs `CASHAPP_FUSION_LIVE_WRITES=1` and s23-tagged data) | an earned-terms invoice gets cash + `DiscountTaken` on one call; balance is 0 |
| 1 | `…::test_live_unearned_discount_rejection_code` (`-m live`, writes) | the rejection's Fusion code is captured and recorded for `DISCOUNT_REJECT_CODES` |
| 2 | `unit/services/matching/test_discount.py::test_earned_when_claimed_within_tier_and_reconciles` | 2%/10 days, balance 1000.00, claimed 20.00, stated 980.00 → `EARNED`, amount 20.00 |
| 2 | `…::test_not_claimed_never_discounts` | `claimed=None` → `NOT_CLAIMED`, amount None ("never invent") |
| 2 | `…::test_paid_after_tier_days_not_earned` | elapsed 11 days → `NOT_EARNED` |
| 2 | `…::test_claim_mismatch_beyond_tolerance` | claimed 25.00 vs computed 20.00 → `CLAIM_MISMATCH` |
| 2 | `…::test_amounts_dont_reconcile` | stated 900.00 + 20.00 ≠ 1000.00 → `AMOUNTS_DONT_RECONCILE` |
| 2 | `…::test_round_half_up_and_inr_tolerance` | balance 1234.25 × 2% = 24.685 → 24.69 (HALF_UP, not banker's); INR 0.49 tolerance accepts a 0.40 gap |
| 2 | `…::test_amount_is_min_of_claimed_and_computed` | claimed 20.05, computed 20.00, tol 0.10 → amount 20.00 |
| 2 | `…::test_multi_tier_picks_first_earned_matching_tier` | 2%/10 and 1%/30; day 20 → 1% tier; day 5 with a 1% claim → 1% tier |
| 2 | `…::test_guards` (parametrised) | credit memo, no stated amount, claim ≤ 0 or ≥ balance, no terms, no tiers, no transaction date, payment before invoice → the matching reason, amount None |
| 3 | `unit/services/matching/test_lines_discount.py::test_disabled_never_discounts` | `discount=None` with a claimed, earned line → no `discount_amount`, s15 short-pay status, reason mentions disabled |
| 3 | `…::test_enabled_step_carries_discount_and_with_discount_status` | `discount_amount` 20.00, cash 980.00, target `ALLOCATION_APPLIED_WITH_DISCOUNT`, residual 0.00 |
| 3 | `…::test_receipt_short_drops_discount` | receipt remaining < stated → no discount, `RECEIPT_REMAINING_SHORT`, s15 cap applies |
| 3 | `…::test_receipt_remaining_consumes_cash_only` | two discounted lines: remaining reduced by the cash only |
| 3 | `…::test_duplicate_lines_claim_summed_only_when_all_claim` | one duplicate without a claim → `NOT_CLAIMED` |
| 3 | `integration/stations/test_apply_discount.py::test_match_lines_disabled_makes_no_terms_call` | `discount.enabled=false` → no `get_payment_terms` in `fake.calls`; ledger `DISCOUNT_AMOUNT` null |
| 3 | `…::test_match_lines_enabled_plans_discount_and_records_decision` | PLANNED ledger `DISCOUNT_AMOUNT`=20.00; DECISION history payload `discounts[0].reason == "earned"` |
| 4 | `…::test_apply_sends_discount_on_same_call` | exactly one `apply_receipt` call for the line with `amount_applied=980.00`, `discount_amount=20.00`; ledger APPLIED with `DISCOUNT_AMOUNT`; `LINE_RESULT` `allocation-applied-with-discount`, `DISCOUNT_AMOUNT`, residual 0; fake balance 0 |
| 5 | `…::test_discount_rejected_reapplies_cash_only_as_short_pay` | `fail_next(FusionFault(FUSION_DISCOUNT_REJECTED))` → a second call with `discount_amount=None`; `LINE_RESULT` `allocation-applied-short-pay`; `INFO_FLAGS` contains `discount-rejected-by-fusion` once and keeps earlier flags; two FUSION_WRITE history rows (attempt 1 with `FUSION_DISCOUNT_REJECTED`, attempt 2 ok); ledger `RESPONSE_MESSAGES.attempts` has 2 entries |
| 5 | `…::test_crash_after_rejection_resumes_cash_only` | kill after transaction A → re-run makes one cash-only call, never a second discount call |
| 5 | `…::test_other_faults_on_discounted_call_follow_s15_route` | OVERAPPLY on a discounted call raises s15's reroute code; no cash-only retry, no flag |

## Risks

- **Fusion contract unknown (the main risk).** Nobody has confirmed the payment-terms resource name, the tier fields, the discount basis (balance vs original amount vs line amount), whether the discount uses `DiscountTaken`, or the rejection fault code. Everything sits behind UNVERIFIED and `discount.enabled=false`. If the probe shows Fusion computes the discount on the original amount, `earned_discount` gets a `basis` parameter. That would be a refinement recorded in CLAUDE.md, not a new path.
- **Edits to s15 and s05 files in the same wave.** s39 merges after s15 and s05; the merger rebases. The new fields are all defaulted and the new keyword is optional, so s15's and s05's own tests stay valid.
- **The tier semantics are an assumption.** The days are counted from the invoice date to the payment date, inclusive, and the first earned tier whose computed amount matches the claim is used. Fusion may count from the terms' discount date instead. The probe confirms this.
- **s38 reversal.** A discounted application unapplies cash plus discount. The fake's `unapply_receipt` is updated here. s38's "amount changed outside CashApp" check compares `amount_applied` only, which is unaffected.
- **s17 note length.** If s17 adds discount text to the small receipt note field, that is s17's design; nothing is required here.

## Assumptions / deviations

- `get_payment_terms` returns `PaymentTerms | None` instead of the AC's bare `PaymentTerms`. "Not found" is a business outcome (`NO_TERMS`, short pay), not an error.
- `FusionTransaction.transaction_date` and `FusionApplication.discount_amount` are added to s05's models. The AC needs the invoice date for "within a tier's days from the invoice date", and s05's model lacked it.
- The discount amount sent is `min(claimed, computed)`, so it is never more than the remittance references. The AC's "computed equals claimed within tolerance" check still gates it.
- `DISCOUNT_REJECT_CODES` starts empty. Until the probe fills it, a rejection is a `FUSION_FAULT`: the line fails and a person decides. That is fail-closed, and the reason the flag stays off.
- The rejected-discount fallback reuses s15's per-line apply helper. There is no new apply path.
- Credit memos never carry a discount.
