# Plan: glass-theme-shell

Story: [story.md](story.md) (issue #48). Board owned: **Shell** (`design/project/glass/Shell.dc.html`; design.md §1, §2, §4, §5, §7, §8).
Skills/rules applied: `nextjs-fullstack-standards` (layering, Zod at boundaries, shadcn from CLI, `components/ui` untouched), bmn `nextjs.md` non-negotiables 1, 7, 8, 13, 14 and topic rules **TS-1, TS-10, TS-14, TS-23, TS-28, TS-29, TS-30, TS-31, TS-32, RC-5, RC-6, RC-7, RC-8, RC-9, RC-38, RC-39, RC-44, RT-4, RT-22, RT-26, RT-31, SSE-24, SSE-25, SSE-26, PERF-8, PERF-11, PERF-16, TEST-1, TEST-2, TEST-6, TEST-12, TEST-14, TEST-23, TEST-25**. API side: `python-web-app:wiring-application-config` (new keys validated, falsy-but-valid not defaulted).

## 1 Approach

- research.md **a1**: retheme through tokens only. Port design.md §1 raw tokens (light `:root`, dark `.dark`, exact hex) into `web/app/globals.css`, map them onto the shadcn variables (§8.2), alias `--status-*` (§8.3), add the `@theme inline` names (§8.4), `.bg-blueprint` (§8.5), keyframes (`live-pulse`, `shimmer`, `breathe`) and a global 4px accent focus halo. No per-page CSS anywhere.
- `app/layout.tsx`: `defaultTheme="dark"`, `enableSystem` kept, Geist Sans/Mono kept (PERF-8/11). A Theme radio (Dark/Light/System) is added to the existing `UserMenu` so light stays selectable.
- One owner for every shared component (split.md "Shared owners"): new `components/common/*` primitives are thin wrappers over shadcn `ui/*` (`card`, `badge`, `alert-dialog`, `sheet`, `skeleton`, `button`, `table`), styled only with token utilities. `components/ui/*` is not edited (the warn button variant lives in `common/action-button.tsx`, a cva wrapper over `buttonVariants`).
- Shell rewritten: dotted ground, glass `NavRail` (lg and up) / mobile bar + `ui/sheet` (below 1024), per-page `TopBar`, `StatusFooter`, an optional `dock` slot (filled by assistant-chat-redesign). `(shell)/layout.tsx` wraps the session gate in `<Suspense>` with a skeleton (RC-38/39) and renders the denied and API-down state cards.
- Footer data: server-side initial `GET /engine/status` (own `<Suspense>`, never blocks the shell) plus the existing `useEventStream` on `/engine/stream` (`status` event). Failure shows "Bus status unavailable".
- API (additive): `GET /me` gains `env`, `sample_data`, `access_request_url`; two DB config keys `ui.sample_data`, `ui.access_request_url` (no env/file setting; input.md item 3). OpenAPI regenerated with `npm run api:sync`.

## 2 Files

### Web (`web/`)

| File | Change | Purpose |
|---|---|---|
| `app/globals.css` | change | Tokens §1 for `:root` (light, payroll-compare set) and `.dark`; shadcn mapping §8.2 (dark `--primary: var(--acc)`, light `--primary: var(--acc-hi)`, `--radius: 0.625rem`, sidebar vars); `--status-*` aliases §8.3 (`--status-locked: #b794ff` dark, existing violet light); `@theme inline` §8.4 (`--color-surface-1/2/3`, `--color-line`, `--color-line-strong`, `--color-faint`, `--color-brand`, `--color-brand-hi`, `--color-brand-ink`, `--color-brand-soft`, `--color-ok/-ink/-soft`, `--color-warn/-ink/-soft`, `--color-err/-ink/-soft`, `--color-locked`, `--color-locked-ink`, `--color-locked-soft`, `--color-log`, `--color-header`, `--color-scrim`, `--shadow-panel`, `--shadow-float`, `--font-mono: var(--font-geist-mono)`, `--animate-breathe`, `--animate-live-pulse`, `--animate-shimmer`, `--text-label: 0.6875rem`); `.bg-blueprint` copied verbatim; `@keyframes`; base layer `:where(a,button,input,textarea,select,summary,[tabindex]):focus-visible { outline: none; box-shadow: 0 0 0 4px var(--halo) }` with `--halo: #4f7cff1f` dark / `#2563eb26` light; `@media (prefers-reduced-motion: reduce)` disables the three animations. Also `--locked/-ink/-soft` raw tokens (dark `#b794ff/#d4bfff/#b794ff1a`). |
| `app/layout.tsx` | change | `defaultTheme="dark"`, `enableSystem`; fonts unchanged; no Inter. |
| `app/page.tsx` | change | `redirect("/dashboard")` (outside any try, TEST-23). |
| `app/(shell)/layout.tsx` | change | `requireSession()` then `<Suspense fallback={<ShellSkeleton/>}><ShellGate>{children}</ShellGate></Suspense>`. `ShellGate` (same file, async): `getMe()`; API down (status 0 or 502/503/504) → `<ApiDownState/>`; other error → existing `ErrorAlert`; `me.roles.length === 0` → `<DeniedState/>`; else `<AppShell me env sampleData footer={<Suspense fallback={<StatusFooter initial={null} pending/>}><StatusFooterServer/></Suspense>}>`. No `dock` here (assistant-chat-redesign adds `dock={...}`). |
| `app/(shell)/flow/page.tsx`, `exceptions/page.tsx`, `reports/page.tsx`, `config/page.tsx` | change (one line each) | Render `<TopBar title="Flow" />` / `"Exceptions"` / `"Reports"` / `"Settings"` first (config replaces its `<h1>Configuration</h1>`). Nothing else on those pages changes (owned by their restyle stories). |
| `app/signed-out/page.tsx` | change | `bg-blueprint` ground + `GlassPanel` + `StateCard`-style copy; logic and link unchanged. `app/auth/*` are route handlers (redirects only, no UI): no change; they land on `/signed-out` or the shell, both on the ground. |
| `components/common/glass-panel.tsx` | new | `GlassPanel`, `PanelHeader`, `PanelBody` (§7 contract). |
| `components/common/pill.tsx` | new | `Pill`, `PillTone`, `PILL_TONE_CLASSES`. |
| `components/common/live-dot.tsx` | new | `LiveDot` (glowing dot, pulse with `motion-reduce:animate-none`). |
| `components/common/mono-label.tsx` | new | `MonoLabel` (`.lab`). |
| `components/common/meter.tsx` | new | `Meter`. |
| `components/common/segmented.tsx` | new (`"use client"`) | `Segmented` radiogroup, roving tabindex, Arrow/Home/End keys. |
| `components/common/filter-chip.tsx` | new (`"use client"`) | `FilterChip`, `SuggestionChip`. |
| `components/common/action-button.tsx` | new | `ActionButton`, `actionButtonVariants` (adds `warn`, `warn-solid`, `glow`). |
| `components/common/confirm-dialog.tsx` | new (`"use client"`) | `ConfirmDialog` on `ui/alert-dialog`; reads actor from `useShellSession()`. |
| `components/common/diff-block.tsx` | new | `DiffBlock`. |
| `components/common/skeleton-rows.tsx` | new | `SkeletonRows` (shimmer gradient `linear-gradient(90deg,#ffffff08,#ffffff14,#ffffff08)`, 12px, radius 6, reduced-motion safe). |
| `components/common/state-card.tsx` | new | `StateCard`. |
| `components/common/shell-session.tsx` | new (`"use client"`) | `ShellSessionProvider`, `useShellSession()` → `{me, env, sampleData}` (RC-9). |
| `components/common/kpi-card.tsx` | change | Glass, mono 30px value, `variant` `plain|ring|meter`, `tone`, `size`; old props unchanged. |
| `components/common/status-badge.tsx` | change | Renders through `Pill`; `STATUS_PILL_TONE` map; `STATUS_TOKENS`, `statusToken`, `StatusBadge` signatures unchanged. |
| `components/common/data-table.tsx` | change | Mono uppercase 11px header (8x12), 10x12 cells, `selectedRowId` tint `bg-brand-soft`, column `meta.align: "right"` + `meta.mono`, wrapper `overflow-x-auto`, cells `whitespace-nowrap`. Existing props kept. |
| `components/common/live-indicator.tsx` | change | Restyled as `Pill` + `LiveDot` (same props). |
| `components/shell/app-shell.tsx` | rewrite | `AppShell` layout (§7 contract): ground, rail, main column, footer, dock slot; providers `ShellSessionProvider`, `FlowStreamProvider`, `CommandPaletteProvider`. |
| `components/shell/nav-rail.tsx` | new (`"use client"`) | `NavRail` (brand row, items with code chip and `NavCount`, active ring/glow via `aria-current="page"`, user row = `UserMenu` trigger) and `MobileNavBar` (below `lg`: brand + menu button opening `ui/sheet` with `NavRail` content). |
| `components/shell/nav.ts` | change | 8 entries, `code`, `countSource`; `visibleNav` unchanged in behaviour. |
| `components/shell/nav-counts.ts` | new (`"use client"`) | `NavCountSource` hooks map; `NavCount` component. |
| `components/shell/top-bar.tsx` | new (`"use client"`) | `TopBar`. |
| `components/shell/status-footer.tsx` | new (`"use client"`) | `StatusFooter` + pure `formatFooter(status)`; subscribes to `/engine/stream`. |
| `components/shell/status-footer-server.tsx` | new (server) | `StatusFooterServer`: `api("get", "/engine/status")`, Zod-free typed via OpenAPI, renders `<StatusFooter initial={ok ? value : null}/>`. |
| `components/shell/shell-states.tsx` | new | `ShellSkeleton` (server), `DeniedState` (server), `ApiDownState` (`"use client"`: 8 s countdown then `router.refresh()`, "Retry now" refreshes at once, TEST-25). |
| `components/shell/command-palette.tsx` | change | Controlled by `CommandPaletteProvider` / `useCommandPalette()` (`open()`), ⌘K/Ctrl+K kept; restyled. |
| `components/shell/env-badge.tsx` | change | Becomes `EnvPill{env}`: `Pill tone="warn" mono` with `env.toUpperCase()`. |
| `components/shell/user-menu.tsx` | change | Trigger = rail user row (28px initials avatar, name 13px, role 10px mono label); adds Theme radio (Dark/Light/System, `next-themes`). |
| `components/shell/breadcrumbs.tsx`, `flow-stream.tsx` | keep | `FlowStreamProvider` unchanged; breadcrumbs no longer mounted by the shell (TopBar `crumb` replaces it). |
| `lib/permissions.ts` | change | `ROUTE_PERMISSIONS` adds `/dashboard` (reports:read), `/engine` (reports:read), `/review` (items:work), `/lab` (lab:run). |
| `lib/api/stream-paths.ts` | change | Add `"/engine/stream"`. |
| `lib/api/openapi.json`, `lib/api/schema.d.ts` | regenerated | `npm run api:sync` after the API change. |

### API (`api/`)

| File | Change | Purpose |
|---|---|---|
| `src/cashapp/domain/config_keys.py` | change (append-only `ui.*` block) | `UI_SAMPLE_DATA = _key("ui.sample_data", bool, False, "Show the Sample data pill: the environment runs on generated test data. Ignored in prod.")`; `UI_ACCESS_REQUEST_URL = _key("ui.access_request_url", str \| None, None, "Link behind Request access when a user's groups map to no role.")`; both added to `_ALL_KEYS`. |
| `src/cashapp/services/ui_context.py` | new | `UiContext` (frozen dataclass: `env`, `sample_data`, `access_request_url`) and `resolve_ui_context(env: Env, snapshot: ConfigSnapshot \| None) -> UiContext`: `sample_data = env != "prod" and snapshot.get(UI_SAMPLE_DATA)`; snapshot `None` (config unreadable) gives `False`/`None`. Pure, no request objects. |
| `src/cashapp/api/schemas/me.py` | change | `MeResponse` adds `env: Literal["local","dev","test","prod"]`, `sample_data: bool`, `access_request_url: str \| None`; `from_principal(principal, ui: UiContext)`. |
| `src/cashapp/api/routers/me.py` | change | Depends on `RuntimeConfigDep`; reads `get_settings().env`; `snapshot = await runtime.snapshot()` inside `try/except ConfigError, DB errors` → `None` (logged by name, never values); `/me` keeps working when config is down. |

Total: 45 files (web 41 incl. 2 regenerated, api 4). Created: 20; changed or regenerated: 25. `breadcrumbs.tsx` and `flow-stream.tsx` are kept unchanged and not counted.

## 3 Test plan

Nobody writes or runs these until step 5. Unit = Vitest (`web/tests/**`, jsdom) or pytest; browser = Playwright (`web/e2e/*.spec.ts`) against the production build with the s19 mock API (`tests/support/mock-api-server.ts`), which gains `/engine/status`, `/engine/stream` and `/me` variants (fixtures `tests/support/fixtures/me-admin.json`, `me-no-role.json`, `me-sample.json`, `engine-status.json`). Async Server Components (layout gate, `StatusFooterServer`) are covered only in Playwright (TEST-2).

| AC | Test (path :: name) | Type |
|---|---|---|
| 1 | `web/tests/theme/globals-css.test.ts` :: `defines every design token in :root and .dark` | unit |
| 1 | same :: `uses the exact hex values of design.md section 1` (table-driven, both modes) | unit |
| 1 | same :: `maps shadcn variables onto tokens with dark primary var(--acc)` | unit |
| 1 | same :: `aliases every --status-* variable` | unit |
| 1 | same :: `adds the @theme inline names and --radius 0.625rem` | unit |
| 1 | same :: `ships .bg-blueprint with the 22px dot grid` | unit |
| 1 | same :: `disables live-pulse, shimmer and breathe under prefers-reduced-motion` | unit |
| 2 | `web/tests/app/root-layout.test.tsx` :: `defaults next-themes to dark with system still enabled` (mocks `next-themes`, `next/font/google`) | unit |
| 2 | same :: `loads Geist Sans and Geist Mono and never Inter` | unit |
| 3 | `web/tests/components/common/glass-panel.test.tsx` :: `renders panel, header title and right slot, body` ; `err tone uses the err border` ; `solid variant has no blur` | unit |
| 3 | `web/tests/components/common/pill.test.tsx` :: `maps each tone to its soft bg and ink text` (6 tones) ; `renders a dot and mono text when asked` | unit |
| 3 | `web/tests/components/common/mono-label.test.tsx` :: `renders mono uppercase 11px label as the given element` | unit |
| 3 | `web/tests/components/common/meter.test.tsx` :: `exposes role meter with value and max` ; `clamps out-of-range values` ; `size 5 and 6 set the bar height` ; `tone colours the fill` | unit |
| 3 | `web/tests/components/common/segmented.test.tsx` :: `marks the selected option checked` ; `calls onChange on click` ; `ArrowRight/ArrowLeft/Home/End move and select` ; `only the selected option is tabbable` | unit |
| 3 | `web/tests/components/common/filter-chip.test.tsx` :: `FilterChip toggles aria-pressed and shows the count` ; `SuggestionChip calls onClick and respects disabled` | unit |
| 3 | `web/tests/components/common/confirm-dialog.test.tsx` :: `confirm is disabled until a reason is entered` ; `returns trimmed {reason} on confirm` ; `shows Recorded as <name · role> · <date> UTC · expected version N` ; `omits the version clause when expectedVersion is undefined` ; `cancel closes without calling onConfirm` ; `warn tone uses the warn-solid confirm button` | unit |
| 3 | `web/tests/components/common/diff-block.test.tsx` :: `renders - lines err-tinted, + lines ok-tinted, context plain, in order` | unit |
| 3 | `web/tests/components/common/skeleton-rows.test.tsx` :: `renders N shimmer rows with aria-busy and caption` ; `rows carry motion-reduce:animate-none` | unit |
| 3 | `web/tests/components/common/state-card.test.tsx` :: `renders label, headline, body and actions per kind` ; `error kind has the err border and role alert` ; `loading kind is aria-busy` | unit |
| 3 | `web/tests/components/common/kpi-card.test.tsx` :: `existing label/value/hint/loading callers render unchanged` ; `value is mono 30px` ; `ring variant draws an SVG ring at progress` ; `meter variant renders a Meter` ; `accent and warn tones colour the value` | unit |
| 3 | `web/tests/components/common/status-badge.test.tsx` :: `maps status tokens to Pill tones (success ok, progress accent, waiting muted, attention warn, error err, locked locked, neutral muted)` ; `every generated enum value has a token` (typed table) | unit |
| 3 | `web/tests/components/common/data-table.test.tsx` :: `header cells are mono uppercase` ; `selectedRowId row gets the selected tint and aria-selected` ; `meta.align right right-aligns numeric cells` ; `table is wrapped in a horizontal scroll container` | unit |
| 4 | `web/tests/components/common/action-button.test.tsx` :: `warn variant is the outline warn tone` ; `warn-solid is the filled confirm form` ; `default variants still match ui/button` | unit |
| 4 | `web/tests/components/ui-untouched.test.ts` :: `components/ui has no warn variant (wrapper only)` (reads `components/ui/button.tsx`) | unit |
| 5 | `web/tests/components/shell/nav.test.ts` :: `holds 8 entries in board order with two-letter codes` ; `each entry names its permission and count source` ; `visibleNav filters by permission` | unit |
| 5 | `web/tests/components/shell/nav-counts.test.tsx` :: `flow.in_flight sums in_queue and in_progress across stages` ; `exceptions.open is needs_person` ; `unwired sources render nothing` | unit |
| 5 | `web/tests/app/home-page.test.ts` :: `redirects / to /dashboard` (mocks `next/navigation`) | unit |
| 6 | `web/tests/components/shell/top-bar.test.tsx` :: `shows title, env pill in warn tone, Live pill from the stream status` ; `Sample data pill only when sampleData` ; `search field opens the command palette` ; `renders the right slot` | unit |
| 6 | `web/e2e/shell.spec.ts` :: `shell board: blueprint ground, glass rail and top bar at 1440` (Shell board) | browser |
| 6 | same :: `shell board: nav codes, Flow in-flight and Exceptions open counts` | browser |
| 6 | same :: `shell board: active nav item has accent ring and aria-current` | browser |
| 6 | same :: `shell board: user row shows initials and role label` | browser |
| 6 | same :: `shell board: Live pill follows the flow SSE connection` | browser |
| 6 | same :: `shell board: Sample data pill only when the API reports sample data` | browser |
| 6 | same :: `shell board: search field and Ctrl+K open the command palette` | browser |
| 7 | `web/tests/components/shell/status-footer.test.tsx` :: `formats lag, dlq warn when > 0, pollers N/M with minute intervals and region` ; `updates from a status SSE frame` ; `shows Bus status unavailable when initial is null and no frame arrived` ; `invalid frames are dropped` | unit |
| 7 | `web/e2e/shell.spec.ts` :: `shell board: status footer from GET /engine/status and SSE status event` | browser |
| 7 | same :: `shell board: footer shows Bus status unavailable and the page still works when engine status fails` | browser |
| 8 | same :: `shell board states: loading session shows skeleton rail and bar` (mock delays `/me`) | browser |
| 8 | same :: `shell board states: denied shows No role is mapped to your groups with Request access` | browser |
| 8 | same :: `shell board states: API down shows the retry copy and Retry now recovers` | browser |
| 8 | `web/tests/components/shell/shell-states.test.tsx` :: `ApiDownState counts down 8 s then refreshes` ; `Retry now refreshes immediately` (fake timers, mocked router) | unit |
| 9 | `web/e2e/shell.spec.ts` :: `shell board responsive: 375 px has no horizontal page scroll` | browser |
| 9 | same :: `shell board responsive: below 1024 px the rail opens from the menu button in a sheet` | browser |
| 9 | same :: `shell board: focus ring is the 4px accent halo` (computed `box-shadow` on a focused nav link and the search input) | browser |
| 9 | same :: `shell board: live dot does not pulse under prefers-reduced-motion` (`page.emulateMedia({ reducedMotion: "reduce" })`) | browser |
| 10 | `api/tests/api/test_me_ui_context.py` :: `test_me_returns_env_and_sample_data` ; `test_sample_data_false_in_prod_even_when_key_true` ; `test_sample_data_true_in_dev_when_key_set` ; `test_sample_data_defaults_false` ; `test_me_still_answers_when_config_unreadable` ; `test_access_request_url_passthrough` | unit (pytest, dependency overrides) |
| 10 | `api/tests/services/test_ui_context.py` :: `test_resolve_ui_context_matrix` (env x key x snapshot None) | unit |
| 10 | `api/tests/domain/test_ui_config_keys.py` :: `test_ui_keys_registered_with_defaults` ; `test_sample_data_rejects_int_as_bool` | unit |
| 10 | `web/tests/lib/api/openapi-me.test.ts` :: `MeResponse in openapi.json has env, sample_data and access_request_url` | unit |
| 11 | `web/tests/app/signed-out.test.tsx` :: `renders on the blueprint ground with a glass panel and the sign-in link unchanged` | unit |
| 11 | `web/e2e/shell.spec.ts` :: `signed-out page renders on the dotted ground` | browser |
| — | `web/tests/lib/api/stream-paths.test.ts` :: `allows /engine/stream` | unit |

Counts: 98 named tests (unit 81: web 71, api 10; browser 17).

### Shell board checklist (lesson L-admin-act-for-absent-owner-1; coder ticks each in validation.md)

- [ ] Ground: `--bg` + 22px dot grid, 16px padding, rail `flex 1 1 200px`, main `flex 999 1 560px` `min-w-0`, gap 16.
- [ ] Rail brand: 28px radius-8 `--acc` tile "CA" mono 12px white with glow `0 0 20px -4px #4f7cff`; "CashApp" 600; mono label "AI" right.
- [ ] Nav item: 26x22 mono code chip, label, right mono count 11px `--faint`; min-height 40, 8x10 padding, radius 10; hover `#ffffff0a`.
- [ ] Active: `--acc-soft` fill, `--acc-ink` text, `inset 0 0 0 1px #4f7cff66, 0 0 28px -10px #4f7cff`, code chip border `--acc-hi`.
- [ ] Codes/labels in order: Dashboard DB, Flow FL, Exceptions EX, Engine EN, Review RV, Reports RP, Lab LB, Config CF.
- [ ] User row: hairline above, 28px circular `--s3` initials avatar with `--line2` border, name 13px, role 10px mono uppercase label.
- [ ] TopBar: glass; title 18/600 (optional mono crumb + `/`); env pill warn mono (`DEV`, `PROD`, `TEST`, `LOCAL`); `Live` ok pill with glowing dot (Reconnecting… warn / Disconnected err from the stream status); `Sample data` muted pill; right slot; search label "Search", placeholder "Item, receipt, invoice", kbd `⌘K`, min-width 260.
- [ ] Footer: glass strip 8x16, 12px `--soft`: `Bus healthy` ok pill with dot (or `Bus unhealthy` err), `lag N` mono, `dlq N` mono warn when > 0, "Pollers H/T · intake Nm · receipt watcher Nm", right `us-ashburn-1` mono; failure copy "Bus status unavailable".
- [ ] Glass: `bg-surface-1/70 backdrop-blur-[14px] border-line-strong rounded-2xl shadow-float`.
- [ ] Pills: ok/accent/warn/err/locked/muted soft bg + ink text; status mapping Applied ok, In progress accent, Awaiting receipt muted, Needs attention warn, Failed err, Locked locked.
- [ ] Buttons: primary with glow `0 0 24px -8px #4f7cff`, outline, warn outline ("Pause"), ghost ("Cancel"), warn-solid `bg-warn text-[#1b1300]`.
- [ ] Type: KPI value mono 30/500/-0.02em; label mono 11px uppercase 0.08em; money mono.
- [ ] Loading: skeleton rail (4 bars, 110px) + bar (30px) + block (80px), caption "Loading your session…".
- [ ] Denied: label "Empty · no role", headline "No role is mapped to your groups", body "Your identity-domain groups are not mapped to an app role yet. An admin maps them in Config.", link "Request access".
- [ ] API down: err border `#f8717155`, label "Error · API unreachable" in `--err-ink`, headline "The cash app API is not answering", body "Pipeline workers keep running. Retrying in 8 seconds.", button "Retry now".
- [ ] Mobile (< 1024): top bar with menu button (aria-label "Open navigation") opening `ui/sheet`; 375 px no horizontal scroll; focus halo 4px; reduced motion stops live dot pulse and skeleton shimmer.

## 4 Data

No ORM model and **no Alembic migration**: the two `ui.*` keys are code-defined `ConfigKey`s; with no stored row the ConfigService serves the default (`effective_value`). split.md's migration list does not include this story.

## 5 Config / env

- DB config keys (new, group `ui`, `admin_only_write=True`): `ui.sample_data` (bool, default `false`; forced false when `env == "prod"`), `ui.access_request_url` (`str | null`, default `null`; when null the Request access link is `mailto:?subject=CashApp%20access%20request`).
- Read, not added: bootstrap `CASHAPP_ENV` (`Settings.env`, stays env per db-stored-settings).
- Web env: none added. The shell stops reading `NEXT_PUBLIC_ENV_LABEL` (env comes from `/me`); `lib/env.public.ts` stays for db-stored-settings to trim. Existing `API_BASE_URL` unchanged.

## 6 Risks and gates

- **Shared-file churn:** `globals.css`, `components/common/*`, `nav.ts`, `(shell)/layout.tsx` are imported by every UI story in the same wave; contracts in §7 are frozen, extensions are additive props only.
- `useEventStream` moves to `web/hooks/use-event-stream.ts` (live-progress-dashboard owns the move). This story imports today's `@/lib/api/use-event-stream`; the dashboard story updates the import in `status-footer.tsx` and `flow-stream.tsx` when it moves the hook.
- `/engine/status` and `/engine/stream` come from engine-control-api (same wave). If the stream does not emit `status` on connect, the server-side initial fetch still fills the footer; if the endpoint is missing at merge time the footer shows "Bus status unavailable" (by design, AC7).
- Base UI `alert-dialog`/`sheet` APIs differ from Radix: coder reads `components/ui/alert-dialog.tsx` and `sheet.tsx` before composing (no `asChild`, use `render`).
- Global focus halo vs shadcn `ring-3` utilities: utilities win on `ui/*` elements; the 4px halo is asserted on shell-owned elements (nav link, search input).
- Restyle via tokens changes every existing screen's look at once (intended, a1); light mode contrast inherits payroll-compare.
- OpenAPI regeneration collides with other API stories; the merger re-runs `npm run api:sync` after each API merge.
- Removing `ui/sidebar` from the shell (rail is hand-composed; the 1024 breakpoint does not fit `useIsMobile`'s 768) leaves `components/ui/sidebar.tsx` and `hooks/use-mobile.ts` unused but in place.

Coder gates (lint + type-check only; no tests written or run):
- api: `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`
- web: `cd web && npm ci && npm run api:sync && npx eslint . && npx next typegen && npx tsc --noEmit`

## 7 Interfaces provided (pinned; consumers build against these in the same wave)

All under `web/`, named exports, `"use client"` only where marked (C).

```ts
// components/common/pill.tsx
export type PillTone = "ok" | "accent" | "warn" | "err" | "locked" | "muted";
export const PILL_TONE_CLASSES: Readonly<Record<PillTone, string>>;
export function Pill(p: { tone: PillTone; dot?: boolean; pulse?: boolean; mono?: boolean;
  title?: string; className?: string; children: ReactNode }): JSX.Element;
// components/common/live-dot.tsx
export function LiveDot(p: { tone?: "ok" | "warn" | "err"; pulse?: boolean; className?: string }): JSX.Element;
// components/common/glass-panel.tsx
export function GlassPanel(p: { as?: "section" | "div" | "aside" | "nav" | "header" | "footer";
  tone?: "default" | "accent" | "warn" | "err"; solid?: boolean; className?: string;
  "aria-label"?: string; children: ReactNode }): JSX.Element;
export function PanelHeader(p: { title?: ReactNode; titleSize?: "card" | "page" | "label";
  className?: string; children?: ReactNode /* right side: pills, labels */ }): JSX.Element;
export function PanelBody(p: { flush?: boolean; className?: string; children: ReactNode }): JSX.Element;
// components/common/mono-label.tsx
export function MonoLabel(p: { as?: "span" | "p" | "div" | "h2" | "h3"; className?: string; children: ReactNode }): JSX.Element;
// components/common/meter.tsx
export function Meter(p: { value: number; max?: number /*1*/; tone?: "accent" | "ok" | "warn" | "err";
  size?: 5 | 6 /*6*/; label: string /*aria-label*/; className?: string }): JSX.Element;
// components/common/segmented.tsx (C)
export type SegmentedOption<T extends string> = { readonly value: T; readonly label: ReactNode };
export function Segmented<T extends string>(p: { options: readonly SegmentedOption<T>[]; value: T;
  onChange: (value: T) => void; ariaLabel: string; className?: string }): JSX.Element;
// components/common/filter-chip.tsx (C)
export function FilterChip(p: { active: boolean; onClick: () => void; count?: number;
  disabled?: boolean; children: ReactNode }): JSX.Element;            // aria-pressed
export function SuggestionChip(p: { onClick: () => void; disabled?: boolean; title?: string;
  children: ReactNode }): JSX.Element;
// components/common/action-button.tsx
export const actionButtonVariants: (o?: { variant?: ActionVariant; size?: ButtonSize; glow?: boolean; className?: string }) => string;
export type ActionVariant = "default" | "outline" | "secondary" | "ghost" | "destructive" | "link" | "warn" | "warn-solid";
export function ActionButton(p: ComponentProps<typeof Button> & { variant?: ActionVariant; glow?: boolean }): JSX.Element;
// components/common/confirm-dialog.tsx (C)
export function ConfirmDialog(p: { open: boolean; onOpenChange: (open: boolean) => void;
  title: string; body: ReactNode; confirmLabel: string; tone?: "warn" | "accent" | "err" /*warn*/;
  expectedVersion?: number; reasonLabel?: string /*"Reason"*/; reasonPlaceholder?: string;
  pending?: boolean; error?: ReactNode /* shown inline, dialog stays open */;
  onConfirm: (result: { reason: string }) => void | Promise<void> }): JSX.Element;
// audit line: "Recorded as <me.display_name · role> · <d MMM yyyy HH:mm> UTC · expected version N"
// components/common/diff-block.tsx
export type DiffLine = { readonly op: "-" | "+" | " "; readonly text: string };
export function DiffBlock(p: { lines: readonly DiffLine[]; caption?: string; className?: string }): JSX.Element;
// components/common/skeleton-rows.tsx
export function SkeletonRows(p: { rows?: number /*3*/; height?: number /*12*/; caption?: string; className?: string }): JSX.Element;
// components/common/state-card.tsx
export type StateKind = "loading" | "empty" | "error" | "denied";
export function StateCard(p: { kind: StateKind; label?: string /* default Loading|Empty|Error|Denied; e.g. "Error · API unreachable" */;
  headline: string; body?: ReactNode; actions?: ReactNode; children?: ReactNode /* e.g. SkeletonRows */;
  className?: string }): JSX.Element;
// components/common/kpi-card.tsx (extended, old callers unchanged)
export function KpiCard(p: { label: string; value: ReactNode; hint?: ReactNode; loading?: boolean;
  variant?: "plain" | "ring" | "meter" /*plain*/; progress?: number /*0..1 for ring/meter*/;
  tone?: "default" | "accent" | "warn" | "ok" | "err"; size?: "default" | "sm" /*sm = 20px mini stat*/;
  className?: string }): JSX.Element;
// components/common/status-badge.tsx (unchanged exports + new map)
export const STATUS_PILL_TONE: Readonly<Record<StatusToken, PillTone>>;
// components/common/data-table.tsx (additive)
//   DataTableProps<T> gains: selectedRowId?: string | null
//   column meta (module augmentation in data-table.tsx): meta?: { align?: "left" | "right"; mono?: boolean }
// components/common/shell-session.tsx (C)
export type ShellSession = { readonly me: Me; readonly env: Me["env"]; readonly sampleData: boolean };
export function useShellSession(): ShellSession;   // throws outside the shell
// components/shell/top-bar.tsx (C)
export function TopBar(p: { title: string; crumb?: string; pills?: ReactNode /* after env/Live/Sample */;
  search?: boolean /*true*/; children?: ReactNode /* right slot: page controls */ }): JSX.Element;
// components/shell/app-shell.tsx (C)
export function AppShell(p: { me: Me; env: Me["env"]; sampleData: boolean; footer: ReactNode;
  dock?: ReactNode /* rendered under the footer, centred min(880px,100%) */; children: ReactNode }): JSX.Element;
// components/shell/nav.ts
export type NavCountSource = "flow.in_flight" | "exceptions.open" | "review.queue" | "lab.candidates";
export type NavItem = { readonly href: string; readonly label: string; readonly code: string;
  readonly permission: string; readonly countSource?: NavCountSource };
export const NAV_ITEMS: readonly NavItem[];
export function visibleNav(me: Me): NavItem[];
// components/shell/nav-counts.ts (C)
export type NavCountHook = () => number | null;
export const NAV_COUNT_SOURCES: Readonly<Record<NavCountSource, NavCountHook>>;
// review.queue and lab.candidates ship as useNoCount (null); their owners replace that one entry.
// components/shell/command-palette.tsx (C)
export function useCommandPalette(): { open: () => void };
// lib/api/stream-paths.ts: STREAM_PATHS includes "/engine/stream"
```

API (additive): `GET /me` -> `MeResponse {subject, display_name, email, groups, roles, permissions, env: "local"|"dev"|"test"|"prod", sample_data: bool, access_request_url: str|null}`.
Consumed from engine-control-api (dep, pinned in split.md): `GET /engine/status` -> `EngineStatusOut {bus_healthy, total_lag, dlq_total, pollers: [{name, interval_seconds, last_beat_at, healthy}], region, consumer_group, ...}`; SSE `GET /engine/stream` event `status` (same shape). The footer reads only those fields and tolerates extra ones.

| Consumer | Contract | plannable |
|---|---|---|
| live-progress-dashboard | `GlassPanel/PanelHeader/PanelBody`, `KpiCard` ring/meter, `Pill`, `Meter`, `Segmented`, `StateCard`, `SkeletonRows`, `DataTable`, `TopBar` children slot; tokens/`--chart-*` | true |
| exceptions-workbench-restyle | `GlassPanel`, `Pill`, `FilterChip`, `Meter`, `DataTable.selectedRowId` + `meta.align`, `StateCard`, `SkeletonRows`, `TopBar`, `StatusBadge` via Pill (lock-banner/history-timeline restyle is theirs) | true |
| engine-control-panel-ui | `ConfirmDialog` (above; `confirmLabel`, `tone`, `expectedVersion`, `onConfirm({reason})`), `Pill`, `Meter`, `GlassPanel`, `DataTable`, `StateCard`, `TopBar`, `ActionButton` warn | true |
| settings-screen-redesign | `GlassPanel`, `Pill`, `DiffBlock`, `StateCard`, `TopBar`, `ConfirmDialog` | true |
| failed-receipt-review | `GlassPanel`, `Pill`, `Meter`, `DataTable`, `StateCard`, `TopBar`; nav: replace `NAV_COUNT_SOURCES["review.queue"]` | true |
| html-progress-reports | `GlassPanel`, `Pill`, `StateCard`, `TopBar`, `Segmented` | true |
| assistant-chat-redesign | `Pill`, `SuggestionChip`, `GlassPanel solid`, `StateCard`, `LiveDot`, `useShellSession`, `AppShell dock` slot (passed from `(shell)/layout.tsx`), `useCommandPalette` | true |
| matching-lab-ui | `GlassPanel`, `Pill`, `DiffBlock`, `ConfirmDialog`, `KpiCard`, `DataTable`, `StateCard`, `TopBar`; nav: replace `NAV_COUNT_SOURCES["lab.candidates"]` | true |

## Assumptions

- `/` redirects to `/dashboard`, which live-progress-dashboard creates; until it merges, `/dashboard` 404s on the sprint branch (expected; e2e uses `/flow`).
- `TopBar` is added (one line) to the four existing top-level pages so the shell is checkable; their restyle stories own everything else on those pages and keep that line.
- `sample_data` source: DB key `ui.sample_data` (admin-set, default false), never true in prod. `access_request_url` added to `/me` (DB key) to give the denied state's Request access link a target.
- Denied = `/me` succeeds with an empty `roles` list. API down = `getMe()` error with status 0, 502, 503 or 504.
- Env pill is warn tone for every env (AC6), replacing the old red PROD outline.
- The rail is composed by hand (not `ui/sidebar`) because the collapse breakpoint is 1024 px, not the sidebar's 768 px.
- Role label in the rail = highest role (ADMIN > OPERATOR > REVERSER > VIEWER), lower-cased.
- The footer's poller interval renders as minutes (`Nm`) when the interval is 60 s or more, else seconds (`Ns`); names map `receipt_watcher` to "receipt watcher".
