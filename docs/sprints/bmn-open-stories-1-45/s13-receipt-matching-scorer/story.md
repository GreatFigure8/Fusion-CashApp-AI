# s13-receipt-matching-scorer: Receipt matching scorer (multi-signal candidates, reservation, ambiguity is an error)

- Issue: #13
- Wave: 5 (money path; owns `cashapp/stations/match_receipt/`, `cashapp/services/matching/receipts.py`, `cashapp/data/repositories/reservations.py`)
- breaking: false

## Story

As AR, I want receipts found by scoring every candidate on all available signals, with ambiguity treated as an error and the chosen receipt reserved, so that the wrong receipt is never applied and retries resume after a partial apply.

## Context

CLAUDE.md *Matching and apply rules* and reference doc §4.5 + defects (no reservation, first-wins, partial receipts never re-matched). Signals and starting weights come from s12's proposal (`matching.scorer_weights`, provisional). Tolerances and the date window come from runtime config. Amount matching uses the receipt's remaining unapplied amount.

## Acceptance criteria

1. [unit] `score_candidates(ctx: MatchContext, receipts: Sequence[FusionReceipt], config: MatchingConfig, aliases: AliasMatch | None) -> ScoredCandidates{candidates: list[Candidate{receipt, qualifies: bool, score: float, signals: dict[str, float], reasons: list[str]}], winner: Candidate | None, outcome: "matched"|"none"|"ambiguous"|"variance"}` where `MatchContext{payment_amount, currency, payment_date, anchor, related, references, invoice_numbers, payer_bank_account, fix_hints}`.
2. [unit] Hard filters (all must hold to qualify): same currency; `|unapplied_amount − payment_amount| ≤ tolerance_for(currency)` (or within a configured bank-fee band → qualifies with signal `bank_fee_band`); receipt_date within ±`date_window_days` of payment_date, or creation_date within the window when `FIX_HINTS.match_on_creation_date`; owner is anchor or related customer (anchor-owned ranked first). Soft signals add score: remittance reference / statement reference equal to the extraction's reference, invoice-set overlap with the receipt's remittance references, payer bank account match (incl. aliases), date distance, alias-learned reference pattern, customer history.
3. [unit] An exact reference match or exact invoice-set match among qualifying candidates wins outright. Otherwise exactly one qualifying candidate → matched; more than one qualifying → `RECEIPT_AMBIGUOUS` unless `FIX_HINTS.narrow` and the best score beats the runner-up by `matching.min_score` margin — never "first wins" (tests: duplicate-amount scenario is ambiguous; with a matching reference it matches). None qualifying but an amount-only near miss beyond tolerance → `AMOUNT_VARIANCE`; nothing in window → `RECEIPT_NOT_YET_AVAILABLE`.
4. [integration] One Alembic revision creates `RECEIPT_RESERVATION` (ID, RECEIPT_ID, RECEIPT_NUMBER, WORK_ITEM_ID, STATUS (ACTIVE|CONSUMED|RELEASED), RESERVED_AT, RELEASED_AT, REASON; unique RECEIPT_ID where STATUS='ACTIVE' via a function-based unique index) and `MATCH_CANDIDATE` (ID, WORK_ITEM_ID, ATTEMPT, RECEIPT_ID, RECEIPT_NUMBER, QUALIFIES, SCORE, SIGNALS JSON, CHOSEN, DECIDED_BY (system|human), CREATED_AT).
5. [integration] `MatchReceiptRunner` (stage MATCH_RECEIPT): loads the resolution (s11), calls `fusion.find_receipts` for anchor+related over the window (by receipt_date, and by creation_date when hinted), scores, logs EVERY candidate's signals to `MATCH_CANDIDATE`, honours `HUMAN_HINTS.receipt_id` (the chosen receipt must still pass the currency check and have unapplied > 0, recorded `DECIDED_BY=human`), releases this item's own earlier ACTIVE reservation, then reserves the winner with `SELECT … FOR UPDATE SKIP LOCKED` on the receipt's reservation row; if another item holds an ACTIVE reservation and that item is not ESCALATED/ARCHIVED → `StageError(RECEIPT_RESERVED)`; a stale holder's reservation is released with history on both items. Writes a DECISION history row ("why this receipt": signals, alias ids used) and returns `Advance(MATCH_LINES, payload={receipt_id})`.
6. [unit] `ReservationRepository`: `reserve(receipt_id, item_id)`, `active_for_item(item_id)`, `consume(item_id)`, `release(item_id, reason)` — public for s15 (consume), s38 (release).
7. [unit] Re-matching after a partial apply: when the item already holds a reservation (or `MATCH_CANDIDATE` shows a previously chosen receipt), the amount check compares the receipt's `unapplied_amount` with the payment amount minus what Fusion already shows applied from that receipt to this remittance's transactions (`fusion.list_receipt_applications(receipt_id)`), so a retry resumes (test: receipt half-applied, retry matches the same receipt).
8. [unit] `ROLE = RoleSpec("match-receipt", "consumer", build)`.

## Out of scope

Line planning and apply (s15); waking awaiting items (s14).

## Deps

- s05-fusion-client — `find_receipts(customer_numbers, date_from, date_to, by)`, `FusionReceipt`, `FakeFusionClient`. plannable.
- s11-customer-resolution — `CustomerResolutionRepository.latest_for(item_id)` → anchor, related, transactions. plannable.
- s12-spike-receipt-signal-study — signal names and provisional weights for `matching.scorer_weights`. plannable (provisional values; the real study needs the pod).
- s37-payer-alias-learning — `AliasService.lookup`. plannable.
- s28-runtime-config-service — `config.matching()`. plannable.
- s18-auto-fix-engine — `FIX_HINTS` keys `narrow`, `match_on_creation_date`, `widen_window_days`; handlers for RECEIPT_* codes. plannable.
- s03-pipeline-runtime — `StageRunner`. plannable.
## Assumptions

- A receipt funds at most one remittance at a time; a second claimant is RECEIPT_RESERVED → person.
