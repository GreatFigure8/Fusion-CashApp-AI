# Plan: settings-screen-redesign

Story: [story.md](story.md). Board: `design/project/glass/Settings.dc.html`, design.md §3.9, §4, §5, §7. Wave: builds after glass-theme-shell, db-stored-settings and fusion-mcp-transport are merged to the sprint tip (lesson L-comparison-wizard-from-fusion-2: the coder never stubs a dep's files; it imports them).

## 1 Approach

- research.md a1 (retheme through tokens and shared components only): `/config` keeps its Server Component page, staging provider, editors and the `PUT /config/{key}` server action; every surface is re-skinned with glass-theme-shell's `GlassPanel`, `Pill`, `MonoLabel`, `DiffBlock`, `StateCard`, `SkeletonRows`, `TopBar`. No per-page CSS.
- research.md a3 confirm pattern stays the write path: one audited PUT per staged key (CONFIG_WRITE, reason, expected_version); the MCP `server_url` is staged into the same provider and saved by the same footer.
- Group nav comes from `GET /config/groups` (story assumption); the web registry keeps only editor hints (editor kind, range, unit, order) and falls back to an editor chosen from the value's JSON type for keys it does not know, so new groups from db-stored-settings and other stories render with no web change.
- `config-tabs.tsx` becomes the group nav (`?group=`), plus one fixed "Payer aliases" link (aliases are a table, not config keys).
- Key search (`?q=`) filters across all groups; an empty result runs a pure did-you-mean (Levenshtein over key tokens).
- The one small API addition is a cross-key history read (`GET /config/history`) in a new auto-discovered router: it feeds the "Change history" card and the global version `vN` (= total change rows). Deviation from research.md recorded under Assumptions.

## 2 Files

### web/ (Next.js, existing layout: feature dir `components/config/`, route `app/(shell)/config/`)

| File | Change | Purpose |
|---|---|---|
| `web/app/(shell)/config/page.tsx` | change | `PageProps<"/config">`; parse `group`, `q`, `history`, `aq`, `apage` with Zod; start `loadMe`, `loadConfigEntries`, `loadConfigGroups`, `loadRecentChanges` together (`Promise.all`, DF-4); render `TopBar` ("Settings", env from `/me`, Pill "Stored in the database · v{total}", `KeySearch` in the right slot), split layout `GroupNav` + body. Viewer/operator get `canEdit=false`. |
| `web/app/(shell)/config/loading.tsx` | change | Board "Loading" state: `StateCard kind="loading"` + `SkeletonRows` shaped like nav + group card, caption "Reading settings…". |
| `web/app/(shell)/config/error.tsx` | change | `'use client'`, `retry()`, generic copy via `StateCard kind="error"` (TEST-20/21). |
| `web/app/(shell)/config/_components/tab-panel.tsx` | rename → `group-body.tsx` | Renders the active group: `access` → `AccessPanel`; `mcp` → `GroupCard` + `McpConnectionCard`; `retention` → `GroupCard` + existing `PurgeDryRun`; `aliases` (fixed link) → `AliasesPanel`; any other group → `GroupCard`; search mode → `GroupCard` titled "Results for '<q>'" or the empty did-you-mean `StateCard`. Always followed by `ChangeHistoryCard`. |
| `web/app/(shell)/config/_components/history-content.tsx` | keep | Per-key history sheet (unchanged behaviour). |
| `web/app/(shell)/config/_lib/load-config.ts` | change | Add `loadConfigGroups()` (`GET /config/groups`), `loadRecentChanges(limit=3)` (`GET /config/history`), `loadMcpStatus()` (`GET /integrations/mcp/status`). |
| `web/app/(shell)/config/_lib/search-params.ts` | new | The page's Zod `searchSchema` (moved out of page.tsx so it is unit-testable); `group` = `^[a-z0-9_-]{1,64}$` catch first group, `q` trimmed max 100. |
| `web/app/(shell)/config/_lib/mcp-test.ts` | new | `server-only` plain function `runMcpTest(apiCaller)` → `Result<McpTestOut, ApiError>` calling `POST /integrations/mcp/test` (TEST-10). |
| `web/app/(shell)/config/actions.ts` | change | Add `testMcpConnection(input: unknown)` thin `apiAction(z.object({}), …)` wrapper (auth inside, DF-12/SEC-21); no `refresh()` (a test changes no setting). |
| `web/components/config/config-tabs.tsx` | rewrite → export `GroupNav` (keep file name per story) | Glass nav from `ConfigGroupOut[]`: label, mono count, active `aria-current` + `bg-brand-soft` ring; fixed "Payer aliases" link; footnote "Only the database connection lives outside the database, in Vault. Every other setting is here, versioned and audited." Horizontal scroll under 1024px. |
| `web/components/config/key-search.tsx` | new | `'use client'` search input (`MonoLabel` "Find", placeholder "Find a setting key") that writes `?q=` with `router.replace` (debounced 200 ms), keeps `group`. |
| `web/components/config/key-match.ts` | new | Pure functions: `levenshtein(a,b)`, `keyTokens(key)`, `searchEntries(entries, q)`, `didYouMean(q, keys): string \| null` (§7 Interfaces, internal). |
| `web/components/config/settings-panel.tsx` | change → exports `GroupCard` (keep `SettingsPanel` name as alias only if callers remain; none expected) | `GlassPanel` with `PanelHeader` (group label, description, Pill "N unsaved change(s)" when > 0, `warn` tone) and rows; renders the group's `SaveFooter` at the bottom of the card. |
| `web/components/config/setting-row.tsx` | change | Mono key + help text (`description`), value editor (dirty → `border-brand-hi` + halo), last-changed (`d MMM · <last_changed_by>` / "seed" / "unsaved"), Pill muted "restart required" when `restart_required`, Pill locked "Vault secret" + mono OCID when `secret_ref` (never a value; editable only as an OCID text input with the Vault OCID pattern, and only with config:write), history link. Read-only: editor disabled. |
| `web/components/config/save-footer.tsx` | change | Diff summary lines `key old → new` (via `DiffBlock` or mono list), required reason input, Revert (clear staging), primary "Save as v{N+1}" (`N` = global version prop). Without config:write: buttons disabled with text "needs config write". Conflict → `StateCard kind="error"` label "Error · conflict", "Someone saved v{current} first. Your edit is kept.", action "Review the difference" opens `ReviewDialog`. Invalid → `StateCard kind="error"` "Error · invalid value", "<key> must be <range>. <value> was rejected. Nothing was saved." |
| `web/components/config/review-dialog.tsx` | change | Restyle onto `ConfirmDialog`/`DiffBlock` (reason, "Recorded as <name · role> · <date> UTC · expected version N"); conflict view shows their value vs yours; logic unchanged. |
| `web/components/config/history-list.tsx`, `history-sheet.tsx` | change | Restyle rows: mono `v{n}`, "when · who", `key old → new`, quoted reason. |
| `web/components/config/change-history-card.tsx` | new | `GlassPanel` "Change history" + muted Pill "last 3", rows from `GET /config/history` via `HistoryList`. Version per row = `total - index`. |
| `web/components/config/access-panel.tsx` | change | `GlassPanel` "Access: groups to roles", `DataTable`-style table (Identity-domain group, Role, Can) with fixed "Can" text per role (Admin "Everything, incl. engine control and config", Operator "Work items, lab replays, reports", Viewer "Reports"), "Map a group" button opening the existing `group-role-editor` (staged + audited as today). |
| `web/components/config/mcp-connection-card.tsx` | new | `'use client'` leaf. Props `{status: Result<McpStatusOut>, entry: ConfigEntry \| undefined, canEdit, canTest}`. Header `MonoLabel` "Connection" + "fusion-sql-mcp · Fusion reads", Pill ok "Healthy · N ms" / err "Unreachable"; `mcp.server_url` input bound to staging (same footer saves it); facts row (OAuth client `<client_id>`, "Secret in OCI Vault" when `secret_in_vault`, Source `<source>`, "Last call HH:MM:SS · <tool> · N rows" or "No calls yet"); text "Used for receipt search, invoice and credit memo lookups, lab replays and the assistant's read-only queries. Applying receipts stays on the direct Fusion client."; "Test connection" (`testMcpConnection` in `startTransition`, DF-22) → "Token valid · N tools · <probe_tool> N ms" or the error message; disabled "needs config write" without it. |
| `web/components/config/config-registry.ts` | change | Drop `ConfigTabId`/`CONFIG_TABS`/`tab`; keep `CONFIG_UI` editor hints keyed by key; add `editorFor(entry)` fallback by JSON type (number → number, boolean → switch, string → text, object/array → json, `secret_ref` → secret OCID text). |
| `web/components/config/config-tab-skeleton.tsx` | change | `SkeletonRows` card skeleton for `<Suspense>` of the group body. |
| `web/components/config/retention-panel.tsx`, `aliases-panel.tsx`, `aliases-table.tsx`, `purge-dry-run.tsx`, `retire-alias-dialog.tsx`, `changed-by-link.tsx`, `editors/*` | restyle only | Tokens/`GlassPanel`/`Pill`; behaviour unchanged. |
| `web/lib/api/openapi.json`, `web/lib/api/types.ts` | regenerate | `npm run api:sync` after the API change (types for `/config/history`, and the deps' `/config/groups`, `/integrations/mcp/*`). |

### api/ (additive read only)

| File | Change | Purpose |
|---|---|---|
| `api/src/cashapp/data/repositories/config.py` | change | `ConfigChangeRepository.history_all(offset, limit) -> Page[ConfigChange]`, newest first (`changed_at desc, id desc`). |
| `api/src/cashapp/services/config.py` | change | `ConfigAudit.history_all(uow, *, offset=0, limit=50)`. |
| `api/src/cashapp/api/routers/config_history.py` | new (auto-discovered) | `GET /config/history` (CONFIG_READ) → `ConfigChangePage` via existing `change_page()`; `offset ≥ 0`, `1 ≤ limit ≤ 200`. Separate module so it does not collide with db-stored-settings' edits to `routers/config.py`. |

No file under `components/ui/` is touched. No `.css` file is added.

### Design checklist (lesson L-admin-act-for-absent-owner-1; coder ticks each in validation.md)

- [ ] TopBar title "Settings"; env Pill (warn, DEV/PROD); Pill accent "Stored in the database · vN"; search `MonoLabel` "Find".
- [ ] Group nav glass, rows "label … count" (mono, faint), active row `bg-brand-soft text-brand-ink`; note text verbatim (see above).
- [ ] Group card header: group label; Pill warn "1 unsaved change" / "N unsaved changes".
- [ ] Row: mono key, help text (`text-muted-foreground`), editor `font-mono 13px` 130px, dirty accent border + halo, last-changed "2 Oct · J. Stevenson" / "seed" / "unsaved".
- [ ] Pill muted "restart required"; Pill locked "Vault secret" + OCID mono.
- [ ] Footer: `tolerance.CAD 0.10 → 0.15`, reason input (required), Revert (outline), primary "Save as v42" with accent glow.
- [ ] Connection card: "Connection", "fusion-sql-mcp · Fusion reads", Pill ok "Healthy · 180 ms" / err "Unreachable", `mcp.server_url` input, facts (OAuth client, "Secret in OCI Vault", Source, "Last call 14:02:08 · run_query · 64 rows"), explanatory text verbatim, "Test connection", "Token valid · 6 tools · fusion_rest_get 210 ms".
- [ ] Access: table headers "Identity-domain group", "Role", "Can"; "Map a group".
- [ ] Change history: Pill muted "last 3", rows `v41 · 21 Oct · J. Stevenson · tolerance.INR 0.25 → 0.49 · “lab replay rp_3290”`.
- [ ] States: Loading (skeletons); "Empty · search" "No setting matches “tolerence”" + "Did you mean tolerance?" (link); "Error · conflict" "Someone saved v42 first" / "Your edit is kept. Review their change, then save again." / "Review the difference"; "Error · invalid value" "tolerance.CAD must be 0.00 to 1.00" / "1.50 was rejected. Nothing was saved."
- [ ] Read-only: every control visible, disabled, "needs config write".
- [ ] Shared components used: `GlassPanel`/`PanelHeader`/`PanelBody`, `Pill`, `MonoLabel`, `DiffBlock`, `StateCard`, `SkeletonRows`, `TopBar`, `ConfirmDialog`, shadcn `Button`/`Input`/`Table`.
- [ ] Assistant dock shows on this screen (mounted by assistant-chat-redesign in the shell layout; nothing added here).

### Next.js rules applied

nextjs.md non-negotiables 1, 3, 7, 9, 13, 14; TS-1, TS-5, TS-10, TS-13, TS-16, TS-17, TS-19, TS-20, TS-22, TS-23, TS-27, TS-28, TS-30, TS-31, TS-32, TS-34; RC-5, RC-6, RC-7, RC-13, RC-36, RC-38, RC-44; DF-1, DF-2, DF-4, DF-10, DF-12, DF-13, DF-14, DF-15, DF-22, DF-24; SEC-5, SEC-16, SEC-21, SEC-22, SEC-23; TEST-2, TEST-10, TEST-14, TEST-17, TEST-18, TEST-20, TEST-21, TEST-25.

## 3 Test plan (written and run only in step 5)

| AC | Test | Path | Type |
|---|---|---|---|
| 1 | `settings top bar shows title, env, stored version pill and key search` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 2 | `group nav lists API groups with counts and the Vault note` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 2 | `GroupNav renders groups in API order with counts and marks the active group` | `web/components/config/config-tabs.test.tsx` | vitest |
| 3 | `editing a value marks it dirty, shows the unsaved pill and the footer diff, and saves as vN+1 with a reason` (asserts PUT body `{value, reason, expected_version}`) | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 3 | `SettingRow shows last-changed as date · name, seed, or unsaved` | `web/components/config/setting-row.test.tsx` | vitest |
| 3 | `SettingRow shows restart required and Vault secret pills, the OCID and never a value` | `web/components/config/setting-row.test.tsx` | vitest |
| 3 | `SaveFooter lists key old → new, requires a reason and labels Save as vN+1` | `web/components/config/save-footer.test.tsx` | vitest |
| 3 | `editorFor falls back by JSON type for keys not in CONFIG_UI` | `web/components/config/config-registry.test.ts` | vitest |
| 4 | `connection card shows Healthy · N ms, facts and a passing Test connection result` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 4 | `connection card shows Unreachable and the test error line` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 4 | `saving mcp.server_url goes through PUT /config/mcp.server_url with a reason` | `web/e2e/settings.spec.ts` | Playwright |
| 4 | `McpConnectionCard renders last call as HH:MM:SS · tool · N rows and No calls yet when null` | `web/components/config/mcp-connection-card.test.tsx` | vitest |
| 4 | `runMcpTest returns the McpTestOut and maps an API error to a value` | `web/app/(shell)/config/_lib/mcp-test.test.ts` | vitest (TEST-10) |
| 5 | `access card lists group, role and Can text and opens Map a group` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 5 | `change history card shows version, when · who, key old → new and quoted reason` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 5 | `GET /config/history returns changes across keys newest first with total` | `api/tests/api/test_config_history_all.py` | pytest (api) |
| 5 | `GET /config/history needs config:read` (403 without) | `api/tests/api/test_config_history_all.py` | pytest (api) |
| 5 | `GET /config/history pages with offset and limit and rejects limit 0 or 201` | `api/tests/api/test_config_history_all.py` | pytest (api) |
| 5 | `GET /config/history never contains a resolved secret, only the OCID` | `api/tests/api/test_config_history_all.py` | pytest (api) |
| 6 | `loading state shows skeletons while settings load` (mock delays `/config`) | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 6 | `searching tolerence shows no match with Did you mean tolerance and the link applies it` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 6 | `a 409 on save shows Someone saved vN first, keeps the edit and opens Review the difference` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 6 | `a 422 on save shows <key> must be <range> and Nothing was saved` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 6 | `config error boundary renders and Try again recovers` | `web/e2e/settings.spec.ts` | Playwright (TEST-17) |
| 7 | `viewer sees every value read-only with needs config write on save and test` | `web/e2e/settings.spec.ts` | Playwright, Settings board |
| 7 | `operator sees every value read-only with needs config write` | `web/e2e/settings.spec.ts` | Playwright |
| 7 | `SettingRow never renders a secret_ref as an editable value input when read-only` | `web/components/config/setting-row.test.tsx` | vitest |
| 8 | `didYouMean suggests tolerance for tolerence` | `web/components/config/key-match.test.ts` | vitest |
| 8 | `didYouMean returns null beyond distance 2 and for an empty query` | `web/components/config/key-match.test.ts` | vitest |
| 8 | `didYouMean breaks ties by shorter then alphabetical token` | `web/components/config/key-match.test.ts` | vitest |
| 8 | `levenshtein matches known distances` | `web/components/config/key-match.test.ts` | vitest |
| 8 | `searchEntries matches key and help text case-insensitively` | `web/components/config/key-match.test.ts` | vitest |
| 8 | `no CSS file or CSS module exists under the config route or components/config` | `web/tests/config/no-page-css.test.ts` | vitest (static) |
| — | `searchSchema falls back to the first group for an unknown or malformed group` | `web/app/(shell)/config/_lib/search-params.test.ts` | vitest |
| — | `settings at 375 px has no horizontal page scroll` | `web/e2e/settings.spec.ts` | Playwright (design §7) |

Totals: 17 Playwright, 16 vitest, 4 pytest = 37. Playwright runs against the existing mock API (`web/tests/support/mock-api-server.ts`, fixtures in `web/tests/support/fixtures/dto.ts`, extended by the tester with `/config/groups`, `/config/history`, `/integrations/mcp/status`, `/integrations/mcp/test`). Async Server Components are tested only in Playwright (TEST-2).

## 4 Data

No new model, no Alembic migration (split.md lists none for this story). The new read uses the existing `CONFIG_CHANGE` table through `ConfigChangeRepository`.

## 5 Config / env

- No new env variable. Web keeps `API_BASE_URL` (existing).
- No new DB config key. Reads/writes `mcp.server_url` (owned by fusion-mcp-transport) through `PUT /config/{key}`; displays `mcp.client_id`, `mcp.fusion_source` via `McpStatusOut`; `mcp.client_secret_ref` is a `secret_ref` row (OCID only).
- Group ids consumed from `GET /config/groups`: `access` (Access card), `mcp` (connection card), `retention` (purge dry run); every other group renders as a plain group card.

## 6 Risks and gates

- Dep contracts land in the same run: the coder starts only from the sprint tip after glass-theme-shell, db-stored-settings and fusion-mcp-transport are merged, and regenerates OpenAPI types (`npm run api:sync`). If a shared component's prop names differ from §7's pinned list, use the owner's names; never add a local copy.
- `GET /config/groups` group id for the mcp keys is assumed `mcp`; if db-stored-settings/fusion-mcp-transport names it differently, the connection card keys off the group containing `mcp.server_url` (implement it that way, not by id string).
- Global `vN` = total change rows (includes `access.group_role_map` changes); a multi-key save advances it by the number of keys, so the label shows the first new version.
- The board draws the dirty input border in warn; the story AC and design.md say accent. AC wins.
- `routers/config.py` is edited by db-stored-settings; this story adds a separate router module to avoid a merge collision.
- Coder gates (no tests): api `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`; web `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`.

## 7 Interfaces

### Provided

No story lists `settings-screen-redesign` in its deps (split.md graph), so nothing is pinned for a consumer. The additive endpoint is published for anyone who wants it:

- `GET /config/history?offset=0&limit=50` (CONFIG_READ) → existing `ConfigChangePage{items: ConfigChangeOut[], total, offset, limit}`, newest first across every key.
- `web/components/config/key-match.ts`: `levenshtein(a: string, b: string): number`; `keyTokens(key: string): readonly string[]` (split on `.` and `_`, lowercased); `searchEntries<T extends {key: string; description: string}>(entries: readonly T[], q: string): T[]`; `didYouMean(q: string, keys: readonly string[]): string | null` (best token or full key at distance ≤ 2, ties → shorter then alphabetical).

### Consumed (pinned from the deps' story contracts)

- glass-theme-shell (`web/components/common/*`, `web/components/shell/*`): `GlassPanel`, `PanelHeader`, `PanelBody`; `Pill{tone: "ok"|"accent"|"warn"|"err"|"locked"|"muted", dot?, mono?}`; `MonoLabel`; `DiffBlock{lines: {op: "-"|"+"|" ", text}[]}`; `SkeletonRows`; `StateCard{kind: "loading"|"empty"|"error"|"denied", label, headline, body, actions}`; `ConfirmDialog` (reason → `{reason}`); `TopBar` (title + right-slot children; assumed prop names `title`, `children`).
- db-stored-settings: `ConfigEntry` + `group, restart_required, secret_ref, last_changed_at, last_changed_by`; `GET /config/groups` → `[{group, label, count, description}]` (`ConfigGroupOut`).
- fusion-mcp-transport: `GET /integrations/mcp/status` → `McpStatusOut{healthy, latency_ms, server_url, client_id, source, secret_in_vault, last_call: {at, tool, rows, duration_ms} | null}`; `POST /integrations/mcp/test` → `McpTestOut{token_valid, tools_count, probe_tool, probe_ms, error?}`.

## Assumptions

- research.md has no cross-key history read; one additive `GET /config/history` is added here (API owns data, CLAUDE.md) to back the Change history card and the `vN` pill. No migration.
- "Payer aliases" stays reachable as a fixed nav link after the API groups, because aliases are rows in their own table, not config keys.
- The old `?tab=` URLs are not kept; `?group=` replaces them (internal links only).
- `secret_ref` rows: with config:write the OCID is editable as text validated against the Vault secret OCID pattern (`ocid1.vaultsecret.`); never a password/value field, and the resolved secret is never fetched.
- Did-you-mean compares against key tokens as well as full keys, so "tolerence" suggests "tolerance" (the board copy) rather than "tolerance.CAD".
- "Can" text per role is fixed copy from the board (a description of the permission sets), not data.
- Dirty border uses the accent token (AC 3 and design.md §3.9), not the board's warn colour.
