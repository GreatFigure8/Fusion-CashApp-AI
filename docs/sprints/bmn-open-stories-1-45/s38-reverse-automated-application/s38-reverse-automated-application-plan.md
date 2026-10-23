# Plan: s38-reverse-automated-application

Issue #38. Wave 5 (money path). Paths: `cashapp/` = `api/src/cashapp/`. API only; the workbench button and dialog are s20's.

## Standards followed

- **CLAUDE.md**: layered (router → service → repositories; no SQLAlchemy outside `cashapp/data/`); services take the `Principal` as a plain argument and only flush, the router commits; one error shape (s01 `ApiError`); every human action and Fusion write recorded on the item's history with who and why; money is `Decimal` with `money_eq`; all Fusion traffic through `FusionClient` behind s05's `WriteGuard`; "never guess an endpoint": the unapply SOAP contract stays UNVERIFIED and gated until a live probe confirms it.
- **research.md a3/a6**: Fusion write rails (`fusion.write_enabled`, prod-pod refusal) apply unchanged; the fake is never presented as a confirmed contract.
- **python-web-app:building-python-web-apps**: logic in `services/`, route parses and calls; `Annotated` dependency aliases; POST for the mutation; router auto-discovered (no `main.py` edit).
- **python-web-app:wiring-application-config**: one new deploy-time key `fusion.unapply_verified` on s27's `FusionSettings` with a typed default `False`, mirrored in `.env.example` (s27's coverage test enforces it). It's a deploy setting, not a runtime-config key, so no admin can flip it in the UI to bypass an unconfirmed contract.
- Pyright strict, ruff. Tests written and run only at step 5.

## Files to touch

New (owned by this story):

| Path | Content |
|---|---|
| `cashapp/services/reversal.py` | `ReversalService`, `ReversalResult`, the `ReversalError` hierarchy, `reversal_gl_date` |
| `cashapp/services/payment_status.py` | `derive_payment_status(uow, item)`: the one place that builds `HeaderResult` from the ledger and `LINE_RESULT` and calls s02's `roll_up` (see Assumptions 3) |
| `cashapp/api/schemas/reversal.py` | `ReverseIn`, `ReverseOut`, `reversal_error_to_api` |
| `cashapp/api/routers/reversal.py` | `router`: `POST /items/{item_id}/applications/{ledger_id}/reverse` |
| `cashapp/api/fusion_deps.py` | `get_fusion_client()` (cached `build_fusion_client(get_settings())`), `FusionClientDep`; shared, so any later router reuses it |
| `api/tests/unit/services/test_reversal_service.py` | AC2, AC3, AC6 (step 5) |
| `api/tests/unit/services/test_payment_status.py` | AC4 roll-up helper (step 5) |
| `api/tests/integration/test_reversal_flow.py` | AC4 (step 5) |
| `api/tests/api/test_reversal_api.py` | AC1 gate, AC5 (step 5) |
| `api/tests/live/fusion/test_unapply_live.py` | AC1 live probe (step 5, `-m live`) |

Edited (cross-story, append-only):

| Path | Change |
|---|---|
| `cashapp/settings.py` (s27) | `FusionSettings.unapply_verified: bool = False` |
| `api/.env.example` (s27) | `CASHAPP_FUSION__UNAPPLY_VERIFIED=false` |
| `cashapp/integrations/fusion/CONTRACTS.md` (s05) | unapply rows (operation name, keys, reversal GL-date rule) become `CONFIRMED <date> <pod>` when the probe passes; until then they stay `UNVERIFIED` with "s38" as owner |
| `cashapp/integrations/fusion/soap.py` (s05) | **only if** the live probe shows the operation name, element names or GL-date rule differ from s05's `build_unapply_envelope`/`parse_unapply_response`; signature of `unapply_receipt` unchanged |

No edit to `main.py`, s15's repositories, s13's reservation repository or s40's lock module.

## Design

### Service flow (`ReversalService.reverse`)

All in the caller's UoW. Checks run in this order, and every refusal happens before any Fusion write; `fake.calls` never shows `unapply_receipt` for a refused request.

1. `principal.can(Permission.APPLY_REVERSE)` and not `principal.is_system` → else `ReversalForbidden` (403 `forbidden`, details `[{"permission": "apply:reverse"}]`). System principals never reverse (s04's `SYSTEM_PRINCIPAL` lacks the permission anyway).
2. `reason.strip()` non-empty, at most 1000 chars → else `ReasonRequired` (422 `reason_required`).
3. `self._unapply_verified` → else `UnverifiedContract` (503 `unverified_contract`). After 403/422 so unauthorized callers learn nothing about rollout.
4. `item = await uow.work_items.get_for_update(item_id, skip_locked=False)` (row lock held until commit; serializes concurrent reversals of the same item) → `None` → `ItemNotFound` (404 `item_not_found`).
5. `LockService.assert_held_by(item, principal, clock.now())` → s40's `LockNotHeld` re-raised as `ReversalLockNotHeld` (409 `lock_not_held`).
6. `row = await ledger_repo.get(ledger_id)`. Refuse with `NotSystemApplication` (409 `not_system_application`) unless **all** hold: row exists, `row.work_item_id == item_id`, `row.status == LedgerStatus.APPLIED`, `row.fusion_application_id is not None`. This is the only source of the application id: the endpoint takes no application id, so an application not in the ledger can never be reversed (AC6).
7. `receipt = await fusion.get_receipt(row.receipt_id)`; `confirm_receipt_number.strip() == receipt.receipt_number.strip()` (exact, case-sensitive) → else `ConfirmationMismatch` (422 `confirmation_mismatch`). The ledger has no receipt-number column; Fusion is the authority (Assumption 2).
8. `apps = await fusion.list_receipt_applications(row.receipt_id)`; find `a.application_id == row.fusion_application_id`. Refuse with `ChangedOutsideCashApp` (409 `changed_outside_cashapp`, error code `REVERSAL_FAILED`, message "changed outside CashApp", details `[{"application_id", "ledger_amount", "fusion_amount" | null, "fusion_status" | null}]`) when it's absent, its status is already reversed (`status != "APP"`, value UNVERIFIED, read from one constant `ACTIVE_APPLICATION_STATUS` in `reversal.py`), its `customer_trx_id` differs, or `not money_eq(a.amount_applied, row.amount)`.
9. `request = UnapplyRequest(receipt_id=row.receipt_id, application_id=row.fusion_application_id, reversal_gl_date=reversal_gl_date(original_accounting_date, clock.now().date()), reason=reason)` where `original_accounting_date` = `row.request["accounting_date"]` (s15 stores the `ApplyRequest` as JSON), else `a.apply_date`. `result = await fusion.unapply_receipt(request)`.
   - `FusionError` (transport, write guard) or `result.ok is False` → `ReversalFusionFailed` (502 `reversal_failed`, error code `REVERSAL_FAILED`, details `[{"error_code", "fusion_code", "message"}]`; `FUSION_WRITE_DISABLED` → 503 `reversal_failed` with the same details). Nothing has been written, so the router's UoW rolls back to nothing.
10. Success writes (flush only, router commits once):
    - `ledger_repo.mark(row, LedgerStatus.REVERSED, reversed_at=now, reversed_by=principal.subject, reversal_reason=reason)`.
    - `line_repo.upsert(item_id, row.line_no, line_status=LineStatus.ALLOCATION_REVERSED, reason=f"Reversed by {principal.display_name}: {reason}")`. `APPLIED_AMOUNT` is kept for audit; the roll-up ignores it because the status is no longer applied.
    - `status = await derive_payment_status(uow, item)`.
    - `await reservation_repo.release(item_id, f"application {row.id} reversed")`.
    - `record_history` HUMAN_ACTION: `**actor_fields(principal)`, from/to stage and state, `reasoning=reason`, payload `{event: "reverse_application", ledger_id, application_id, receipt_id, receipt_number, customer_trx_id, amount, line_no, payment_status_before, payment_status_after}`.
    - `record_history` FUSION_WRITE: same actor, payload `{operation: "unapply_receipt", request (dataclass as JSON, Decimal as str), messages: [code, severity, text]}`.
    - `uow.work_items.update(item, stage=Stage.MATCH_RECEIPT, state=ItemState.ESCALATED, last_error_code=None, last_error_detail=None, escalation_summary=f"Application reversed by {principal.display_name}: {reason}", payment_status=status)`. Lock columns untouched (the person keeps the lock; s40's layering test holds). No outbox event: nothing automatic runs until the person requeues through s18 (`target_stage` defaults to the stage it's in, MATCH_RECEIPT).
11. Returns `ReversalResult`.

`reversal_gl_date(original: date, today: date) -> date = max(original, today)` (UNVERIFIED rule; the probe confirms whether Fusion requires the reversal GL date on or after the application's GL date and in an open period).

### `derive_payment_status(uow, item)`

`HeaderResult(customer_found=item.customer_account_number is not None, payment_date_present=item.payment_date is not None, receipt_found=any ledger row for the item, applied_total=sum(row.amount for APPLIED rows) (signed), total_due=item.payment_amount or 0, receipt_closed=False, dry_run=False)`; lines = `[r.line_status for r in line_repo.for_item(item.id)]`; returns `roll_up(header, lines)`. When every line is reversed, s02's `roll_up` returns `PAYMENT_APPLY_FAILED_SYSTEM` (s02 plan line 464).

### Router

```python
@router.post("/items/{item_id}/applications/{ledger_id}/reverse", response_model=ReverseOut,
             responses=ERROR_RESPONSES, operation_id="reverseApplication")
async def reverse_application(item_id: int, ledger_id: int, body: ReverseIn,
        principal: Annotated[Principal, Depends(require_permission(Permission.APPLY_REVERSE))],
        uow_factory: UowFactoryDep, fusion: FusionClientDep) -> ReverseOut
```

Builds `ReversalService(fusion, unapply_verified=get_settings().fusion.unapply_verified)`, opens `async with uow_factory() as uow`, calls `reverse`, `await uow.commit()`, maps `ReversalError` with `reversal_error_to_api`. `require_permission` gives the 403 before the body is used; the service re-checks (defence in depth, AC2).

## Interfaces provided (pinned)

```python
# cashapp/services/reversal.py
ACTIVE_APPLICATION_STATUS: Final = "APP"          # UNVERIFIED, s05 FusionApplication.status

@dataclass(frozen=True, slots=True)
class ReversalResult:
    item_id: int; ledger_id: int; application_id: int; receipt_id: int; receipt_number: str
    amount: Decimal; reversal_gl_date: date
    item_stage: Stage; item_state: ItemState; payment_status: PaymentStatus

class ReversalError(Exception):
    status_code: ClassVar[int]; code: ClassVar[str]
    error_code: ClassVar[ErrorCode | None] = None
    def __init__(self, message: str, *, details: Sequence[Mapping[str, Any]] = ()) -> None
    message: str; details: list[dict[str, Any]]
class ReversalForbidden(ReversalError):      # 403 "forbidden"
class ReasonRequired(ReversalError):         # 422 "reason_required"
class UnverifiedContract(ReversalError):     # 503 "unverified_contract"
class ItemNotFound(ReversalError):           # 404 "item_not_found"
class ReversalLockNotHeld(ReversalError):    # 409 "lock_not_held"
class NotSystemApplication(ReversalError):   # 409 "not_system_application"
class ConfirmationMismatch(ReversalError):   # 422 "confirmation_mismatch"
class ChangedOutsideCashApp(ReversalError):  # 409 "changed_outside_cashapp", error_code REVERSAL_FAILED
class ReversalFusionFailed(ReversalError):   # 502 (503 when FUSION_WRITE_DISABLED) "reversal_failed", error_code REVERSAL_FAILED

def reversal_gl_date(original_accounting_date: date, today: date) -> date

class ReversalService:
    def __init__(self, fusion: FusionClient, *, unapply_verified: bool, clock: Clock | None = None) -> None
    async def reverse(self, uow: UnitOfWork, *, item_id: int, ledger_id: int, principal: Principal,
                      reason: str, confirm_receipt_number: str) -> ReversalResult   # flushes only; never commits

# cashapp/services/payment_status.py
async def derive_payment_status(uow: UnitOfWork, item: WorkItem) -> PaymentStatus

# cashapp/api/fusion_deps.py
def get_fusion_client() -> FusionClient             # lru_cache; tests use app.dependency_overrides
FusionClientDep = Annotated[FusionClient, Depends(get_fusion_client)]

# cashapp/api/schemas/reversal.py
class ReverseIn(BaseModel):
    reason: Annotated[str, StringConstraints(max_length=1000)]               # blank reaches the service -> 422 reason_required
    confirm_receipt_number: Annotated[str, StringConstraints(max_length=100)]
class ReverseOut(BaseModel):
    ledger_id: int; status: Literal["REVERSED"]; item_state: ItemState
    item_stage: Stage; payment_status: PaymentStatus | None
def reversal_error_to_api(exc: ReversalError) -> ApiError
```

### HTTP contract (s20 and s31 consume it)

`POST /items/{item_id}/applications/{ledger_id}/reverse`, permission `apply:reverse`, body `{reason, confirm_receipt_number}`.

| Status | `code` | When |
|---|---|---|
| 200 | — | `{ledger_id, status: "REVERSED", item_state: "ESCALATED", item_stage: "MATCH_RECEIPT", payment_status}` |
| 403 | `forbidden` | missing `apply:reverse` |
| 404 | `item_not_found` | no such item |
| 409 | `lock_not_held` | caller holds no live lock on the item |
| 409 | `not_system_application` | ledger row missing, of another item, not APPLIED, or no Fusion application id |
| 409 | `changed_outside_cashapp` | Fusion's application missing, reversed, or of a different amount/transaction |
| 422 | `reason_required`, `confirmation_mismatch` | blank reason; typed receipt number differs |
| 502/503 | `reversal_failed` | Fusion fault or transport error (503 when writes are disabled) |
| 503 | `unverified_contract` | `fusion.unapply_verified` is false |

All errors use s01's `{"error": {code, message, request_id, details}}`.

## Migrations

None. `APPLICATION_LEDGER.REVERSED_AT/REVERSED_BY/REVERSAL_REASON`, `LINE_RESULT.LINE_STATUS` (VARCHAR2(40), no CHECK) and `RECEIPT_RESERVATION` come from s15's and s13's revisions; `WORK_ITEM` columns from s02's `0001_base`. Expected Alembic head: unchanged (whatever head s15/s13 leave).

## Test plan

Written and run at step 5 only. Unit/integration on aiosqlite (s02 `uow`/`uow_factory`), `FrozenClock`, s04 `make_principal`, s40 `lock_item`, s05 `FakeFusionClient` seeded with a receipt, an invoice and one application created through the fake's own `apply_receipt` (so its id comes from the fake), plus a matching APPLIED ledger row and `LINE_RESULT` row created through s15's repositories.

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/live/fusion/test_unapply_live.py::test_live_unapply_round_trip` (`@pytest.mark.live`; skipped unless the live pod has `is_production=False`, `fusion.write_enabled`, `CASHAPP_FUSION_LIVE_WRITES=1`; uses s23-tagged data: apply, `list_receipt_applications`, `unapply_receipt` with `reversal_gl_date`, re-read shows the application reversed and balances restored; on pass `record_confirmation("unapply_receipt", [operation, ReceiptId/ApplicationId keys, reversal GL date rule])` updates `CONTRACTS.md`) |
| 1 | `api/tests/live/fusion/test_unapply_live.py::test_live_unapply_gl_date_before_application_rejected` (probes the GL-date rule; result recorded either way) |
| 1 | `api/tests/unit/services/test_reversal_service.py::test_unverified_contract_refuses_before_any_fusion_call` |
| 1 | `api/tests/api/test_reversal_api.py::test_reverse_503_unverified_contract_unless_setting_true` (settings false → 503 `unverified_contract`; true → 200) |
| 2 | `…test_reversal_service.py::test_requires_apply_reverse_permission` (parametrized OPERATOR, VIEWER, `SYSTEM_PRINCIPAL` → `ReversalForbidden`) |
| 2 | `…::test_blank_or_whitespace_reason_refused` (`ReasonRequired`, 422) |
| 2 | `…::test_lock_not_held_refused` (parametrized no lock, other owner, expired lock → `ReversalLockNotHeld`, 409) |
| 2 | `…::test_confirmation_mismatch_refused` (wrong number and different case → 422; surrounding whitespace accepted) |
| 2 | `…::test_unknown_item_refused_404` |
| 2 | `…::test_ledger_row_of_other_item_refused` (`NotSystemApplication`) |
| 2 | `…::test_refusals_make_no_fusion_write_and_no_db_change` (every refusal above: no `unapply_receipt` in `fake.calls`, ledger/item/history unchanged) |
| 3 | `…::test_application_absent_in_fusion_refused_changed_outside` (`ChangedOutsideCashApp`, error_code `REVERSAL_FAILED`, message contains "changed outside CashApp") |
| 3 | `…::test_application_amount_differs_refused_changed_outside` (amount differs by 0.01; differing by 0.004 passes `money_eq`) |
| 3 | `…::test_application_already_reversed_in_fusion_refused` |
| 4 | `api/tests/integration/test_reversal_flow.py::test_reverse_success_writes_everything_in_one_transaction` (ledger REVERSED with at/by/reason; `LINE_RESULT` `allocation-reversed`; `PAYMENT_STATUS` equals `roll_up` of the remaining lines; reservation released; one HUMAN_ACTION and one FUSION_WRITE row with actor USER/subject/name and reason; item MATCH_RECEIPT/ESCALATED, `LAST_ERROR_CODE` null, summary "Application reversed by <name>: <reason>", lock still held by the caller; a second UoW sees nothing before commit and everything after) |
| 4 | `…::test_reverse_restores_fusion_balance_and_uses_gl_date_rule` (fake application REVERSED, invoice balance and receipt unapplied restored; `reversal_gl_date == max(original accounting date, today)`) |
| 4 | `…::test_fusion_fault_changes_nothing_locally` (parametrized `fail_next("unapply_receipt", FusionFault(...))` and `FusionError(FUSION_TRANSIENT)` and write guard disabled → `ReversalFusionFailed` with `REVERSAL_FAILED`; DB identical after rollback) |
| 4 | `…::test_partial_reversal_keeps_other_lines_applied` (two applied lines, reverse one → status derived from one applied + one reversed) |
| 4 | `…::test_requeue_after_reversal_is_accepted_at_match_receipt` (s18 `POST /items/{id}/requeue` by the lock holder → PENDING at MATCH_RECEIPT; skipped with a reason if s18 isn't merged) |
| 4 | `api/tests/unit/services/test_payment_status.py::test_derive_payment_status_matches_roll_up` (all applied, one reversed, all reversed → `PAYMENT_APPLY_FAILED_SYSTEM`) |
| 5 | `api/tests/api/test_reversal_api.py::test_reverse_200_response_shape` |
| 5 | `…::test_reverse_error_codes_use_single_error_shape` (parametrized `forbidden`, `lock_not_held`, `not_system_application`, `confirmation_mismatch`, `changed_outside_cashapp`, `unverified_contract` → status, `error.code`, `request_id`) |
| 5 | `…::test_reverse_requires_apply_reverse_403_for_operator` |
| 5 | `…::test_reverse_route_in_openapi` (operation `reverseApplication`, `ReverseIn`/`ReverseOut` schemas) |
| 6 | `…test_reversal_service.py::test_non_applied_ledger_status_never_reversible` (parametrized PLANNED, FAILED, REVERSED, DRY_RUN → `NotSystemApplication`, no Fusion write) |
| 6 | `…::test_applied_row_without_fusion_application_id_never_reversible` |
| 6 | `…::test_application_not_in_ledger_never_reversible` (a Fusion application created outside CashApp on the same receipt; no ledger id reaches it: unknown `ledger_id` → refused; the unapply request's `application_id` always equals the ledger row's id) |
| 6 | `…::test_second_reversal_of_same_row_refused` |

## Risks

1. **Unapply contract unknown.** s05 has the SOAP operation, keys and GL-date rule UNVERIFIED. The endpoint returns 503 until `CASHAPP_FUSION__UNAPPLY_VERIFIED=true`, which is set only after the live probe passes and `CONTRACTS.md` shows CONFIRMED. If the probe shows a different operation (for example a receipt-level `unapplyReceipt` keyed on `ReceivableApplicationId`), the coder changes s05's envelope/parse only, never `unapply_receipt`'s signature.
2. **Fusion succeeds, local commit fails.** Fusion is reversed but the ledger still says APPLIED. A retry then refuses with `changed_outside_cashapp` and `fusion_status` in details, so a person sees the exact state; the API logs the event at ERROR with ids only (no payload). The window is small because the item row is locked and nothing else runs between the call and the commit.
3. **Row lock held across two Fusion reads and one write** (seconds). Acceptable for a human action on one item; it blocks only automation on that item, which the person's lock already blocks.
4. **Write-back note is stale.** s17's receipt note still says what was applied until the item is re-applied and written back. Out of scope; the history shows the reversal.
5. **Application status values** (`APP` vs reversed) are UNVERIFIED; one constant to change.

## Assumptions

1. `fusion.unapply_verified` is a deploy-time setting on s27's `FusionSettings`, not a runtime-config key: an admin must not be able to bypass an unconfirmed Fusion contract from the configuration screen.
2. The ledger has no receipt number, so the confirmation compares with Fusion's `get_receipt(receipt_id).receipt_number`. The comparison strips whitespace and is case-sensitive.
3. s15 owns the ledger and line tables but hasn't pinned a header-builder. `derive_payment_status` is pinned here as the single place that turns ledger + `LINE_RESULT` rows into a `HeaderResult` for `roll_up`; s15's `ApplyRunner` should call it. If s15 merges an equivalent first, the merger deletes this file and re-points the import (one copy only).
4. Names coded against s15's story text: `LedgerStatus` enum (PLANNED/APPLIED/FAILED/REVERSED/DRY_RUN), `ApplicationLedgerRepository.mark/for_item`, `LineResultRepository.upsert/for_item`, ledger attribute names (`work_item_id`, `line_no`, `receipt_id`, `customer_trx_id`, `amount`, `status`, `fusion_application_id`, `request`). s13: `ReservationRepository.release(item_id, reason)`; if it only releases ACTIVE rows (the item's reservation is CONSUMED after apply), the outcome is still correct because no ACTIVE holder exists. The merger reconciles names if code differs.
5. After reversal the item stays ESCALATED and locked by the reverser; no `StageEvent` is emitted and s18's `escalate()` is not used (it would set `LAST_ERROR_CODE` and notify, which the story rules out).
6. Fusion failure maps to 502 `reversal_failed` (503 when writes are disabled); the story names the error code `REVERSAL_FAILED` but not the HTTP status.
7. `cashapp/api/fusion_deps.py` is new and shared: no earlier plan pins a request-scoped `FusionClient` dependency for routers. The cached client lives for the API process; closing it in the app lifespan is left to whoever next edits `main.py`.
