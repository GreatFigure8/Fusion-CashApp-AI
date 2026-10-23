# Plan: exceptions-workbench-restyle

Story: [story.md](story.md) · Issue #48 (AC 3) · Board: `design/project/glass/Exceptions.dc.html` (design.md §3.4; Flow §3.2 and Items §9 have no board) · Deps: glass-theme-shell (same wave, pinned interface in §7a).

## 1. Approach

- research.md a1: retheme through tokens and the shared Glass components only. No structural change: the workbench already lists exceptions only and hides applied items (`include_auto_applied` defaults to off). No API change, no new endpoint, no migration.
- Restyle the existing files, don't rewrite them. Behaviour (dequeue, renew, requeue, release, reverse, override, SSE item updates) keeps the same server actions and API calls. Only markup, classes and copy change.
- Filter chips are presets over the existing URL filter state (`error_codes`, `locked_by_me`). Their counts come from the existing `GET /exceptions` query: the same `getExceptions` path with `page_size=1`, reading `total`, one call per chip, started together (DF-4). "N applied items hidden" is `total(include_auto_applied=1) − total`.
- Split layout: the list is a `GlassPanel` holding `DataTable` (`flex-[999_1_480px]`), beside a detail `aside` (`flex-[1_1_420px]`, accent-glow ring). Below 1024 px the same server-rendered body (RC-8) goes into `ui/sheet` instead.
- Flow and Items get the Glass treatment through the same shared components (`TopBar`, `GlassPanel`, `Pill`, `Meter`, `SkeletonRows`, `StateCard`). Their logic doesn't change.
- Colour comes from tokens only. A Vitest grep test guards `components/{exceptions,flow,items}/**`.

## 2. Files

Paths are relative to `web/`. Server Components stay the default. `"use client"` is used only where a file already has it or is marked (client) below (RC-5, RC-6).

### Create

| # | File | Purpose |
|---|---|---|
| 1 | `components/exceptions/filter-chips.ts` | Pure and client-safe. `EXCEPTION_CHIPS` (pinned in §7b), `activeChip(filters)` and `chipFilters(filters, chip)`: replaces `errorCodes` and `lockedByMe`, keeps every other filter, resets `page`, drops `item`. |
| 2 | `components/exceptions/exception-filter-chips.tsx` (client) | The chip row: one `FilterChip` per chip, labelled `"<label> · <count>"` (the count is omitted when it's unknown). Click calls `router.push` with `filtersToSearchParams(chipFilters(...))` and `scroll:false`. Wrapped in `<Suspense>` by the page (RT-27). |
| 3 | `components/exceptions/reason.ts` | `REASON_TONE: Record<ErrorCode, PillTone>` is exhaustive, so a new API code is a `tsc` error. Codes map to tones: always-a-person codes → `locked`; not-found, failed and fault codes → `err`; ambiguous, variance, low-confidence and transient codes → `warn`. `reasonLabel(code)` uses short labels ("Ambiguous receipt", "Amount variance", "Invoice not found", "Customer not found", "Prepayment", "Low confidence", "PO reference only") and falls back to `humanizeEnum`. |
| 4 | `components/exceptions/list-format.ts` | `footerText({total, appliedHidden, showApplied})` returns "63 exceptions · 1,221 applied items hidden", "1 exception · …", or "N items · applied items shown". `lockOwnerLabel(lock, meSubject)` returns `"You"`, the owner's name, or `null`. |
| 5 | `components/exceptions/autofix-timeline.ts` | Pure `buildAutofixTimeline(attempts, itemState)` returns `{tried, limit, steps:[{text, detail, at, tone:"warn"\|"err"}]}`. Each attempt becomes a warn step. An `ESCALATED` item ends with an err step "Escalated to a person" ("Handlers exhausted", at the time of the last `escalate` attempt). `limit` is the max `attempt.limit`, falling back to `tried`. |
| 6 | `components/exceptions/show-applied-toggle.tsx` (client) | The "Show applied items" checkbox for the `TopBar` right slot. It writes `include_auto_applied=1` and resets `page`. Default off. |
| 7 | `components/exceptions/detail-frame.tsx` (client) | Owns `close()` (moved from `exception-sheet.tsx`). At ≥1024 px it renders `<aside aria-label="Item WI-n">` as a `GlassPanel` with `ring-1 ring-brand-hi/35 shadow-float`. Below that it renders `Sheet`/`SheetContent` at full width. Children are rendered once (RC-8). |
| 8 | `components/exceptions/candidate-receipt-tiles.tsx` | Async Server Component. It awaits the cached `getFusionContext` promise and renders the qualifying `candidate_receipts` as bordered tiles: mono number, then "19 Oct · customer". The `chosen` tile gets the accent border and `bg-brand-soft`. Shown inside "Why it's stuck". |
| 9 | `components/exceptions/lock-conflict-card.tsx` (client) | `StateCard kind="error"`, label "Error · lock conflict", headline "`<name>` locked this item first", body "You can view it read-only until they release it.", and a "View read-only" button. Shown in the detail when the lock view is `other`. The button dismisses it into the read-only detail (local state only). |
| 10 | `components/items/source-tag.ts` | Moves `SOURCE_TAG` out of `extraction-tabs.tsx`, unchanged: `{A:"A", B:"B", both:"A+B", human:"Human"}`. Adds `sourceTone(tag)`: `both`→`ok`, `human`→`accent`, others→`muted`. Shared by `extraction-tabs` and `edit-form` (DRY). |
| 11 | `hooks/use-media-query.ts` (client) | `useMediaQuery(query, serverValue)` built on `useSyncExternalStore` and `matchMedia`, with every access guarded. `detail-frame` uses `("(min-width: 1024px)", true)`. |
| 12 | `components/ui/checkbox.tsx` | Added with `npx shadcn@latest add checkbox` (CLI output, not hand-written). |

### Change

| File | Change |
|---|---|
| `app/(shell)/exceptions/page.tsx` | Renders `TopBar title="Exceptions"` with `<ShowAppliedToggle/>` in its slot. The chip row comes next, then the filter bar, then the split: the table plus footer, beside `ExceptionSheet` in `DetailFrame`. Starts `getExceptionCounts(filters)` together with the list, `me`, detail, history and context (DF-4). Body order follows the board: header → lock status → `WhyStuck` (with `<Suspense fallback={<SkeletonRows rows={2}/>}><CandidateReceiptTiles/></Suspense>`) → `<Suspense><FusionAutofix/></Suspense>` → `EditForm` → `<Suspense><FusionReceiptPicker/></Suspense>` → the rest of the Fusion context → action row. The inline "Full history" collapsible becomes a `Link` to `/items/WI-n` (RT-22). History is still fetched for `lastErrorText`. Awaits `searchParams` (TS-16). |
| `app/(shell)/exceptions/_lib/queries.ts` | Adds `getExceptionCounts(filters): Promise<{chips: Partial<Record<ChipId, number>>, appliedHidden: number \| null}>` (pinned in §7b). Calls run in parallel, are `cache()`-wrapped by query string, and use `page_size=1`. A failed call leaves its key undefined and never fails the page (TEST-18). |
| `app/(shell)/exceptions/loading.tsx` | Top bar skeleton, chip skeletons, then `GlassPanel` + `SkeletonRows rows={10} caption="Reading exceptions…"` (RT-8). |
| `app/(shell)/exceptions/error.tsx` | `StateCard kind="error"` with Retry. Logic unchanged (TEST-20, TEST-21). |
| `components/exceptions/exceptions-table.tsx` | New props `meSubject` and `selectedId: number \| null`. Passes `selectedRowId` to `DataTable`. Wraps the table in a `GlassPanel` with `overflow-x-auto`. Renders the footer from `footerText`. Empty states become `StateCard`s. |
| `components/exceptions/exception-columns.tsx` | Columns follow the board: Item (mono, `text-brand-ink`), Payer (`payer_name` as today), Amount (`Money`, right-aligned, mono, currency-prefixed), Reason (`Pill tone=REASON_TONE[code]` with `reasonLabel`), Age (mono, right-aligned, `text-muted-foreground`), lock owner (`lockOwnerLabel`, locked-tone text), and the row menu (Open/Dequeue unchanged). The Payment date and Auto-fixes columns are dropped: both are still shown in the detail. |
| `components/exceptions/exceptions-filter-bar.tsx` | Restyled to tokens and mono labels. The "Locked by me" switch is removed (now the Locked chip). The "Include auto-applied" switch is removed (now the top-bar checkbox). Search, amount, date, stage, the error-code combobox, sort and archived stay. |
| `components/exceptions/exception-sheet.tsx` | Uses `DetailFrame` instead of `Sheet`. The header shows mono "WI-n · CCY 1,234.00" (from the new `amount`/`currency` picks on `item`), the 17px/600 reason line (`reasonLabel(last_error_code)`, or "Needs a person"), `StatusBadge` and close. Below the header it shows `<LockStatus/>`, the children, then the action row `<LockActions/>` plus the "Full history" link. Shows `LockConflictCard` when the lock view is `other` and not yet dismissed. Notices are unchanged. |
| `components/exceptions/why-stuck.tsx` | `MonoLabel` "Why it's stuck", 13.5px summary, the error-code `Pill`. New optional `candidates?: ReactNode` slot. The last error stays in a `bg-surface-3` mono well. |
| `components/exceptions/autofix-list.tsx` | Renders `buildAutofixTimeline`: the label "Auto-fixes tried · N of M", then a vertical timeline (10px nodes, `bg-warn` or `bg-err`). Each step shows its text, then the result and time in `text-muted-foreground` 12px. Decision icons are dropped. Takes the new `itemState` prop. |
| `components/exceptions/fusion-context-section.tsx` | Split into `FusionAutofix`, `FusionReceiptPicker` and `FusionContextSection` (the rest). Each is an async Server Component awaiting the same cached promise, so the page can place them in the board order. Content is unchanged. |
| `components/exceptions/receipt-picker.tsx` | Becomes `ui/select` labelled "Receipt to use" with `MonoLabel`. The `setReceipt` and editable rules are the same. Options read "RCPT-n · date · CCY remaining", with "(system pick)" on the chosen one. |
| `components/exceptions/edit-form.tsx` | Inputs use `font-mono` and token borders. The Lines table gains a Source column with `Pill tone=sourceTone(tag)` and text `SOURCE_TAG[tag]`. A new prop `lineSources: Readonly<Record<number, string>>` maps `line_no` to `provenance["lines[i]"]`, built in the page from `extraction.final.lines` and `extraction.provenance`. Added lines show no pill. Validation and `setAfter` are unchanged. |
| `components/exceptions/lock-controls.tsx` | Split into `LockStatus` (the banner, or Dequeue) and `LockActions` (`RequeueDialog` + "Unlock"). The handlers (`dequeueAction`, `releaseLockAction`, `lockErrorToast`) are unchanged. "Release lock" is relabelled "Unlock". |
| `components/exceptions/requeue-dialog.tsx` | The trigger becomes primary (`default` + glow). Its label is "Requeue to match receipt" when `draft.receipt` is set or the code is `RECEIPT_AMBIGUOUS`, otherwise "Requeue". The dialog body and `requeueAction` are unchanged. |
| `components/exceptions/empty-states.tsx` | `NoExceptions` becomes `StateCard kind="empty"`: label "Empty", headline "No exceptions right now", body "Everything applied or is fixing itself. Applied items stay hidden unless you show them." `NoMatches` becomes a `StateCard` "No exceptions match these filters" with a Clear filters link. |
| `components/exceptions/fusion-context-cards.tsx`, `applications-table.tsx`, `customer-picker.tsx`, `classification-override.tsx`, `reverse-dialog.tsx`, `retry-alert.tsx` | Token restyle only: `Badge` becomes `Pill`, inner cards use `rounded-xl border-line-strong bg-surface-2`, labels use `MonoLabel`. No logic change. |
| `components/common/lock-banner.tsx` | Locked-tone styling (`border-locked/30 bg-locked-soft text-locked-ink`, through the token aliases). The `mine` copy becomes "Locked by you since HH:MM. Automation won't act on this item." API unchanged. |
| `components/common/history-timeline.tsx` | Node and step styling matches the board (`.step`/`.node`), with mono timestamps. API unchanged. |
| `components/flow/stage-tile.tsx` | Station-style card: `rounded-xl border border-line bg-surface-2/40 px-3.5 py-3 gap-2`. Mono stage name, errors as an err `Pill`, mono in-queue count, and the existing sparkline and texts. The focus ring is the accent halo. |
| `components/flow/backlog-bar.tsx` | `Progress` becomes `Meter value={processed} max={total} size={5} tone="accent"`. The text and Pause behaviour are unchanged. Wrapped in a `GlassPanel`. |
| `components/flow/flow-monitor.tsx` | The heading becomes `TopBar title="Flow"`, with the stale pill and Ask button in the slot. The stage line becomes `grid grid-cols-[repeat(auto-fill,minmax(210px,1fr))] gap-3` inside a `GlassPanel` (so there's no horizontal scroll at 375 px). Error/empty use `StateCard`. The `LlmChat` usage is untouched. |
| `components/flow/stage-items-table.tsx` | Inside a `GlassPanel`, using the restyled `DataTable`. Status via `StatusBadge`. |
| `app/(shell)/flow/[stage]/page.tsx`, `app/(shell)/flow/loading.tsx`, `app/(shell)/flow/[stage]/loading.tsx`, `app/(shell)/flow/error.tsx` | `TopBar` title, `SkeletonRows`, and an error `StateCard`. Logic unchanged. |
| `components/items/item-view.tsx`, `item-header.tsx`, `extraction-tabs.tsx`, `lines-table.tsx`; `app/(shell)/items/[id]/loading.tsx` | Panes become `GlassPanel`s with `PanelHeader`. The header pills are `Pill`/`StatusBadge`. `extraction-tabs` imports `SOURCE_TAG`/`sourceTone` from `source-tag.ts` and renders a `Pill`. The 3-pane grid keeps `min-w-0`, and tables sit in `overflow-x-auto`. `LlmChat` is untouched. |

No `api/` files. No router, no model, no migration.

### Design checklist (Exceptions board, plus Flow and Items). The coder ticks each item in `validation.md`.

- [ ] TopBar: title "Exceptions"; env pill `DEV`/`PROD` (warn, mono); `Live` pill with glowing dot; `Sample data` muted pill (dev only, from the shell). All provided by `TopBar`.
- [ ] Right slot: native-look checkbox "Show applied items", default off, accent colour.
- [ ] Chips (12.5px, `FilterChip`): `All · N`, `Ambiguous receipt · N`, `Amount variance · N`, `Invoice not found · N`, `Customer not found · N`, `Always a person · N`, `Locked · N`. The active chip has the `--acc-hi` border and `--acc-soft` fill.
- [ ] Table headers (mono, 11px, uppercase): Item · Payer · Amount (right) · Reason · Age (right) · (lock).
- [ ] Item column mono in `text-brand-ink`; Amount `CCY 1,234.00` mono, right-aligned; Reason pill warn, err or locked; Age mono in `--soft`; lock "You" or name in locked-ink 12px.
- [ ] Selected row tint (`DataTable` selected API, `#4f7cff14` via token).
- [ ] Footer 12px `--soft`: "N exceptions · N applied items hidden".
- [ ] Detail: glass with the accent glow (`0 0 0 1px` acc-hi/35 + `shadow-float`); header mono "WI-n · CCY amount" 12px soft; reason 17px/600; close button `×` with aria-label "Close".
- [ ] Lock banner: violet tone, "Locked by you since HH:MM. Automation won't act on this item."
- [ ] `MonoLabel` "Why it's stuck"; body 13.5px; candidate receipts in a 2-column tile grid. The chosen tile has the accent border and soft fill; the others have a `--line2` border.
- [ ] `MonoLabel` "Auto-fixes tried · N of M"; 10px nodes (warn, then err for the last step); final step "Escalated to a person" with "Handlers exhausted · HH:MM".
- [ ] `MonoLabel` "Lines": invoice input (mono), amount input (mono, right-aligned), source pill `A+B` (ok) or `A` (muted).
- [ ] `MonoLabel` "Receipt to use": `ui/select`.
- [ ] Actions: primary "Requeue to match receipt" (with glow), outline "Unlock", "Full history" link pushed right.
- [ ] Loading: `SkeletonRows` with the shimmer (reduced-motion safe).
- [ ] Empty: label "Empty", "No exceptions right now", "Everything applied or is fixing itself. Applied items stay hidden unless you show them."
- [ ] Error: err border, label "Error · lock conflict", "`<name>` locked this item first", "You can view it read-only until they release it.", button "View read-only".
- [ ] Below 1024 px the detail is a full-width `ui/sheet`; at 375 px there is no horizontal page scroll.
- [ ] Flow: `TopBar` "Flow"; KPI strip uses `KpiCard`; stage tiles are station cards (mono name, err pill, mono counts); backlog bar is a 5px accent `Meter`; the grid wraps.
- [ ] Flow stage: `TopBar` with the stage name; table in a `GlassPanel`.
- [ ] Items: header pills; panes in `GlassPanel`; extraction "From" column as a `Pill`; history timeline restyled.

## 3. Test plan

Nobody writes or runs these until step 5 (TEST-1). The unit tests are Vitest (jsdom, `tests/support/api-mock.ts` msw). Client and synchronous components are render-tested; async Server Components are covered only by Playwright (TEST-2). The browser tests are Playwright against `next build && next start` with the programmable mock API (`tests/support/mock-api-server.ts`, TEST-12), using visibility-aware locators (TEST-14).

Test-support change for the tester: today `mock-api-server.ts` keys routes by pathname only. Add an optional `query` matcher to `setMockRoute(method, path, response, { query })`: the most specific route wins, and the request's `search` is recorded. This is additive, so the existing specs are unaffected. It's needed so each chip count can return a different `total`.

| AC | Test (path :: name) | Type |
|---|---|---|
| 1 | `web/components/exceptions/list-format.test.ts` :: "footerText says N applied items hidden when off and applied items shown when on" | unit |
| 1 | `web/components/exceptions/show-applied-toggle.test.tsx` :: "checkbox is off by default and pushes include_auto_applied=1 with the page reset" | unit |
| 1 | `web/e2e/exceptions-workbench.spec.ts` :: "top bar shows Exceptions, env, Live and Sample data; Show applied items changes the footer count" (board: Exceptions top bar) | browser |
| 2 | `web/components/exceptions/filter-chips.test.ts` :: "activeChip resolves All, each code group and Locked from the URL filters" | unit |
| 2 | `web/components/exceptions/filter-chips.test.ts` :: "chipFilters keeps other filters, replaces error codes and locked_by_me, resets page and drops item" | unit |
| 2 | `web/app/(shell)/exceptions/_lib/queries.test.ts` :: "getExceptionCounts calls GET /exceptions once per chip with page_size=1 and returns each total" | unit |
| 2 | `web/app/(shell)/exceptions/_lib/queries.test.ts` :: "a failed count call leaves that chip without a count and the rest still resolve" | unit |
| 2 | `web/app/(shell)/exceptions/_lib/queries.test.ts` :: "appliedHidden is total with include_auto_applied minus the list total" | unit |
| 2 | `web/components/exceptions/exception-filter-chips.test.tsx` :: "renders seven chips with counts, marks the active one aria-pressed and navigates on click" | unit |
| 2 | `web/e2e/exceptions-workbench.spec.ts` :: "filter chips show counts from the exceptions query and highlight the active chip" (board: chip row) | browser |
| 3 | `web/components/exceptions/reason.test.ts` :: "every ErrorCode has a tone; always-a-person codes are locked, not-found codes err, ambiguous and variance warn" | unit |
| 3 | `web/components/exceptions/list-format.test.ts` :: "lockOwnerLabel returns You for my lock, the owner name otherwise, null when unlocked" | unit |
| 3 | `web/components/exceptions/exceptions-table.test.tsx` :: "renders Item, Payer, Amount, Reason, Age and lock columns with the selected row marked and the footer" | unit |
| 3 | `web/e2e/exceptions-workbench.spec.ts` :: "at 1440 the glass list and the detail panel sit side by side with the selected row tinted" (board: split) | browser |
| 3 | `web/e2e/exceptions-workbench.spec.ts` :: "below 1024 px opening a row shows the detail as a full-width sheet" | browser |
| 4 | `web/components/exceptions/autofix-timeline.test.ts` :: "attempts become warn steps and an escalated item ends with Escalated to a person; N of M from limits" | unit |
| 4 | `web/components/exceptions/autofix-list.test.tsx` :: "renders the Auto-fixes tried N of M label and one node per step" | unit |
| 4 | `web/components/exceptions/edit-form.test.tsx` :: "lines show A+B as an ok pill and A as a muted pill; added lines have no pill" | unit |
| 4 | `web/components/exceptions/lock-controls.test.tsx` :: "mine shows the banner copy, Requeue to match receipt and Unlock; Unlock calls releaseLockAction" | unit |
| 4 | `web/components/exceptions/receipt-picker.test.tsx` :: "selecting a receipt sets the draft receipt; disabled when not editable" | unit |
| 4 | `web/components/items/source-tag.test.ts` :: "SOURCE_TAG and sourceTone map both→A+B ok, A and B muted, human accent" | unit |
| 4 | `web/e2e/exceptions-workbench.spec.ts` :: "detail shows header, lock banner, why it's stuck tiles, auto-fix timeline, lines, receipt selector and actions" (board: sheet) | browser |
| 4 | `web/e2e/exceptions-workbench.spec.ts` :: "Requeue posts /items/{id}/requeue and Unlock sends DELETE /items/{id}/lock exactly as before" | browser |
| 5 | `web/components/exceptions/empty-states.test.tsx` :: "NoExceptions shows the board empty copy; NoMatches links to clear filters" | unit |
| 5 | `web/components/exceptions/lock-conflict-card.test.tsx` :: "shows '<name> locked this item first' and View read-only dismisses to the read-only detail" | unit |
| 5 | `web/e2e/exceptions-workbench.spec.ts` :: "loading shows row skeletons while the list is slow" (mock `delayMs`; board: Loading) | browser |
| 5 | `web/e2e/exceptions-workbench.spec.ts` :: "empty list shows No exceptions right now" (board: Empty) | browser |
| 5 | `web/e2e/exceptions-workbench.spec.ts` :: "an item locked by someone else shows the lock conflict card and View read-only" (board: Error) | browser |
| 6 | `web/components/flow/stage-tile.test.tsx` :: "renders a station card with mono name, err pill for errors and mono in-queue count" | unit |
| 6 | `web/components/flow/backlog-bar.test.tsx` :: "renders a 5px Meter with processed/total and keeps Pause" | unit |
| 6 | `web/e2e/flow-items-restyle.spec.ts` :: "/flow shows glass station cards and the backlog meter" | browser |
| 6 | `web/e2e/flow-items-restyle.spec.ts` :: "/flow/[stage] renders the items table in a glass panel" | browser |
| 6 | `web/e2e/flow-items-restyle.spec.ts` :: "/items/[id] renders glass panes, pills and the restyled history timeline" | browser |
| 6 | `web/e2e/flow-items-restyle.spec.ts` :: "no horizontal page scroll at 375 px on /exceptions, /flow, /flow/[stage] and /items/[id]" (`scrollWidth <= clientWidth`) | browser |
| 7 | `web/tests/no-colour-literals.test.ts` :: "components/exceptions, flow and items contain no hex colours and no style= colour literals" (globs `**/*.{ts,tsx}`, regex `#[0-9a-fA-F]{3,8}\b` and `style=\{\{[^}]*(color\|background\|border)`) | unit |
| 8 | full `cd web && npx vitest run` + `npx playwright test`; `cd api && uv run pytest` :: "existing suites pass" (no existing web test covers these files today: `git ls-files` shows none, so only selectors in the new specs above apply) | unit + browser |

Totals: 22 unit, 13 browser, 1 regression run. Files: 12 created, 37 changed (49).

## 4. Data

None. No ORM model, no Alembic revision (this story isn't in split.md's migration list). Every read uses the existing `GET /exceptions`, `/items/{id}`, `/items/{id}/history`, `/items/{id}/fusion-context`, `/me` and `/flow/*`.

## 5. Config and env

None new. No env variable and no DB-stored settings key. Breakpoint 1024 and chip definitions are UI constants (design.md §7). The "Sample data" pill and the env come from `TopBar` (glass-theme-shell, `/me` `env`/`sample_data`).

## 6. Risks and gates

- **Dep timing:** `TopBar`, `GlassPanel`, `Pill`, `FilterChip`, `Meter`, `StateCard`, `SkeletonRows`, `MonoLabel`, the `DataTable` selected-row prop and the token utilities come from glass-theme-shell. The coder starts from the sprint tip after its wip branch is merged, or merges its pushed wip branch. The coder never stubs them at the owner's paths (lesson L-comparison-wizard-from-fusion-2). If the owner's plan pins different prop names than §7a, the owner's plan wins and the coder adapts the call sites.
- **Shared-file overlap:** `common/lock-banner.tsx` and `common/history-timeline.tsx` are restyled here (design.md §3.4 lists them for this screen), not by glass-theme-shell, whose ACs don't touch them. `common/status-badge.tsx` and `data-table.tsx` belong to glass-theme-shell and are only consumed here. `hooks/use-media-query.ts` is new. If glass-theme-shell lands an equivalent hook first, use that one and drop this file (DRY).
- **Chat:** `flow-monitor.tsx` and `item-view.tsx` render `LlmChat`, which assistant-chat-redesign owns. These call sites are left as they are, and any prop change there is that story's merge.
- **Chip count cost:** 8 extra `page_size=1` calls per render. They're parallel and cached per query string. Acceptable for an operator screen. A facets endpoint would be a later API story (out of scope: no API change).
- **Sheet/aside switch:** switching remounts the body on resize, and an unsaved line edit is lost when the viewport crosses 1024 px. The server snapshot is desktop, so phones briefly paint inline before the sheet. Acceptable for this story.
- **`queries.ts` imports `server-only`:** the unit test mocks `server-only` (`vi.mock("server-only", () => ({}))`).
- **Coder gates (no tests):** `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`. The API is untouched, so there's no API gate. Run `npm ci` in `web/` first in a fresh worktree.

Next.js rules applied: nextjs.md NN-1, NN-7, NN-14; TS-1, TS-5, TS-10, TS-13, TS-16, TS-17, TS-19; RT-6, RT-8, RT-22, RT-26, RT-27, RT-28; RC-5, RC-6, RC-7, RC-8, RC-38, RC-44; DF-4, DF-6, DF-8, DF-22; TEST-1, TEST-2, TEST-12, TEST-14, TEST-18, TEST-20, TEST-21, TEST-37. nextjs-fullstack-standards: shadcn primitives from the CLI only (`checkbox`), Zod at the URL boundary (the existing `exceptionFiltersSchema`), Result values across the boundary, `"use client"` on leaves.

## 7. Interfaces

### 7a. Consumed from glass-theme-shell (same wave). Must match its plan.

```ts
// components/common/*
GlassPanel(props: { className?: string; children: ReactNode } & ComponentProps<"section">)
PanelHeader(props: { title?: ReactNode; children?: ReactNode; className?: string })
PanelBody(props: { children: ReactNode; className?: string })
type PillTone = "ok" | "accent" | "warn" | "err" | "locked" | "muted"
Pill(props: { tone: PillTone; dot?: boolean; mono?: boolean; className?: string; children: ReactNode })
MonoLabel(props: { children: ReactNode; className?: string })
FilterChip(props: { active: boolean; onClick?: () => void; disabled?: boolean; children: ReactNode }) // <button aria-pressed>
Meter(props: { value: number; max: number; tone?: "accent" | "ok" | "warn" | "err"; size?: 5 | 6; label: string })
StateCard(props: { kind: "loading" | "empty" | "error" | "denied"; label: string; headline: string; body?: ReactNode; actions?: ReactNode })
SkeletonRows(props: { rows: number; caption?: string })
DataTable: existing props + selectedRowId?: string  // row gets data-selected="true" and the selected tint
StatusBadge: unchanged ({ kind, value })
// components/shell/top-bar.tsx
TopBar(props: { title: string; children?: ReactNode })  // children = right-slot page controls; env, Live and Sample data pills rendered by TopBar itself
```

Token utilities used: `bg-surface-1/2/3`, `border-line`, `border-line-strong`, `text-faint`, `text-brand-ink`, `bg-brand-soft`, `ring-brand-hi`, `bg-ok-soft text-ok-ink`, `bg-warn`, `bg-err`, `text-err-ink`, `shadow-float`, `font-mono`, and locked-tone utilities (`text-status-locked`, `bg-status-locked/10`).

### 7b. Provided by this story

No story in split.md lists exceptions-workbench-restyle in its deps, so this story has no consumers and nothing to pin for another wave. These internal contracts are recorded for chat-agent-tool-registry, in case its exceptions tools ever link into the workbench:

```ts
// components/exceptions/filter-chips.ts
type ChipId = "all" | "ambiguous" | "variance" | "invoice" | "customer" | "person" | "locked"
EXCEPTION_CHIPS: readonly { id: ChipId; label: string; codes: readonly ErrorCode[]; lockedByMe: boolean }[]
//  all:[] · ambiguous:[RECEIPT_AMBIGUOUS] · variance:[AMOUNT_VARIANCE] · invoice:[INVOICE_NOT_FOUND]
//  customer:[CUSTOMER_NOT_FOUND] · person:[PREPAYMENT, PO_SO_ERS_ONLY, DUAL_CURRENCY, UNGROUNDED] · locked:[] + lockedByMe
activeChip(f: ExceptionFilters): ChipId | null
chipFilters(f: ExceptionFilters, id: ChipId): ExceptionFilters
// app/(shell)/exceptions/_lib/queries.ts
getExceptionCounts(f: ExceptionFilters): Promise<{ chips: Partial<Record<ChipId, number>>; appliedHidden: number | null }>
// Deep link into the workbench (unchanged): /exceptions?item=WI-<id>[&error_codes=…][&locked_by_me=1]
```

## Assumptions

- **Payer masking.** No masking rule exists in `web/` or the API today. The board's `[Payer 0142]` is sample data. Payer shows `payer_name` exactly as today ("keeps the existing rule").
- **Locked chip.** The API has only a `locked_by_me` filter, and adding one is out of scope ("no API changes"). So the "Locked" chip uses that filter, and its count is the items locked by the viewer.
- **Chip code groups.** Invoice not found = `INVOICE_NOT_FOUND`. Customer not found = `CUSTOMER_NOT_FOUND`. Always a person = `PREPAYMENT`, `PO_SO_ERS_ONLY`, `DUAL_CURRENCY`, `UNGROUNDED` (CLAUDE.md "Always a person"). Chip counts respect every other active filter.
- **Removed controls.** The filter bar's "Locked by me" and "Include auto-applied" switches are removed because the chip and the top-bar checkbox replace them (DRY). The URL parameters are unchanged.
- **Columns.** The list drops the Payment date and Auto-fixes columns to match the board. Both still appear in the detail.
- **Full history.** The inline "Full history" collapsible becomes a link to `/items/WI-n`, which stays the full-history page (design.md §3.4).
- **Requeue label.** It reads "Requeue to match receipt" only when a receipt is chosen or the code is `RECEIPT_AMBIGUOUS`; otherwise "Requeue". The API decides the target stage, as today.
- **Lock conflict.** It's rendered for the `other` lock view. The existing `lock_conflict` toast on a failed dequeue stays.
- **AC 8.** No existing web unit or E2E test covers these components (`git ls-files` finds none). AC 8 is met by the full suites passing, with the new specs written against the new markup.
