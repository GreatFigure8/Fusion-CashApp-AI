# s38-reverse-automated-application: Reverse an automated application in Fusion

- Issue: #38
- Wave: 5 (money path; owns `cashapp/services/reversal.py`, `cashapp/api/routers/reversal.py`)
- breaking: false

## Story

As an AR lead, I want to undo a wrong automated application from the workbench with a full audit trail, so that a mistake is fixed in minutes instead of by hand in Fusion with no record.

## Context

The previous build had no unapply flow (reference doc §4 defects). Never reverses an application this system didn't make: only `APPLICATION_LEDGER` rows with STATUS=APPLIED and a `FUSION_APPLICATION_ID`. The unapply call must be confirmed on a non-production pod (s05 marks it UNVERIFIED); built against the fake until then.

## Acceptance criteria

1. [integration] Confirmation: a `-m live` probe confirms the unapply operation on `StandardReceiptService` (operation name, keys, reversal GL date rule) on the dev pod and updates `CONTRACTS.md`; until then `unapply_receipt` stays UNVERIFIED and the endpoint returns 503 `{code:"unverified_contract"}` unless setting `fusion.unapply_verified=true`.
2. [unit] `ReversalService.reverse(uow, *, item_id, ledger_id, principal, reason, confirm_receipt_number) -> ReversalResult`: requires `apply:reverse`, a non-empty reason, the caller holding the item's live lock, `confirm_receipt_number` equal to the ledger row's receipt number, and the ledger row belonging to the item with STATUS=APPLIED; otherwise a typed refusal (403/409/422).
3. [unit] It re-reads Fusion's applications for the receipt and refuses if the application id is no longer present or differs in amount (someone changed it in Fusion) with `REVERSAL_FAILED` detail "changed outside CashApp".
4. [integration] On success, in one transaction: ledger row → REVERSED (by, at, reason), `LINE_RESULT` → `allocation-reversed`, `PAYMENT_STATUS` re-derived via `roll_up`, reservation released (`ReservationRepository.release`), HUMAN_ACTION + FUSION_WRITE history rows with who/why, and the item set to STAGE=MATCH_RECEIPT, STATE=ESCALATED, LAST_ERROR_CODE=null with summary "Application reversed by <name>: <reason>" — re-matchable by the person's requeue (s18) while they still hold the lock. Fusion failure → `REVERSAL_FAILED`, nothing changed locally.
5. [api] `POST /items/{id}/applications/{ledger_id}/reverse` body `{reason, confirm_receipt_number}` → 200 `{ledger_id, status: "REVERSED", item_state}`; errors in the single error shape (`forbidden`, `lock_not_held`, `not_system_application`, `confirmation_mismatch`, `changed_outside_cashapp`, `unverified_contract`).
6. [unit] A test asserts a ledger row with STATUS other than APPLIED, or an application id not present in the ledger, can never be reversed.

## Out of scope

The workbench button and dialog (s20); partial reversal of an application amount.

## Deps

- s15-line-matching-apply — `APPLICATION_LEDGER`, `LINE_RESULT`, `ApplicationLedgerRepository`, `LineResultRepository`. plannable.
- s13-receipt-matching-scorer — `ReservationRepository.release(item_id, reason)`. plannable.
- s05-fusion-client — `unapply_receipt(UnapplyRequest)`, `list_receipt_applications`. unplannable for the live contract (needs pod); plannable against the fake.
- s40-item-locking — `LockService.assert_held_by`. plannable.
- s04-sign-in-authorization — `require_permission(APPLY_REVERSE)`. plannable.
- s02-data-layer-foundation — `roll_up`, `LineStatus.ALLOCATION_REVERSED`. plannable.

## Assumptions

- After reversal the item waits for the person (ESCALATED) rather than re-matching automatically, so automation can't re-apply the same mistake.
