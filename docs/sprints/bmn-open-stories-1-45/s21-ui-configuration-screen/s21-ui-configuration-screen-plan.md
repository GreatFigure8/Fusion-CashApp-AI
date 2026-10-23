# s21-ui-configuration-screen: plan

Issue #21. Wave 5. Web only: no API, no migration. Owns `web/app/(shell)/config/**` and `web/components/config/**`, plus the new test files listed below. Design: design.md §6 (and §1 "read-only admins see values greyed with 'Admin role required to edit'").

## Standards followed

- **CLAUDE.md**
  - Thin client: every read and write goes through s31's `api()` / `apiAction()`. The API enforces `config:read` / `config:write`. The UI only hides.
  - No business rules in web. Validation that the API also does (the Fable rule, types, ranges) is mirrored in Zod only for fast feedback. The API's 422 is still shown inline.
  - Money and tolerances are decimal **strings** end to end (never `Number`), shown with their currency code.
  - DRY: one generic `SettingsPanel` renders every tab's registry rows. One `SettingRow` renders every row. One history `Sheet` serves every key and the group-role map. One staging store and one review dialog serve every tab, Access included.
  - Shared components come from s19's `web/components/common/` (`data-table`, `error-alert`, `empty-state`) and are never copied.
- **nextjs-fullstack-standards:** strict TS, no `any`, Zod at the action boundary, `Result` values across layers, Server Components by default with `"use client"` only on interactive leaves, named exports, kebab-case files, shadcn primitives from `components/ui/`, no hand-rolled primitives.
- **BMN `references/nextjs.md` rule ids applied:**
  - NN1/RC-13/RC-16: `searchParams` awaited in the page.
  - NN3: every Server Action reaches the API with the user's token through `api()`, and the API authorizes.
  - NN4: no `route.ts` in the config segment.
  - NN7/TS: `PageProps<"/config">`.
  - RC-5/RC-6/RC-7/RC-8: server panels, client leaves. The history sheet's content is server-rendered and passed as `children`.
  - RC-9: the staging provider wraps only the panel area.
  - RC-12: loaders and save functions are `server-only`.
  - RC-36: `refresh()` after a write, because the data is uncached.
  - RC-38/RC-44: data requests start together in `Promise.all`, and the tab panel sits in its own `<Suspense key={tab}>`.
  - DF-1, DF-10: no Server Function is used to fetch. History is URL-driven (`?history=<key>`) and rendered on the server.
  - DF-13: action input is Zod-parsed.
  - DF-14/TEST-18: per-key results come back as typed values.
  - DF-15: actions return DTOs only.
  - TS-20: types come from `z.infer` and from generated `Schemas`.
  - TEST-1/TEST-2: async Server Components are covered by Playwright. Client components and pure logic are covered by Vitest.
  - TEST-10: action logic lives in plain functions.
  - TEST-14: role- and label-based locators.
  - TEST-17/TEST-19/TEST-21: `error.tsx` with a generic message, and the error path is E2E-tested.
  - TEST-23: `notFound()`/`redirect()` are never called inside a `try`.
  - TEST-25: dialog submit errors are kept in state.
- **python-web-app:designing-interaction-states / building-accessible-interfaces** (via design.md): every tab has loading, error and empty states. Inputs have labels, `aria-invalid` and `aria-describedby` for inline errors. Dialogs trap focus (shadcn). The sticky footer uses `role="region"` with `aria-label="Unsaved changes"`.

## Files to touch (all new)

### Route (`web/app/(shell)/config/`)

| Path | Purpose |
|---|---|
| `page.tsx` | Async Server Component.<br>1. Awaits `searchParams` (`tab`, `history`, `aq`, `apage`) and validates them with Zod. An unknown tab falls back to `access`.<br>2. Loads `/me`. Without `config:read`, it renders s19's unauthorized state for role `ADMIN` and does nothing else.<br>3. Renders `ConfigTabs`, `<ConfigStagingProvider canEdit>`, `<Suspense key={tab} fallback={<ConfigTabSkeleton tab/>}>`, the tab panel, `SaveFooter` and, when `history` is set, `<HistorySheet>` wrapping the server-rendered `<HistoryList>`. |
| `loading.tsx` | Route-level skeleton: the tab rail plus `ConfigTabSkeleton`. |
| `error.tsx` | `"use client"`. Generic message plus `error.digest`, with a Retry button calling `reset()` (TEST-19/TEST-21). Expected API errors never reach it; they render through `error-alert`. |
| `actions.ts` | `"use server"`: `saveConfigChanges`, `retireAlias`, `runRetentionPurgeDryRun`. Each is `apiAction(schema, fn)` and delegates to `_lib/save-config.ts`. Each calls `refresh()` (from `next/cache`) after any successful write. |
| `_lib/load-config.ts` | `import "server-only"`. Loaders: `loadMe`, `loadConfigEntries`, `loadGroupRoles`, `loadAliases`, `loadHistory`, all returning `Result`. `loadMe` reuses s19's `/me` helper if one exists (see Assumptions). |
| `_lib/save-config.ts` | `import "server-only"`. Plain functions: `saveStagedChanges`, `retireAliasCall`, `purgeDryRunCall` (TEST-10). They take an injected `put`/`post` (defaulting to `api`) so unit tests can run them under msw. |

### Components (`web/components/config/`)

| Path | Purpose |
|---|---|
| `config-registry.ts` | Pure. `CONFIG_TABS` (id, label, order), plus `CONFIG_UI` mapping each config key to `{tab, label, unit?, editor, order}`. Also `tabForKey(key)` and `uiFor(entry)`. A key that isn't in the registry falls back to `{tab: "retries", editor: "json", label: key}` under an "Other settings" heading, so no API key is ever unreachable. |
| `config-schemas.ts` | Pure Zod, client-safe. Defines `decimalString`, `intervalSeconds`, `positiveInt`, `nullableDays`, `confidence`, `modelRoleSchema` (with the Fable refine and the exact message), `tolerancesSchema` (currency code `^[A-Z]{3}$` or `*`, unique), `bankFeeBandsSchema` (min ≤ max), `backoffSchema`, `maxAttemptsSchema`, `groupRolesSchema` (at least one ADMIN), `reasonSchema` (trim, 1..1000), and `schemaForEditor(editor)`. |
| `staging.ts` | Pure reducer and selectors: `StagingState`, `stagingReducer`, `stagedCount`, `stagedDiff`, `applySaveResults`, `fieldErrorsFromLoc`. |
| `value-format.ts` | Pure: `formatConfigValue(editor, value, unit)`, used by rows, the review dialog and history ("Keep indefinitely" for null retention, `±0.10 USD`, `300 s`). Also `formatRelative(date, now)`, unless s19 ships one in `common/` (see Assumptions). |
| `config-staging-provider.tsx` | `"use client"`. Context with `useReducer(stagingReducer)` and `canEdit`. Exposes `useStaging()`. Wraps the panel area only (RC-9). |
| `config-tabs.tsx` | Server. Vertical `<nav aria-label="Configuration sections">` of `Link`s (`?tab=`), with `aria-current="page"` on the active one. Below 1024px it becomes a horizontally scrolling row inside its card (design §10). |
| `config-tab-skeleton.tsx` | Server. Per-tab skeleton (rows or a table) from shadcn `Skeleton` (AC9). |
| `settings-panel.tsx` | Server. Takes `entries: ConfigEntry[]` and `tab`, and renders the tab's `SettingRow`s in registry order. One copy serves Polling, Matching, Retries & aging, Models and Retention. |
| `setting-row.tsx` | `"use client"`. Shows label, API description, the editor chosen by `editor`, unit, a "Modified" dot when staged, inline field errors, and `ChangedByLink`. Read-only (`disabled`, greyed) when `!canEdit`. |
| `changed-by-link.tsx` | `"use client"`. "Changed by {updated_by_name} {relative}", or "Default value" when version 0. It links to the current URL with `history=<key>` added, keeping the other params (`useSearchParams`, `scroll={false}`). |
| `history-sheet.tsx` | `"use client"`. shadcn `Sheet`, opened while `history` is in the URL. Closing it calls `router.replace` without `history`. Its content comes as `children` (RC-8). |
| `history-list.tsx` | Server. Renders `ConfigChangeOut[]`: who (`changed_by_name`), when (absolute plus relative), old → new through `formatConfigValue`, and reason. Uses `empty-state` ("No changes yet. This setting has its default value.") and `error-alert`. |
| `editors/number-editor.tsx` | int or float input with unit (intervals, days, attempts, timeouts, confidence). |
| `editors/nullable-days-editor.tsx` | Number plus a "Keep indefinitely" switch. Null renders as "Keep indefinitely" (AC7). |
| `editors/tolerance-table.tsx` | Currency rows (`USD ±0.10` …), Add currency, Remove. The `*` row is labelled "All other currencies" and can't be removed. |
| `editors/bank-fee-bands-editor.tsx` | Rows of currency, min fee and max fee, with add and remove. |
| `editors/backoff-list-editor.tsx` | Ordered list of seconds, with add and remove. |
| `editors/max-attempts-editor.tsx` | Rows of error code (select from the generated `ErrorCode` enum, plus `*`) and attempts. |
| `editors/model-role-editor.tsx` | One row per role (Reader A, Reader B, Adjudicator, Workhorse).<br>- Model ID: `Select` of `KNOWN_MODEL_IDS` (`claude-opus-5-5`, `claude-haiku-5-5`, `cohere.command-a-vision`) plus the current value, plus "Other…" which reveals a text `Input`.<br>- Effort: `Select` of low/medium/high/max/none.<br>- Timeout in seconds.<br>The fixed note "Claude Fable models are not allowed (zero data retention)." sits above the rows. |
| `editors/json-editor.tsx` | Fallback textarea for unmapped keys. JSON-parsed client-side, value checked by the API. |
| `editors/switch-editor.tsx`, `editors/text-editor.tsx` | Boolean (`discount.enabled`) and string (`reports.daily_summary_cutover`, `^\d{2}:\d{2}$`). |
| `access-panel.tsx` | Server wrapper. Fetches nothing itself; it receives the group-roles DTO and renders `GroupRoleEditor` plus `ChangedByLink` keyed `access.group_role_map`. |
| `editors/group-role-editor.tsx` | `"use client"`. Table of group name `Input` and role `Select` (generated `Role` enum), with add and remove rows. It stages into the same store under the synthetic key `access.group_role_map`. |
| `aliases-panel.tsx` | Server. Search box (`aq`) plus s19 `data-table` with columns: alias text (mono), kind, maps to customer, learned from (`WI-{id}` → `/items/{id}`), uses, last used. Server paging (`apage`, 50 a page). `empty-state` "No active payer aliases." Retire column only when `canEdit`. |
| `retire-alias-dialog.tsx` | `"use client"`. `AlertDialog`: "Retire alias '{alias_text}'? It will no longer be used to match payers." Requires a Reason, then calls `retireAlias`. Errors stay in the dialog (TEST-25). |
| `retention-panel.tsx` | Server. `SettingsPanel tab="retention"` plus `PurgeDryRun` when `canEdit`. |
| `purge-dry-run.tsx` | `"use client"`. Button "Run purge (dry run)". The `PurgeReportResponse` renders as a definition list (artifacts, parts, readings, adjudications, history payloads, objects deleted / kept shared, resumed, skipped, ran at), or `error-alert`. |
| `save-footer.tsx` | `"use client"`. Sticky bottom bar.<br>- Admin with changes: "{n} unsaved change(s) · Discard · Review & save".<br>- Admin with no changes: hidden.<br>- Non-admin: "Admin role required to edit". |
| `review-dialog.tsx` | `"use client"`. `Dialog` listing each staged key as `label: old → new` and a required Reason `Textarea` (`reasonSchema`).<br>Submit calls `saveConfigChanges` and then shows per-key results: ✓ saved; ✗ invalid (field errors are also pushed inline onto the rows); 409 "This setting was changed by someone else since you opened it." with a **Reload** button that unstages that key and calls `router.refresh()`.<br>Saved keys leave staging. The dialog closes automatically when every key saved. |

### Tests (written and run at step 5 only)

| Path | Purpose |
|---|---|
| `web/tests/support/fixtures/config-dto.ts` | Owned builders, typed from `Schemas`: `makeConfigEntry`, `makeAllConfigEntries()` (every s02 registry key with s02 defaults), `makeConfigChange`, `makeGroupRoles`, `makeAlias`, `makeAliasPage`, `makePurgeReport`. A separate file from s19's `dto.ts` keeps the stories file-disjoint. |
| `web/tests/unit/config/*.test.ts(x)` | Vitest, listed in the TEST PLAN. |
| `web/e2e/config.spec.ts` | Playwright, listed in the TEST PLAN. |

Not touched: `web/components/common/*` (s19), `web/components/ui/*` (CLI), `web/lib/api/*` (s31), `web/lib/auth/*` (s04), the shell layout and nav (s19), any API file, `web/lib/api/openapi.json`/`schema.d.ts` (no route changes), `package.json`, `playwright.config.ts` (unless the s19 stub fallback in Risks applies).

## Design notes

**Tab → keys** (`CONFIG_UI`, pinned; keys are s02 registry names):

| Tab (`?tab=`) | Keys (editor) |
|---|---|
| `access` | `access.group_role_map` (group-roles, via `/access/group-roles`) |
| `polling` | `intake.poll_interval_seconds` (number, s), `receipt_watcher.poll_interval_seconds` (number, s) |
| `matching` | `matching.date_window_days` (number, ± days), `matching.tolerances` (tolerance-table), `matching.bank_fee_bands` (bank-fee-bands), `matching.min_score` (number), `matching.scorer_weights` (json), `discount.enabled` (switch) |
| `retries` | `retries.max_attempts` (max-attempts), `retries.backoff_seconds` (backoff-list), `aging.awaiting_receipt_max_days` (number, days), `escalation.min_extraction_confidence` (number 0–1), `extraction.fanin_timeout_seconds` (number, s), then "Other settings": `concurrency.per_stage` (json), `concurrency.apply_per_receipt`, `locks.lease_minutes`, `backlog.rate_limit_per_minute` (number), `notifications.recipients` (json), `notifications.batch_window_seconds` (number), `reports.daily_summary_cutover` (text) |
| `models` | `models.reader_a`, `models.reader_b`, `models.adjudicator`, `models.workhorse` (model-role), `budget.daily_usd` (decimal string or null, USD) |
| `retention` | `retention.raw_artifact_days`, `retention.extraction_days`, `retention.history_payload_days` (nullable-days) + purge dry run |
| `aliases` | `GET /aliases` table |

The registry key `receipt_watcher.poll_interval_seconds` is the coder's best reading of s02's constant `RECEIPT_WATCHER_POLL_INTERVAL_SECONDS`. The coder confirms each key against `GET /config` (the generated OpenAPI has no key enum). Any key the registry misses still renders through the fallback.

**Data flow.** `page.tsx` runs `Promise.all([loadMe(), loadConfigEntries(), tab-specific loads])`.
- Access: `loadGroupRoles()` plus `GET /access/group-roles/history?limit=1` for the changer's display name.
- Aliases: `loadAliases({q, offset})`.
- `history` param set: `loadHistory(key)`, which uses `/access/group-roles/history` when the key is `access.group_role_map`.

Each `Result` error renders `<ErrorAlert error={…}>` in place of the panel (AC9). An error from `/config` replaces every setting panel. An error from aliases replaces only the table.

**Staging** (`StagingState = { base: Record<key, {value, version}>, staged: Record<key, unknown>, errors: Record<key, FieldError[]>, conflicts: Set<key> }`):
- `stage(key, value)` removes the entry when the value deep-equals the base, so typing back to the original isn't a change.
- `discard()` clears everything.
- `rebase(entries)` runs when the server re-renders after `refresh()`, and updates base values and versions for unstaged keys only.
- Staged values survive tab switches, because the provider sits outside the `Suspense key={tab}` boundary and the same component instance persists across soft navigation.
- **Save is per key** (story assumption): `saveStagedChanges` runs the PUTs **sequentially**, in registry order, so the results are deterministic. The group-role map goes last. Each key's result is independent.

**Error mapping** (from s28 and s37):

| API response | Shown as |
|---|---|
| 409 `config_conflict` | conflict result with the exact message from AC2 |
| 422 `invalid_config_value` | `loc` becomes inline errors via `fieldErrorsFromLoc`: drop the leading `body`/`value` segments, then the remaining path addresses the field inside the editor (for example `["model_id"]`, or `[2, "max_fee"]` for a band row) |
| 422 framework `validation_error` (blank reason) | prevented client-side; shown as a dialog error if it happens |
| 422 `last_admin_mapping` | the API `message` verbatim in the dialog and inline on the Access table (AC5) |
| 403 | `error-alert` in the dialog |
| network | `error-alert` in the dialog |

## Interfaces provided (pinned)

```ts
// web/components/config/config-registry.ts
export type ConfigTabId = "access" | "polling" | "matching" | "retries" | "models" | "retention" | "aliases";
export type EditorKind = "number" | "nullable-days" | "tolerance-table" | "bank-fee-bands" | "backoff-list"
  | "max-attempts" | "model-role" | "group-roles" | "switch" | "text" | "decimal-nullable" | "json";
export type ConfigUi = Readonly<{ tab: ConfigTabId; label: string; unit?: string; editor: EditorKind; order: number; section?: "main" | "other" }>;
export const CONFIG_TABS: readonly { id: ConfigTabId; label: string }[];   // design §6 order
export const CONFIG_UI: Readonly<Record<string, ConfigUi>>;
export const GROUP_ROLE_KEY = "access.group_role_map";
export function uiFor(key: string): ConfigUi;                                // fallback for unknown keys
export function keysForTab(entries: readonly Schemas["ConfigEntry"][], tab: ConfigTabId): Schemas["ConfigEntry"][];

// web/components/config/config-schemas.ts
export const FABLE_MESSAGE = "Claude Fable models are not allowed (zero data retention).";
export const modelRoleSchema: z.ZodType<{ model_id: string; effort: "low"|"medium"|"high"|"max"|null; timeout_s: number }>;
export const reasonSchema: z.ZodString;                                       // trim, 1..1000
export function schemaForEditor(editor: EditorKind): z.ZodType;

// web/components/config/staging.ts
export type FieldError = Readonly<{ path: string; message: string }>;
export type KeyResult =
  | { key: string; outcome: "saved"; version: number }
  | { key: string; outcome: "conflict"; currentVersion: number | null; message: string }
  | { key: string; outcome: "invalid"; fieldErrors: FieldError[]; message: string }
  | { key: string; outcome: "failed"; error: ApiError };
export function fieldErrorsFromLoc(details: ApiError["details"]): FieldError[];

// web/app/(shell)/config/actions.ts  ("use server"; all via apiAction(schema, fn))
export const saveConfigChanges: (input: unknown) => Promise<Result<{ results: KeyResult[] }, ApiError>>;
//   input: { reason: string; changes: { key: string; value: JsonValue; expected_version: number }[];
//            groupRoles?: { mappings: { group_name: string; role: Role }[] } }  (changes may be empty when groupRoles is set; at least one of them)
export const retireAlias: (input: unknown) => Promise<Result<Schemas["AliasOut"], ApiError>>;      // { aliasId: number; reason: string }
export const runRetentionPurgeDryRun: (input: unknown) => Promise<Result<Schemas["PurgeReportResponse"], ApiError>>; // {}; always sends {dry_run: true}

// web/tests/support/fixtures/config-dto.ts
export function makeConfigEntry(o?: Partial<Schemas["ConfigEntry"]>): Schemas["ConfigEntry"];
export function makeAllConfigEntries(): Schemas["ConfigEntry"][];
export function makeConfigChange(o?: Partial<Schemas["ConfigChangeOut"]>): Schemas["ConfigChangeOut"];
export function makeGroupRoles(o?: Partial<Schemas["GroupRolesOut"]>): Schemas["GroupRolesOut"];
export function makeAlias(o?: Partial<Schemas["AliasOut"]>): Schemas["AliasOut"];
export function makePurgeReport(o?: Partial<Schemas["PurgeReportResponse"]>): Schemas["PurgeReportResponse"];
```

Schema component names (`ConfigEntry`, `ConfigChangeOut`, `GroupRolesOut`, `AliasOut`, `PurgeReportResponse`) follow s28, s37 and s45's Pydantic class names. If the generated names differ, the coder uses `ResponseOf<path, method>` instead. No consumer other than this story is expected. `runRetentionPurgeDryRun` deliberately can't send `dry_run: false`; a real purge isn't in scope.

## Migrations

None. Web only. No Alembic revision, so the head is unchanged.

## TEST PLAN (written and run at step 5 only)

Unit tests run in Vitest/jsdom unless noted. `save-config` tests run with `// @vitest-environment node`, `vi.mock("server-only")`, s31's `useApiMockServer`/`mockApi`/`mockApiError` and `sessionModuleMock()`. E2E runs in Playwright against the production build, with s04's `withSession` and the API stub (see Assumptions 3).

| AC | Test | Asserts |
|---|---|---|
| 1 | `web/e2e/config.spec.ts` › `admin sees the seven tabs in design order and each setting row` | Vertical nav: Access, Polling, Matching, Retries & aging, Models, Retention, Payer aliases. A Polling row shows label, API description, value input, unit "s" and "Changed by J. Stevenson 3 days ago". |
| 1 | › `changed-by link opens the history sheet with who, when, old → new and reason` | Clicking the link puts `?history=intake.poll_interval_seconds` in the URL. The sheet lists rows newest first. Closing it removes the param and keeps other params. |
| 1 | `web/tests/unit/config/config-registry.test.ts` › `every registry key from GET /config renders on exactly one tab` | `makeAllConfigEntries()` → every key maps to one tab. An unknown key falls back to retries/other/json. |
| 1 | `web/tests/unit/config/setting-row.test.tsx` › `renders label, description, unit, changed-by text and default state` | Version 0 shows "Default value". Relative time comes from an injected `now`. |
| 1 | `web/tests/unit/config/value-format.test.ts` › `formats tolerances, seconds, nulls and model roles for history and review` | `±0.10 USD`, `300 s`, "Keep indefinitely", `claude-opus-5-5 · high · 120 s`. |
| 2 | `web/tests/unit/config/staging.test.ts` › `stage, unstage-on-equal, discard, count and diff` | Counts and diff old → new. Re-entering the original value unstages it. |
| 2 | › `rebase keeps staged values and refreshes unstaged versions` | |
| 2 | › `applySaveResults clears saved keys, keeps invalid with field errors and marks conflicts` | |
| 2 | › `fieldErrorsFromLoc strips body/value and maps nested paths` | `["body","value","model_id"]` becomes `model_id`. `["body","value",2,"max_fee"]` becomes `2.max_fee`. |
| 2 | `web/tests/unit/config/save-config.test.ts` › `sends one PUT per changed key with value, reason and expected_version in registry order` | msw records N requests whose bodies equal `{value, reason, expected_version}`. The group-role PUT comes last. |
| 2 | › `maps 200, 409 config_conflict and 422 invalid_config_value to per-key results` | One key saved, one conflict (`currentVersion` from details) and one invalid (field errors). Later keys still run. |
| 2 | › `network failure on one key yields failed for that key only` | |
| 2 | `web/tests/unit/config/save-footer.test.tsx` › `shows "3 unsaved changes · Discard · Review & save" and Discard clears staging` | Hidden when there are 0 changes. Singular "1 unsaved change". |
| 2 | `web/tests/unit/config/review-dialog.test.tsx` › `lists old → new per key and requires a reason` | Submit is disabled or errors with an empty or whitespace reason. The action is not called. |
| 2 | › `shows per-key results, inline 422 errors and the 409 conflict message with Reload` | Mocked action (TEST-10 split). Reload unstages the key and calls `router.refresh`. |
| 2 | `web/e2e/config.spec.ts` › `edit two settings, review, save with reason; stale version shows the conflict message` | Stub returns 200 for one key and 409 for the other. The footer then shows "1 unsaved change". The conflict text matches AC2 exactly. |
| 3 | `web/tests/unit/config/tolerance-table.test.tsx` › `renders USD ±0.10, EUR ±0.10, INR ±0.49 and adds a currency` | Values stay decimal strings (no float). A duplicate or invalid currency gives an inline error. The `*` row can't be removed. |
| 3 | `web/tests/unit/config/config-schemas.test.ts` › `tolerances, bank-fee bands, backoff, max attempts, intervals and confidence validate` | min > max is rejected, as are negative or zero intervals, confidence > 1 and a non-integer backoff. |
| 3 | `web/e2e/config.spec.ts` › `Matching, Polling and Retries & aging tabs show their settings` | Date window, tolerance rows and bank-fee bands on Matching. Both intervals on Polling. Max attempts per code, backoff list, aging days, min confidence and fan-in timeout on Retries & aging. |
| 4 | `web/tests/unit/config/config-schemas.test.ts` › `modelRoleSchema rejects any id containing fable, case-insensitive, with FABLE_MESSAGE` | |
| 4 | `web/tests/unit/config/model-role-editor.test.tsx` › `four role rows with model select, effort select, timeout and the fixed Fable note` | "Other…" reveals the text input. Typing `claude-fable-1` shows the inline error and doesn't stage the change. |
| 4 | `web/e2e/config.spec.ts` › `server 422 for a model id is shown inline on the Models tab` | Stub returns 422 `invalid_config_value` with loc `["body","value","model_id"]`. The message shows under that role's model field. |
| 5 | `web/tests/unit/config/group-role-editor.test.tsx` › `edit, add and remove group → role rows and stage access.group_role_map` | |
| 5 | `web/tests/unit/config/save-config.test.ts` › `group roles PUT sends mappings and reason; 422 last_admin_mapping returns the API message` | |
| 5 | `web/e2e/config.spec.ts` › `removing the last admin mapping shows the API's 422 message` | |
| 6 | `web/e2e/config.spec.ts` › `aliases table lists active aliases with WI link; retire with reason removes it` | Columns are present. "WI-881" links to `/items/881`. The confirm dialog requires a reason. After `POST /aliases/{id}/retire` the stub's next `GET /aliases` excludes the alias and the row is gone. |
| 6 | `web/tests/unit/config/retire-alias-dialog.test.tsx` › `requires reason, calls retireAlias, keeps errors in the dialog` | |
| 6 | `web/tests/unit/config/save-config.test.ts` › `retireAliasCall posts reason to /aliases/{id}/retire` | |
| 7 | `web/tests/unit/config/nullable-days-editor.test.tsx` › `null renders "Keep indefinitely" and toggling restores a number` | |
| 7 | `web/tests/unit/config/purge-dry-run.test.tsx` › `button calls the action and renders every report count` | |
| 7 | `web/tests/unit/config/save-config.test.ts` › `purgeDryRunCall always sends {dry_run:true}` | |
| 7 | `web/e2e/config.spec.ts` › `Retention tab shows retention keys and a dry-run report` | |
| 8 | `web/e2e/config.spec.ts` › `config:read-only user sees greyed values and "Admin role required to edit"` | Session with `/me` permissions `[config:read]`. Inputs are disabled. No Review & save, Retire or Run purge. |
| 8 | › `user without config:read gets the unauthorized state` | VIEWER sees "You don't have access to this page. Ask an administrator for the ADMIN role." |
| 8 | `web/tests/unit/config/setting-row.test.tsx` › `canEdit=false disables the editor` | |
| 9 | `web/e2e/config.spec.ts` › `slow tab shows its skeleton, then content` | The stub delays `/aliases`. Skeleton test id `config-tab-skeleton`. |
| 9 | › `API error renders error-alert with request id` | The stub returns 503 for `/config`. The alert shows status and request id. Other tabs' navigation still works. |
| 9 | › `unexpected render error shows error.tsx with Retry` (TEST-17) | |

## Assumptions and deviations

1. **The s19 interfaces aren't pinned yet** (no plan at planning time). The coder uses whatever s19 ships under these names, or the closest equivalent:
   - `ErrorAlert({error: ApiError, title?, onRetry?})`, `EmptyState`, `DataTable` from `web/components/common/`;
   - the unauthorized state component from `web/components/shell/`;
   - a cached `/me` loader.

   If s19 ships no `/me` loader, `_lib/load-config.ts` calls `api("get", "/me")` wrapped in React `cache`. If s19 ships a relative-time formatter in `common/`, `value-format.ts` uses it and doesn't define its own (DRY).
2. **History is URL-driven** (`?history=<key>`), rendered on the server (DF-10: no Server Function fetch) and linkable.
3. **E2E API stub.** The Next server calls the API on the server side, so Playwright's `page.route` can't intercept it.
   - The spec uses s19's E2E API stub if s19 adds one: a programmable fake at `API_BASE_URL`.
   - If s19 adds none, this story adds `web/e2e/support/api-stub.ts`, a Node `http` server on `PLAYWRIGHT_API_STUB_PORT` programmed through `POST /__stub/routes` and reset per test. It also adds one entry to the `webServer` array in `playwright.config.ts`, plus `API_BASE_URL` for the Next server (an s01 file edit, flagged in Risks).
4. **Access is staged with the other settings** under the synthetic key `access.group_role_map`, sharing the footer, the review dialog and the reason. Its PUT has no `expected_version` (s28: last writer wins).
5. **Alias retire and the purge dry run are immediate actions**, each with its own confirmation or button, and are not staged. Both are hidden without `config:write`, because the API requires it for both.
6. **Registry keys beyond AC3** (concurrency, locks, backlog, notifications, reports, discount, budget, scorer weights, min score) are shown so every runtime key is tunable. They're placed per the Tab → keys table, and the complex ones (`*.per_stage`, `scorer_weights`, `notifications.recipients`) use the JSON editor. The fallback renders keys the UI registry doesn't know about.
7. **Model ID** is a `Select` of known ids plus "Other…" free text, because no API lists models. This is what lets an admin enter, and be told off for, a Fable id (AC4).
8. **Saves run sequentially, not in parallel.** That keeps the result order deterministic and keeps load trivial on the API.
9. **"Changed by" for the Access tab** comes from `GET /access/group-roles/history?limit=1` (`changed_by_name`), because `GET /access/group-roles` returns only the subject.

## Risks

- **Generated schema names.** The s28, s37 and s45 Pydantic names may differ in `schema.d.ts`. The fix is mechanical: use `ResponseOf<…>`.
- **The registry key spelling** (for example `receipt_watcher.*`) is unconfirmed. The fallback stops a missed key from disappearing. `makeAllConfigEntries` must mirror s02's final names.
- **State across soft navigation.** Switching tabs must keep the staging provider mounted. If s19's layout keys children by `searchParams`, staged edits are lost on a tab switch. Mitigation: the provider sits in `page.tsx` above the keyed `Suspense`. The E2E "edit two settings" test switches tabs between the edits.
- **The E2E stub** may need the s01 `playwright.config.ts` edit (Assumption 3), which could conflict with s19 or s20 doing the same. The merger keeps one stub.
- **Base UI `Select`** API differences (shadcn v4 default base). The coder checks `components.json` and the generated `select.tsx` before use.
- **Decimal handling.** Tolerance and fee inputs must never be converted to `Number`. The schema keeps strings (`^\d+(\.\d{1,2})?$`) and the API's `MoneyStr` is the authority.
