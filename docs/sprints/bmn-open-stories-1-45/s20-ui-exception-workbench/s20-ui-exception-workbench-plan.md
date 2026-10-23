# Plan: s20-ui-exception-workbench

Issue #20. Wave 5 (index 4), merged after s19 and s38. Paths: `cashapp/` = `api/src/cashapp/`. UI follows design.md §5, with §2 for the tokens and §10 for responsive behaviour.

## Standards followed

- **CLAUDE.md**
  - *UI / Exception workbench*: exceptions only, auto-applied items hidden by default; dequeue, see why, see the fixes tried, correct, requeue; show the invoice-to-customer link, location, original and remaining amounts, and credit memo history.
  - *Self-healing*: a human requeue reuses s18's endpoint. This story adds **no manual code path**. Every mutation calls an existing endpoint (s40 lock, s18 requeue, s38 reverse, s07 override).
  - *Authorization*: the UI hides, the API enforces. Both new endpoints use `require_permission(Permission.ITEMS_READ)`.
  - *Money*: `Decimal` in Python and `MoneyStr` (string) on the wire. Display goes through s19's `money`.
  - *DRY* (non-negotiable 7): the workbench reuses s19's `data-table`, `status-badge`, `money`, `empty-state`, `error-alert` and `history-timeline`, s40's `LockInfoOut` and `lock_error_to_api`, s02's `ErrorCode` and `ItemState`, and s05's `FusionClient`. It owns `lock-banner` once.
- **Layering**
  - The router imports no SQLAlchemy.
  - Services take plain arguments (`Principal`, filters dataclass, `now`) and never touch `Request`.
  - Every query sits in `ExceptionsRepository`, a new owned file. This is a deviation from the story's owned list: a repository is required by CLAUDE.md, so no query goes in the service.
  - Read-only endpoints. No transaction is committed.
- **python-web-app**: `Annotated` deps; services own the logic; Fusion is behind an interface (`read_only(FusionClient)`); GET never mutates.
- **Next.js rules (bmn `nextjs.md`)**
  - TS: TS-13, TS-16, TS-17 (`PageProps<'/exceptions'>`; await and Zod-parse `searchParams`), TS-19, TS-20, TS-28, TS-30 (sheet-transition discriminated union), TS-31, TS-32.
  - RT: RT-6 (`_lib` private folder), RT-8 (`loading.tsx`), RT-26, RT-27 (filter bar uses `useSearchParams` inside `<Suspense>`), RT-28 (the server reads `searchParams` from the page prop).
  - RC: RC-5, RC-7, RC-8 (the server-rendered sheet body is passed as `children` into the client `Sheet`), RC-38 (Suspense around the fusion-context cards).
  - DF: DF-4 (list, item, fusion-context and `/me` are fetched in parallel), DF-11, DF-12, DF-13, DF-14, DF-15, DF-22.
  - SEC: SEC-16, SEC-21, SEC-22, SEC-23.
  - SSE: SSE-25, SSE-26 (reuse s19's single `/flow/stream` subscription; see Assumptions).
  - TEST: TEST-1, TEST-2, TEST-10, TEST-14, TEST-17, TEST-18, TEST-25.
- **nextjs-fullstack-standards**: strict TS; Zod at every boundary (search params, action inputs, SSE payloads); `Result` errors from s31's `apiAction`; shadcn primitives only through the CLI; named exports; `kebab-case.ts` files.

## Files to touch

### API (all new, owned)

| Path | Content |
|---|---|
| `cashapp/api/routers/exceptions.py` | `router`: `GET /exceptions` and `GET /items/{item_id}/fusion-context`. Also `get_exceptions_service`, `get_fusion_context_service` and `get_fusion_reader` dependencies, which tests override. |
| `cashapp/api/schemas/exceptions.py` | `ExceptionSort`, `ExceptionListQuery`, `ExceptionRowOut`, `ExceptionListOut`, and the `FusionContextOut` family (see Interfaces) |
| `cashapp/services/exceptions_query.py` | `ExceptionFilters`, `ExceptionRow`, `ExceptionsQueryService`, `FAILED_LINE_STATUSES`, `AWAITING_EXCEPTION_AFTER` |
| `cashapp/services/fusion_context.py` | `FusionContext` dataclasses, `FusionContextService`, `FusionContextCache` (in-process TTL, 60 s) |
| `cashapp/data/repositories/exceptions.py` | `ExceptionsRepository(BaseRepository[WorkItem])`: `search`, `autofix_counts`, `autofix_attempts`, `latest_match_candidates` |
| `api/tests/support/exceptions.py` | `seed_exception_item(uow, **kw)`, `seed_autofix_attempt(...)`, `seed_line_result(...)`, `seed_match_candidates(...)`, `fusion_context_fake()` |
| `web/lib/api/openapi.json`, `web/lib/api/schema.d.ts` | regenerated with `npm run api:sync` (s31), never edited by hand |

### Web (owned)

| Path | Content |
|---|---|
| `web/app/(shell)/exceptions/page.tsx` | Async Server Component. It awaits and Zod-parses `searchParams`, starts `getExceptions`, `getMe` and, when `item` is set, `getItemDetail`, `getItemHistory` and `getFusionContext` in parallel. It renders the filter bar, the table and the sheet. |
| `web/app/(shell)/exceptions/loading.tsx` | Skeleton for the filter bar and a 10-row table |
| `web/app/(shell)/exceptions/error.tsx` | `"use client"`. s19's `error-alert` with a Retry button that calls `reset` (TEST-20, TEST-21). |
| `web/app/(shell)/exceptions/_lib/search-params.ts` | `exceptionFiltersSchema`, `ExceptionFilters`, `parseExceptionFilters`, `filtersToSearchParams`, `isFiltered`, `DEFAULT_FILTERS` (pure, client-safe) |
| `web/app/(shell)/exceptions/_lib/queries.ts` | `import "server-only"`: `getExceptions`, `getItemDetail`, `getItemHistory`, `getFusionContext` and `getMe`, each wrapping s31 `api()` in React `cache` |
| `web/app/(shell)/exceptions/_lib/actions.ts` | `"use server"`: `dequeueAction`, `renewLockAction`, `releaseLockAction`, `requeueAction`, `reverseAction` and `overrideClassificationAction`. Each is `apiAction(zodSchema, fn)` and returns `Result<…, ApiError>`. |
| `web/components/common/lock-banner.tsx` | `LockBanner` (see Interfaces) |
| `web/components/exceptions/exceptions-filter-bar.tsx` | `"use client"`: search (debounced 300 ms), amount min/max, date range `Popover`+`Calendar`, error-code multi-select (`Popover`+`Command` with checkmarks), stage `Select`, "Locked by me" `Switch`, "Show auto-applied" `Switch`, "Show archived" `Switch` (only with `classification:override`), and Clear filters. It writes the URL through `router.replace`. |
| `web/components/exceptions/exception-columns.tsx` | TanStack column defs for s19's `DataTable`: WI id · Payer · Amount (`money`) · Payment date · Error code (`Badge`) · Auto-fixes "2 / 3" · Age · Lock (violet lock + owner) · `⋯` menu (Open, Dequeue) |
| `web/components/exceptions/exceptions-table.tsx` | `"use client"`. The `DataTable` wrapper. A row click sets `?item=WI-…` while keeping the filters. It shows the empty and filtered-empty states. |
| `web/components/exceptions/exception-sheet.tsx` | `"use client"`. A shadcn `Sheet` (`side="right"`, `w-full lg:w-[60vw] lg:max-w-none`), opened from the `item` param. Closing removes `item` from the URL. The header shows the WI id, `StatusBadge` and lock controls. The body is `children` (RC-8). |
| `web/components/exceptions/why-stuck.tsx` | `escalation_summary`, the error-code badge and `last_error_detail.message` |
| `web/components/exceptions/autofix-list.tsx` | An ordered list with outcome icons by decision (`retry`, `reroute`, `park`, `escalate`, `noop`), "attempt n / limit", and the reasoning |
| `web/components/exceptions/fusion-context-cards.tsx` | `CustomerCard`, `CandidateReceiptsTable`, `InvoicesTable` (number, bill-to customer, original, remaining, currency, status) and `CreditMemoHistory`, plus a warnings `Alert` for any Fusion section that failed |
| `web/components/exceptions/applications-table.tsx` | Applied ledger rows, with a per-row "Reverse…" action when `apply:reverse` is held |
| `web/components/exceptions/reverse-dialog.tsx` | `"use client"` `AlertDialog`: a required reason and a "type the receipt number" input. Confirm stays disabled until `isReverseConfirmValid`. |
| `web/components/exceptions/lock-controls.tsx` | `"use client"`: Dequeue, Requeue, Release lock and the `LockBanner`. Maps action errors to toasts (`sonner`) and owns `useLockLease`. |
| `web/components/exceptions/use-lock-lease.ts` | `"use client"` hook: renews every `lease/3` while the sheet is open and I hold the lock; detects expiry by timer |
| `web/components/exceptions/use-item-live.ts` | `"use client"` hook: subscribes to `item_changed` for the open item, folds each event through `nextSheetState`, and calls `router.refresh()` |
| `web/components/exceptions/sheet-state.ts` | Pure: `SheetLockView`, `SheetNotice`, `SheetState`, `initialSheetState`, `nextSheetState`, `lockExpiredState` |
| `web/components/exceptions/lock-messages.ts` | Pure: `lockErrorToast(err: ApiError): string \| null`, `formatLockTime(iso)` |
| `web/components/exceptions/edit-model.ts` | Pure: `editFormSchema` (Zod), `EditFormValues`, `toFormValues(final)`, `applyEdits(final, values)`, `diffSummary(before, after, choices)`, `buildRequeueBody(...)` |
| `web/components/exceptions/edit-form.tsx` | `"use client"` react-hook-form + `zodResolver(editFormSchema)`. Header fields plus an editable lines grid (add and remove line). Controls are disabled when `editable=false`. |
| `web/components/exceptions/receipt-picker.tsx` | `RadioGroup` over `candidate_receipts`. Rendered only when `error_code === "RECEIPT_AMBIGUOUS"`. |
| `web/components/exceptions/customer-picker.tsx` | `Popover`+`Command` over the anchor, related and invoice bill-to numbers, plus a free-text account number. Rendered only when `error_code` starts with `CUSTOMER_`. |
| `web/components/exceptions/requeue-dialog.tsx` | `"use client"` `AlertDialog`: shows `diffSummary`, a required note (prefilled with the summary), and confirms `requeueAction`. On error it shows a destructive `Alert` in the sheet and the form keeps its values. |
| `web/components/exceptions/classification-override.tsx` | "This is a remittance" button plus a reason dialog. Shown for `state === "ARCHIVED"` with `classification:override`. |
| `web/components/exceptions/empty-states.tsx` | `NoExceptions` (link to `/flow`) and `NoMatches` (Clear filters link), both on s19's `EmptyState` |
| `web/components/ui/radio-group.tsx` | `npx shadcn@latest add radio-group` (CLI output only; see Assumptions) |
| `web/e2e/support/api-stub.ts` | Only if s19 doesn't ship one (see Assumptions): a stub API server with scenario control |
| `web/e2e/exceptions/*.spec.ts`, `web/tests/unit/exceptions/*.test.ts(x)`, `api/tests/**` | Tests, written in step 5 |

### Not touched

`main.py`, `cashapp/api/deps.py`, s19's `components/common/*` (other than adding `lock-banner.tsx`), `routers/items.py`, `routers/locks.py`, `routers/requeue.py`, `routers/reversal.py`, `routers/classification.py`, every model, lockfiles (except the radio-group note), and any Alembic revision.

## Design

### `GET /exceptions`

- **Query** (`ExceptionListQuery`, Pydantic, `extra="forbid"`):
  - `q: str | None` (≤ 200 chars)
  - `amount_min`, `amount_max: MoneyStr | None`
  - `date_from`, `date_to: date | None`
  - `error_codes: list[ErrorCode] = []`, repeated key `error_codes=A&error_codes=B`
  - `stage: Stage | None`
  - `locked_by_me: bool = False`
  - `include_auto_applied: bool = False`
  - `include_archived: bool = False`
  - `page: int ≥ 1 = 1`
  - `page_size: int 1..200 = 50`
  - `sort: ExceptionSort = "-age"`

  `amount_min > amount_max` or `date_from > date_to` returns 422 `validation_error`.
- **Base set** (OR of the following):
  1. `state == ESCALATED`.
  2. `state == AWAITING_RECEIPT AND awaiting_since <= now - 1 day` (`AWAITING_EXCEPTION_AFTER = timedelta(days=1)`).
  3. `EXISTS LINE_RESULT` with `line_status IN FAILED_LINE_STATUSES` and `state NOT IN TERMINAL_STATES` or `state == DONE`. In practice, any item with a failed line.
     - `FAILED_LINE_STATUSES` is derived, not listed: `frozenset(LineStatus) - APPLIED_LINE_STATUSES - {ALLOCATION_PREVIOUSLY_APPLIED, ALLOCATION_DRY_RUN, ALLOCATION_REVERSED}`.
  4. A live lock (`lock_owner IS NOT NULL AND lock_expires_at > now`), so a dequeued item stays visible while a person works it.
  5. When `include_auto_applied`: `state == DONE AND payment_status IN SUCCESS_STATUSES`.
  6. When `include_archived`: `state == ARCHIVED`.
- **Filters** (AND):
  - `q`:
    - `WI-<n>` or `<n>` matches `id`.
    - Otherwise case-insensitive `LIKE` on `payer_name` and `customer_account_number`.
    - Or `EXISTS LINE_RESULT.transaction_number LIKE`.
    - Or `EXISTS MATCH_CANDIDATE.receipt_number = q`.
    - The `LIKE` pattern escapes `%`, `_` and `\` with `ESCAPE '\'`.
  - Amount: `payment_amount >= amount_min - 0.005` and `<= amount_max + 0.005`, which is `money_eq`-tolerant at both ends.
  - `payment_date` falls within `[date_from, date_to]`.
  - `last_error_code IN error_codes`.
  - `stage == stage`.
  - `locked_by_me`: `lock_owner == principal.subject AND lock_expires_at > now`.
- **Sort allowlist**: `age` / `-age` (`created_at` desc means youngest first, so `-age` maps to `created_at ASC`), `amount` / `-amount`, `payment_date` / `-payment_date`, `id` / `-id`. `id` is always the tiebreak. The default is `-age`, oldest first.
- **Row fields**:
  - `age_s = int((now - created_at).total_seconds())`.
  - `autofix_tried` = the count of `AUTOFIX_ATTEMPT` history rows with `error_code == last_error_code` and `at > last requeue` (the last `HUMAN_ACTION` row whose payload `event == "requeue"`), counted in one grouped query for the page's ids.
  - `autofix_limit = (await runtime.retries()).max_attempts_for(code)`. When there's no code, it is `0` / `0`.
  - `lock = LockInfoOut.from_info(lock_info_for(item, now))`.
  - `payer_name`, `amount` (`payment_amount`), `currency`, `payment_date`, `error_code` (`last_error_code`), `stage`, `state`, `payment_status`.
- **Performance**: one paged `SELECT` with a count (`BaseRepository.list` semantics) and one grouped history count. `EXISTS` subqueries use the `LINE_RESULT(WORK_ITEM_ID, LINE_NO)` unique index and `IX_WIH_ITEM_AT`.

### `GET /items/{item_id}/fusion-context`

`FusionContextService.build(uow, item_id, *, now)`:

1. Load the item. If it's missing, raise 404 `item_not_found`.
2. **Cache**: the key is `(item_id, item.version)` and the TTL is 60 s, using `Clock`. It holds at most 512 entries (LRU by insertion). It is in-process only; every API instance has its own copy, which is acceptable for a 60 s view cache. A version bump (lock, state change) is a miss, so a person never sees context older than the item.
3. **Customer**:
   - `CustomerResolutionRepository.latest_for(item_id)` gives the anchor (falling back to `item.customer_account_number`).
   - `fusion.get_customer_account(anchor)` gives the `name`. `bill_to_site` is the first site with `purpose == "BILL_TO"`, falling back to the first site; `location` and `address` come from that site.
   - `fusion.customer_relationships([anchor])` gives `relationships: [{account_number, name, directions}]`.
   - With no anchor, `customer` is `null`.
4. **Transactions**:
   - The numbers are the union of `AdjudicationRepository.latest_for(item_id).result().final.lines[*].transaction_number` (non-empty) and `resolution.transactions[*].number`, deduped.
   - One `fusion.find_transactions(numbers)` call returns fresh balances.
   - `invoices` = `kind == INVOICE` mapped to `{number, customer_trx_id, bill_to_customer, bill_to_site, original_amount, remaining, currency, status}`.
   - Credit memos: for at most 20 `kind == CREDIT_MEMO` transactions, `list_transaction_applications(customer_trx_id)` gives `credit_memo_history: [{number, original, remaining, currency, applications: [{application_id, receipt_id, amount_applied, apply_date, status}]}]`.
5. **Candidate receipts**:
   - `ExceptionsRepository.latest_match_candidates(item_id)` returns the rows of the highest `ATTEMPT`, ordered by `chosen DESC, score DESC`, at most 10.
   - Each gets a fresh `fusion.get_receipt(receipt_id)` (concurrently, `asyncio.gather` bounded by a semaphore of 4) for `remaining`, `receipt_date`, `amount`, `customer` and `currency`.
   - Output: `{receipt_number, receipt_id, receipt_date, amount, remaining, currency, customer, score, qualifies, chosen, stale}`.
   - If a receipt read fails, the stored values are kept with `stale=true`.
6. **`autofix_attempts`**: `ExceptionsRepository.autofix_attempts(item_id)` returns `AUTOFIX_ATTEMPT` history rows oldest first, as `[{at, code, decision, attempt, limit, reasoning}]`. `decision`, `attempt` and `limit` come from s18's history payload keys `decision`, `attempt` and `limit`; a missing key gives `null`.
7. **`applications`** (additive, see Assumptions): `ApplicationLedgerRepository.for_item(item_id)` gives `[{ledger_id, line_no, receipt_id, receipt_number, customer_trx_id, transaction_number, amount, status, fusion_application_id, applied_at, reversed_at, reversed_by, reversal_reason}]`. `receipt_number` comes from the matching `MATCH_CANDIDATE` row; `transaction_number` comes from `LINE_RESULT` by `line_no`.
8. **Failure isolation**: every Fusion section is wrapped. A `FusionError` adds `warnings: [{section, code, message}]`, and that section is empty or `null`. The endpoint still returns 200, because a person needs the rest of the context during a Fusion outage. A failed build is not cached.
9. **Fusion client**:
   - `get_fusion_reader()` returns `read_only(build_fusion_client(get_settings()))`. It is created lazily and `lru_cache`d per process. Closing it on shutdown (`aclose`) is left to the app lifespan or s30's container; this story adds no shutdown hook.
   - The API never writes to Fusion from these endpoints. `read_only` makes that structural.

### Web: page data flow

- `page.tsx`:
  - `const sp = await props.searchParams; const filters = parseExceptionFilters(sp)`, where an invalid value falls back to the default for that key and never throws.
  - `item` matches `/^WI-\d+$/`, giving `itemId`.
  - Start in parallel: `getExceptions(filters)`, `getMe()`, and, when `itemId` is set, `getItemDetail(itemId)` (s19 `GET /items/{id}`), `getItemHistory(itemId)` and `getFusionContext(itemId)`.
  - The fusion-context cards render inside `<Suspense>` with skeleton cards (RC-38), because Fusion reads are slow.
- **Permissions**: `me.permissions` gates the controls.
  - Dequeue, Requeue, Release and the edit form need `items:work`.
  - Reverse needs `apply:reverse`.
  - Archived-toggle and override need `classification:override`.
  - Hidden, not disabled (design §1).
- **Sheet body**:
  - Why it's stuck.
  - Auto-fixes tried.
  - The edit form. It is shown only when there is an adjudication final, and editable only while `lockView.kind === "mine"`.
  - Pickers.
  - Applications.
  - Fusion context cards.
  - s19's `HistoryTimeline` in a `Collapsible` "Full history".

### Lock lifecycle (client)

- **Dequeue**: `dequeueAction({itemId})` → `POST /items/{id}/lock`.
  - On success, the `LockBanner` variant is `mine`, with the text "Locked by you since HH:MM. Automation won't touch this item until you requeue or release it." and the **Requeue** and **Release lock** buttons.
  - Errors map through `lockErrorToast`:
    - `lock_conflict` → "`<details[0].owner_name>` dequeued this item a moment ago."
    - `item_busy` → "The line is processing this item; try again in a moment."
    - `lock_not_held` → "Your lock expired — automation may act. Dequeue again".
    - Anything else → s19's `error-alert` message.
- **Lease**: `lease_ms = Date.parse(expires_at) - Date.parse(acquired_at_or_renewed_at)`, computed from the response of the acquire or renew call. `useLockLease` sets an interval of `lease_ms / 3`. The renew response resets the cadence.
  - A renew failure with `lock_not_held` becomes the `expired` state.
  - An `item_busy` failure is retried on the next tick.
  - A one-shot timer at `expires_at` also flips to `expired` when renewals didn't happen (tab asleep).
  - The interval is cleared on unmount, on sheet close, and when the lock isn't mine.
- **Release**: `releaseLockAction` → `DELETE /items/{id}/lock`, then `router.refresh()`.
- **Requeue**: `requeueAction(body)` → s18 `POST /items/{id}/requeue`.
  - On success: a toast "Requeued WI-n", `item` is removed from the URL, and `router.refresh()` runs. The item leaves the list because it is PENDING with no lock. s18 releases the lock in the same transaction.
  - On error: an `Alert` in the sheet with s19's `error-alert`. The RHF form isn't reset.

### Sheet transitions (AC8), `sheet-state.ts`

```ts
type SheetLockView =
  | { kind: "none" } | { kind: "mine"; since: string; expiresAt: string }
  | { kind: "other"; ownerName: string; since: string }
  | { kind: "expired" } | { kind: "taken_over"; ownerName: string };
type SheetNotice = { kind: "moved_on"; stage: Stage; state: ItemState } | { kind: "reasons_updated" } | null;
type SheetState = { stage: Stage; state: ItemState; lock: SheetLockView; notice: SheetNotice; editable: boolean };
```

`nextSheetState(prev, ev, me)` takes `ev = item_changed {id, stage, state, lock, payment_status}`:

| Case | Condition | Result |
|---|---|---|
| (b) | `prev.lock.kind === "mine"` and `ev.lock?.owner` exists and `!== me` | `taken_over(ev.lock.owner_name)`, `editable=false` |
| (c) | `prev.lock.kind` is `mine`, `expired` or `none`, `ev.lock === null`, and (`ev.state !== prev.state` or `ev.stage !== prev.stage`), with `ev.state` in `{PENDING, IN_PROGRESS, DONE}` | notice `moved_on`, lock `none`, `editable=false` |
| (d) | `ev.state` is `ESCALATED` or `AWAITING_RECEIPT` and differs from `prev` (or the stage changed) | notice `reasons_updated`, badge updated, lock re-derived from `ev.lock` |
| (e) | After my reversal: `ev.state === ESCALATED`, `ev.stage === MATCH_RECEIPT`, `ev.lock.owner === me` | lock stays `mine`, `editable=true`. The refreshed sheet shows the "Application reversed by …" `escalation_summary`. |
| otherwise | | lock re-derived from `ev.lock` (`mine`, `other`, `none`) |

(a) Expiry produces no event, because lazy expiry doesn't bump `UPDATED_AT`. `lockExpiredState(prev)` is called by `useLockLease`'s timer or by a renew that returns `lock_not_held`. The banner then reads "Your lock expired — automation may act. Dequeue again", with a Dequeue button, and `editable=false`.

Every handled event also calls `router.refresh()`, so the server-rendered body (why-stuck, autofix list, history) is re-read.

### Edit model (`edit-model.ts`)

- `editFormSchema`:
  - `payer_name`: string.
  - `remittance_reference`: string.
  - `payment_amount`: `/^-?\d+\.\d{2}$/`.
  - `currency`: `/^[A-Z]{3}$/`.
  - `payment_date`: ISO date.
  - `lines[]`:
    - `line_no`: int.
    - `kind`: enum from the OpenAPI `LineKind`.
    - `transaction_number`: string. It must be non-empty unless `kind` is `BANK_FEE`, `TARIFF` or `DISCOUNT`, enforced by `superRefine`.
    - `amount_paid` and `discount_claimed`: money string or empty.
- `applyEdits(final, values)` returns a new `RemittanceExtraction` JSON.
  - Each changed scalar sets `{value, confidence: 1, source: existing source}`.
  - Lines are matched by `line_no`; new lines get `confidence: 1, source: null`.
  - Untouched fields are left byte-identical.
- `diffSummary(before, after, {receipt?, customer?})` returns, for example, "You changed 2 fields: line 3 invoice 'INV1044' → 'INV-1044'; receipt → R-88213."
  - It counts every changed field, plus 1 for a picked receipt and 1 for a picked customer.
  - The pluralisation is "1 field" / "n fields".
  - Line labels: "line N invoice", "line N amount", "line N kind"; header labels: "payer", "reference", "amount", "currency", "payment date".
- `buildRequeueBody(...)` returns `{corrected_extraction?, receipt_id?, customer_number?, note}`. `corrected_extraction` is present only when a field changed. `target_stage` is left unset, so s18's default applies.

## Interfaces provided (pinned)

### HTTP (s31 regenerates the types; s19's sidebar count uses `GET /exceptions?page_size=1` → `total`)

| Method and path | Permission | Success | Errors |
|---|---|---|---|
| `GET /exceptions` | items:read | 200 `ExceptionListOut` | 401/403, 422 `validation_error` |
| `GET /items/{item_id}/fusion-context` | items:read | 200 `FusionContextOut` | 401/403, 404 `item_not_found` |

```python
# cashapp/api/schemas/exceptions.py
ExceptionSort = Literal["age", "-age", "amount", "-amount", "payment_date", "-payment_date", "id", "-id"]
class ExceptionListQuery(BaseModel):  # model_config extra="forbid"; fields as in Design
    def to_filters(self) -> ExceptionFilters
class ExceptionRowOut(BaseModel):
    id: int; payer_name: str | None; amount: MoneyStr | None; currency: str | None; payment_date: date | None
    error_code: ErrorCode | None; autofix_tried: int; autofix_limit: int; age_s: int
    stage: Stage; state: ItemState; payment_status: PaymentStatus | None; lock: LockInfoOut | None
class ExceptionListOut(BaseModel): items: list[ExceptionRowOut]; total: int; page: int; page_size: int
class CustomerSiteOut(BaseModel): site_number: str; purpose: str | None; location: str | None; address: str | None
class RelationshipOut(BaseModel): account_number: str; name: str | None; directions: list[Literal["INBOUND", "OUTBOUND"]]
class CustomerContextOut(BaseModel):
    account_number: str; name: str; bill_to_site: CustomerSiteOut | None; location: str | None
    relationships: list[RelationshipOut]
class InvoiceContextOut(BaseModel):
    number: str; customer_trx_id: int; bill_to_customer: str | None; bill_to_site: str | None
    original_amount: MoneyStr; remaining: MoneyStr; currency: str; status: str
class CreditMemoApplicationOut(BaseModel):
    application_id: int; receipt_id: int; amount_applied: MoneyStr; apply_date: date; status: str
class CreditMemoHistoryOut(BaseModel):
    number: str; customer_trx_id: int; original: MoneyStr; remaining: MoneyStr; currency: str
    applications: list[CreditMemoApplicationOut]
class CandidateReceiptOut(BaseModel):
    receipt_number: str; receipt_id: int; receipt_date: date | None; amount: MoneyStr | None
    remaining: MoneyStr | None; currency: str | None; customer: str | None
    score: float; qualifies: bool; chosen: bool; stale: bool
class AutofixAttemptOut(BaseModel):
    at: datetime; code: ErrorCode | None; decision: str | None; attempt: int | None; limit: int | None
    reasoning: str | None
class LedgerApplicationOut(BaseModel):
    ledger_id: int; line_no: int; receipt_id: int; receipt_number: str | None; customer_trx_id: int
    transaction_number: str | None; amount: MoneyStr; status: str; fusion_application_id: int | None
    applied_at: datetime | None; reversed_at: datetime | None; reversed_by: str | None; reversal_reason: str | None
class ContextWarningOut(BaseModel):
    section: Literal["customer", "invoices", "credit_memos", "receipts"]; code: ErrorCode; message: str
class FusionContextOut(BaseModel):
    item_id: int; customer: CustomerContextOut | None; invoices: list[InvoiceContextOut]
    credit_memo_history: list[CreditMemoHistoryOut]; candidate_receipts: list[CandidateReceiptOut]
    autofix_attempts: list[AutofixAttemptOut]; applications: list[LedgerApplicationOut]
    warnings: list[ContextWarningOut]; built_at: datetime
```

```python
# cashapp/services/exceptions_query.py
AWAITING_EXCEPTION_AFTER: Final = timedelta(days=1)
FAILED_LINE_STATUSES: Final[frozenset[LineStatus]]     # derived as in Design
@dataclass(frozen=True, slots=True)
class ExceptionFilters:
    q: str | None = None; amount_min: Decimal | None = None; amount_max: Decimal | None = None
    date_from: date | None = None; date_to: date | None = None; error_codes: tuple[ErrorCode, ...] = ()
    stage: Stage | None = None; locked_by_me: bool = False; include_auto_applied: bool = False
    include_archived: bool = False; page: int = 1; page_size: int = 50; sort: str = "-age"
@dataclass(frozen=True, slots=True)
class ExceptionRow:
    item: WorkItem; autofix_tried: int; autofix_limit: int; age_s: int; lock: LockInfo | None
class ExceptionsQueryService:
    def __init__(self, config: RuntimeConfig | ConfigSnapshot, clock: Clock | None = None) -> None
    async def list(self, uow: UnitOfWork, filters: ExceptionFilters, principal: Principal) -> Page[ExceptionRow]

# cashapp/services/fusion_context.py   (dataclasses mirror the *Out models; the router maps 1:1)
class FusionContextCache:
    def __init__(self, *, ttl_s: float = 60.0, max_entries: int = 512, clock: Clock | None = None) -> None
    def get(self, item_id: int, version: int) -> FusionContext | None
    def put(self, item_id: int, version: int, ctx: FusionContext) -> None
class FusionContextService:
    def __init__(self, fusion: FusionClient, *, cache: FusionContextCache, clock: Clock | None = None,
                 max_credit_memos: int = 20, max_receipts: int = 10, fusion_concurrency: int = 4) -> None
    async def build(self, uow: UnitOfWork, item_id: int) -> FusionContext      # ItemNotFound (s40's) if missing

# cashapp/data/repositories/exceptions.py
class ExceptionsRepository(BaseRepository[WorkItem]):
    async def search(self, filters: ExceptionFilters, *, subject: str, now: datetime) -> Page[WorkItem]
    async def autofix_counts(self, items: Sequence[WorkItem]) -> dict[int, int]
    async def autofix_attempts(self, item_id: int) -> list[WorkItemHistory]
    async def latest_match_candidates(self, item_id: int, *, limit: int = 10) -> list[MatchCandidate]   # s13 model

# cashapp/api/routers/exceptions.py
def get_fusion_reader() -> FusionClient                    # lru_cache; read_only(build_fusion_client(get_settings()))
def get_exceptions_service(runtime: RuntimeConfigDep) -> ExceptionsQueryService
def get_fusion_context_service(fusion: FusionClient = Depends(get_fusion_reader)) -> FusionContextService  # module-level cache
```

```ts
// web/components/common/lock-banner.tsx  (shared; s19 may reuse it on the item view)
export type LockBannerProps = Readonly<{
  variant: "mine" | "other" | "expired" | "taken_over";
  ownerName?: string;          // other | taken_over
  since?: string;              // ISO; rendered HH:MM local (mine | other)
  actions?: React.ReactNode;   // Requeue / Release lock / Dequeue again
}>;
export function LockBanner(props: LockBannerProps): React.JSX.Element;
// Exact copy:
// mine:       "Locked by you since 10:42. Automation won't touch this item until you requeue or release it."
// other:      "Locked by Priya N. since 09:15"
// expired:    "Your lock expired — automation may act. Dequeue again"
// taken_over: "Priya N. took over this item"
// role="status", violet --status-locked border/dot for mine|other, attention token for expired|taken_over

// web/app/(shell)/exceptions/_lib/search-params.ts
export const exceptionFiltersSchema: z.ZodType<ExceptionFilters>;
export type ExceptionFilters = Readonly<{ q?: string; amountMin?: string; amountMax?: string; dateFrom?: string; dateTo?: string;
  errorCodes: readonly ErrorCode[]; stage?: Stage; lockedByMe: boolean; includeAutoApplied: boolean; includeArchived: boolean;
  page: number; sort: ExceptionSort; item?: `WI-${number}` }>;
export function parseExceptionFilters(sp: Record<string, string | string[] | undefined>): ExceptionFilters;
export function filtersToSearchParams(f: ExceptionFilters): URLSearchParams;   // round-trips with parse; defaults omitted
export function isFiltered(f: ExceptionFilters): boolean;

// web/components/exceptions/sheet-state.ts — as in Design (pinned for the tests)
export function nextSheetState(prev: SheetState, ev: ItemChangedEvent, me: string): SheetState;
export function lockExpiredState(prev: SheetState): SheetState;
// web/components/exceptions/edit-model.ts
export function diffSummary(before: EditFormValues, after: EditFormValues, choices: { receipt?: string; customer?: string }): { count: number; text: string };
export function isReverseConfirmValid(input: { reason: string; typed: string; receiptNumber: string }): boolean;   // trimmed, exact (case-sensitive) match, reason non-blank
```

## Migrations

None. The workbench reads s02's `WORK_ITEM`/`WORK_ITEM_HISTORY`, s11's `CUSTOMER_RESOLUTION`, s09's `ADJUDICATION`, s13's `MATCH_CANDIDATE` and s15's `LINE_RESULT`/`APPLICATION_LEDGER`. The fusion-context cache is in-process. Expected Alembic head: unchanged.

## TEST PLAN (written and run in step 5 only)

**Python.** aiosqlite fixtures `uow` and `uow_factory` (s02), `FrozenClock`, `make_principal` and `override_principal` (s04), `make_runtime_config` (s28), `FakeFusionClient` (s05), and the `api/tests/support/exceptions.py` seeders. **Web unit.** Vitest + RTL, with s31's `api-mock` / `sse-mock` and s19's `fixtures/dto.ts`. **Browser.** Playwright in `web/e2e/exceptions/`, with s04 `withSession` and the stub API scenarios, at 1280 px unless stated otherwise.

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/unit/services/test_exceptions_query.py::test_default_set_escalated_awaiting_over_1d_failed_lines_and_live_locks` (AWAITING 23 h excluded, 25 h included; DONE-success excluded; PENDING without failed lines excluded) |
| 1 | `…::test_include_auto_applied_adds_done_success_items` |
| 1 | `…::test_include_archived_adds_archived_items` |
| 1 | `…::test_q_matches_wi_id_payer_invoice_and_receipt_number` (and `%`/`_` are escaped) |
| 1 | `…::test_amount_range_is_money_eq_tolerant` (`100.004` within min `100.00`, max `100.00`; `100.01` outside) |
| 1 | `…::test_date_error_code_stage_and_locked_by_me_filters` (expired own lock is not "locked by me") |
| 1 | `…::test_sort_allowlist_and_paging_total` |
| 1 | `…::test_autofix_tried_counts_current_code_since_last_requeue_and_limit_from_config` |
| 1 | `…::test_failed_line_statuses_derived_from_line_status_enum` |
| 1 | `api/tests/api/test_exceptions_router.py::test_get_exceptions_shape_and_money_as_string` |
| 1 | `…::test_get_exceptions_requires_items_read` (401 without token; principal without items:read → 403) |
| 1 | `…::test_get_exceptions_422_on_inverted_ranges_and_unknown_param` |
| 2 | `api/tests/unit/services/test_fusion_context.py::test_customer_card_bill_to_site_location_and_relationships` |
| 2 | `…::test_invoices_from_fresh_find_transactions_with_original_remaining_currency_status` |
| 2 | `…::test_credit_memo_history_lists_applications` |
| 2 | `…::test_candidate_receipts_from_latest_attempt_with_fresh_remaining_and_stale_fallback` |
| 2 | `…::test_autofix_attempts_from_history_rows_oldest_first` |
| 2 | `…::test_applications_from_ledger_with_receipt_and_transaction_numbers` |
| 2 | `…::test_cache_hits_within_60s_misses_after_ttl_or_version_bump` (FakeFusionClient `calls` count) |
| 2 | `…::test_fusion_error_in_one_section_yields_warning_and_no_cache` |
| 2 | `…::test_uses_read_only_client_no_write_methods_called` |
| 2 | `api/tests/api/test_exceptions_router.py::test_fusion_context_200_shape_and_404_item_not_found` |
| 2 | `…::test_exceptions_routes_in_openapi` (both operations; `ExceptionListOut`, `FusionContextOut` present) |
| 3 | `web/tests/unit/exceptions/search-params.test.ts` › `parse and filtersToSearchParams round-trip; invalid values fall back to defaults` |
| 3 | `web/tests/unit/exceptions/filter-bar.test.tsx` › `each control writes its query key and Show auto-applied is off by default` |
| 3 | `web/e2e/exceptions/list.spec.ts` › `filter bar drives the URL and the API query` (search, amount, date range via calendar, error-code multi-select, stage, Locked by me) |
| 3 | `…` › `columns render WI id, payer, money, date, error badge, "2 / 3", age, lock owner and row menu` |
| 3 | `…` › `auto-applied items hidden by default and shown when the switch is on` |
| 4 | `web/e2e/exceptions/sheet.spec.ts` › `row click opens the 60% sheet and deep link ?item=WI-20481 opens it on load` |
| 4 | `…` › `why it's stuck shows escalation summary, error code and last error` |
| 4 | `…` › `auto-fixes tried list shows outcome icons and reasoning in order` |
| 4 | `…` › `fusion context cards show customer bill-to location and relationships, candidate receipts, invoices, credit memo history` |
| 5 | `web/tests/unit/exceptions/lock-banner.test.tsx` › `renders exact copy for mine, other, expired, taken_over` |
| 5 | `web/tests/unit/exceptions/lock-messages.test.ts` › `lock_conflict and item_busy map to the design toasts` |
| 5 | `web/tests/unit/exceptions/use-lock-lease.test.ts` › `renews every lease/3 while open, stops on close, expires on lock_not_held` (fake timers) |
| 5 | `web/e2e/exceptions/lock.spec.ts` › `Dequeue posts the lock and shows the violet banner with Requeue and Release lock` |
| 5 | `…` › `locked by someone else shows owner and no edit controls` |
| 5 | `…` › `409 lock_conflict and 409 item_busy show the toasts` |
| 6 | `web/tests/unit/exceptions/edit-model.test.ts` › `applyEdits changes only edited fields; diffSummary text matches design example` |
| 6 | `…` › `editFormSchema rejects bad money, currency and empty invoice for INVOICE lines` |
| 6 | `web/e2e/exceptions/requeue.spec.ts` › `edit a line, pick a receipt, see the diff summary, requeue posts the body and the item leaves the list` |
| 6 | `…` › `customer picker shown for CUSTOMER_NOT_FOUND and sends customer_number` |
| 6 | `…` › `requeue error shows an alert and keeps form values` |
| 7 | `web/tests/unit/exceptions/reverse-dialog.test.tsx` › `confirm disabled until reason and exact receipt number` |
| 7 | `web/e2e/exceptions/reverse.spec.ts` › `reverse visible only with apply:reverse and posts reason and confirm_receipt_number` |
| 8 | `web/tests/unit/exceptions/sheet-state.test.ts` › `(a) expiry, (b) taken over, (c) moved on, (d) re-escalated or parked, (e) after reversal stays mine` (one `it` per case) |
| 8 | `web/e2e/exceptions/live.spec.ts` › `item_changed events update the banner, badge and notice without reload` (sse stub drives b, c, d, e; a via a short lease) |
| 9 | `web/e2e/exceptions/classification.spec.ts` › `archived items reachable with Show archived and "This is a remittance" posts the override` |
| 9 | `…` › `override control hidden without classification:override` |
| 10 | `web/e2e/exceptions/states.spec.ts` › `loading skeleton, empty state with flow link, filtered-empty with Clear filters` |
| 10 | `…` › `sheet is full-screen below 1024 px` (viewport 900) |
| 10 | `…` › `API error renders error-alert with request id and Retry` (TEST-17) |

Coder gates: api `uv run ruff check . && uv run ruff format --check .`, `uv run pyright`; web `npx next typegen && npx tsc --noEmit`, `npx eslint .`. Run `npm run api:sync` after the routes exist.

## Assumptions and deviations

- **New file `cashapp/data/repositories/exceptions.py`** (not in the story's owned list). CLAUDE.md forbids queries outside repositories, and it touches no other story's file. `latest_match_candidates` queries s13's `MatchCandidate` model; if s13 ships an equivalent accessor, the merger re-points to it (one copy).
- **`applications` and `warnings` are additive to the AC2 shape.** The Reverse action (AC7) needs ledger ids and receipt numbers, and s19's `GET /items/{id}` lines carry no `ledger_id`. A partial Fusion outage must not blank the whole workbench.
- **"reference" search** covers WI id, receipt number (MATCH_CANDIDATE) and invoice numbers (LINE_RESULT). Searching the remittance reference inside the adjudication JSON is left out, because it would need dialect-specific `JSON_VALUE`. That is recorded for a later story.
- **Exceptions base set also includes live-locked items**, so a dequeued item doesn't vanish while being worked.
- **`age_s` is measured from `created_at`** (arrival).
- **`autofix_tried`** counts attempts for the current code since the last requeue. It relies on s18 writing `payload.event = "requeue"` on its HUMAN_ACTION row and `payload.decision/attempt/limit` on AUTOFIX_ATTEMPT rows. If s18 names those keys differently, only the repository and mapper change.
- **Lease cadence** is derived from the lock response (`expires_at − acquired_at`), so no config endpoint is needed (story assumption: `lease/3`).
- **The `/flow/stream` subscription**: if s19 exposes a shared provider or context for the flow stream (SSE-26), `use-item-live` subscribes through it. Otherwise it calls s31's `useEventStream("/flow/stream", {schema})` itself, and the merger consolidates.
- **`/me`**: `getMe()` wraps `api("get", "/me")` in React `cache`. If s19 already exports a `getMe`, the merger deletes this one and imports s19's.
- **`radio-group`** isn't in s01's shadcn list. It is added with `npx shadcn@latest add radio-group`. With the Base UI base this should add no npm dependency. If the CLI changes `package.json` or the lockfile, the merger resolves it (logged per s01's rule).
- **Playwright testDir** is s01's `web/e2e/`; s04 wrote `web/tests/e2e`, which s01's config wouldn't pick up, so this story uses `web/e2e/`.
- **Browser tests need the server-side API stubbed.** Server Components call `API_BASE_URL` from the Next server, so `page.route` can't intercept those calls. The stub is a small Node HTTP server with a scenario-control endpoint, started as an extra Playwright `webServer` entry, with `API_BASE_URL` in `.env.test` pointing at it.
  - It reuses s19's stub if s19 ships one.
  - Otherwise this story adds `web/e2e/support/api-stub.ts` and makes one append-only edit to `web/playwright.config.ts`.
- **Fusion client in the API**: `get_fusion_reader()` lives in this router module. If s38 (merged first) already provides an API-side Fusion dependency, the merger switches to it (one copy).
- **Error-code multi-select** is `Popover`+`Command`, because shadcn has no multi-select primitive. "Locked by me" is a `Switch` rather than a toggle button, which avoids adding another primitive.

## Risks

- **Fusion latency**: fusion-context can make up to 1 + 1 + 20 + 10 Fusion calls on a cold cache. Mitigations: the bounded semaphore, the Suspense-streamed cards, the 60 s cache, and per-section warnings. If p95 is still too slow on a real pod, drop the per-receipt `get_receipt` reads and use the stored candidate values.
- **The `OR`/`EXISTS` query on ATP** with paging: verify the plan on DEV ATP with an `-m atp` smoke run. It may need an index on `LINE_RESULT(LINE_STATUS)` later; that would be a new revision, owned by whoever adds it.
- **Expiry is invisible to SSE** (lazy expiry): AC8(a) depends on the client timer. A tab asleep past expiry shows `expired` on wake, which is the correct outcome.
- **The `item_changed` 5 s tick latency** (s19) can let a person act on a stale view. The API still refuses with `lock_not_held`/`lock_conflict`, and the UI maps those errors.
- **Edits on a long lines grid** (100+ lines): RHF `useFieldArray` without virtualization. This is acceptable for the expected sizes; revisit if real remittances exceed about 300 lines.
- **s18, s38 and s19 are unplanned** at the time of writing. The request and response shapes used here come from their story ACs, so any drift appears at `api:sync` as a type error, not at runtime.
