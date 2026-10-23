# s39-earned-discount-application: Earned-discount application

- Issue: #39
- Wave: 5 (money path; owns `cashapp/services/matching/discount.py`; edits s15's `plan_lines` and apply step)
- breaking: false

## Story

As AR, I want a discount applied only when the remittance references it, the payment terms earned it and the amounts agree within tolerance, so that discounts are never invented and earned ones don't show up as short pays.

## Context

Reference doc §4 "Agreed but not built" and §1 ("never invent a discount"). Blocked until the tenant confirms the payment-terms resource and the `createApplyReceipt` discount element: built behind `config.discount().enabled=false` against the fake; the live probe confirms. EU VAT discounts are a Fusion payment-terms fix, not this story.

## Acceptance criteria

1. [integration] Confirmation: `-m live` probes confirm the payment-terms REST resource (name, discount percent/days fields) and the `DiscountTaken`-style element on `createApplyReceipt` on the dev pod; `CONTRACTS.md` updated; `FusionClient.get_payment_terms(term_id|name) -> PaymentTerms{name, discount_tiers: [{days, percent}]}` added to s05's client and fake.
2. [unit] `earned_discount(transaction, terms, payment_date, claimed: Decimal|None, stated_amount, tolerance) -> DiscountDecision{amount: Decimal|None, reason}`: only when `claimed` is present on the line (remittance references it), the payment date is within a tier's days from the invoice date, the computed discount (balance × percent, ROUND_HALF_UP) equals the claimed discount within tolerance, and `stated_amount + discount ≈ balance` within tolerance; otherwise `None` with the reason (treated as a short pay).
3. [unit] `plan_lines` uses it when `config.discount().enabled`: the step carries `discount_amount`, the target status becomes `allocation-applied-with-discount`; disabled → never a discount (test).
4. [unit] The discount is sent on the same `apply_receipt` call (`ApplyRequest.discount_amount`) as the cash; the ledger stores `DISCOUNT_AMOUNT`.
5. [unit] Fusion rejecting the discount (fault mapped to `FUSION_DISCOUNT_REJECTED`) re-applies the cash without the discount on the same line (short pay), sets `InfoFlag.DISCOUNT_REJECTED_BY_FUSION`, and records both attempts in history.

## Out of scope

EU VAT discount handling; write-offs.

## Deps

- s15-line-matching-apply — `plan_lines`, `LineStep`, apply loop, ledger `DISCOUNT_AMOUNT`. plannable.
- s05-fusion-client — `ApplyRequest.discount_amount`, fault mapping; `get_payment_terms` added here. unplannable for the live element (needs tenant confirmation); plannable against the fake.
- s28-runtime-config-service — `config.discount().enabled`, `matching().tolerance_for`. plannable.
- s02-data-layer-foundation — `LineStatus.ALLOCATION_APPLIED_WITH_DISCOUNT`, `InfoFlag.DISCOUNT_REJECTED_BY_FUSION`, `ErrorCode.FUSION_DISCOUNT_REJECTED`. plannable.

## Assumptions

- Disabled by default until the tenant confirmation passes.
