# glass-theme-shell: Glass Orbit tokens, shared components and the app shell

- Issue: #48
- breaking: false
- Design screen owned: **Shell** (`design/project/glass/Shell.dc.html`, design.md §1, §2, §4, §5, §7, §8)

## Story

As an operator of the cash app, I want one dark, techy "Glass Orbit" look applied through tokens and shared components, with a rail, top bar and status footer around every page, so that every screen looks the same and no page carries its own styling.

## Context

research.md a1: retheme through tokens only. design.md §8 is the exact translation (payroll-compare token block onto the shadcn variables in `web/app/globals.css`, `@theme inline` aliases, `.bg-blueprint`). design.md §4 lists the shared components; this story is their **one owner** (split.md "Shared owners"). Every other UI story imports them and never defines its own copy (CLAUDE.md non-negotiable 7). Existing shell: `web/components/shell/{app-shell.tsx,nav.ts,user-menu.tsx,env-badge.tsx,breadcrumbs.tsx,command-palette.tsx,flow-stream.tsx}`, `web/app/(shell)/layout.tsx`.

## Acceptance criteria

1. [unit] `web/app/globals.css` defines the raw tokens of design.md §1 (`--bg --s1 --s2 --s3 --tx --soft --faint --line --line2 --acc --acc-hi --acc-ink --acc-soft --ok/-ink/-soft --warn/-ink/-soft --err/-ink/-soft --dot --log --header --sh --sh-lg --scrim`) for light (`:root`) and dark (`.dark`) with the exact hex values, maps the shadcn variables as in §8.2 (dark `--primary: var(--acc)`), aliases `--status-*` as in §8.3, adds the `@theme inline` names of §8.4 and the `.bg-blueprint` utility of §8.5. A vitest reads the CSS and asserts every token name exists in both blocks.
2. [unit] `app/layout.tsx` uses `defaultTheme="dark"` (next-themes kept, light still selectable); fonts stay Geist Sans and Geist Mono; no Inter.
3. [unit] Shared components exist once under `web/components/common/` with typed props and vitest render tests: `glass-panel.tsx` (`GlassPanel`, `PanelHeader`, `PanelBody`), `pill.tsx` (`Pill` tones `ok|accent|warn|err|locked|muted`, `dot`, `mono`), `mono-label.tsx` (`MonoLabel`, the `.lab` style), `meter.tsx` (`Meter` value/max/tone, 5 or 6px), `segmented.tsx` (`Segmented` options/value/onChange, keyboard accessible), `filter-chip.tsx` (`FilterChip`, `SuggestionChip`), `confirm-dialog.tsx` (`ConfirmDialog` title/body/required reason textarea/"Recorded as <name · role> · <date> UTC · expected version N" line/confirm tone; returns `{reason}` on confirm; built on `ui/alert-dialog`), `diff-block.tsx` (`DiffBlock` lines `{op: "-"|"+"|" ", text}`), `skeleton-rows.tsx` (`SkeletonRows` with the shimmer gradient, reduced-motion safe), `state-card.tsx` (`StateCard` kind `loading|empty|error|denied`, label, headline, body, actions; error kind uses the err border). `kpi-card.tsx` is extended (mono 30px value, `ring` and `meter` variants, accent/warn tones) without breaking existing callers; `status-badge.tsx` maps the shared status enum to `Pill` tones (Applied ok, In progress accent, Awaiting receipt muted, Needs attention warn, Failed err, Locked locked); `data-table.tsx` gains the mono uppercase header, 10x12 cells, selected-row tint, right-aligned numeric columns and horizontal scroll.
4. [unit] `Button` gets a `warn` variant (outline warn tone, and a filled form for confirm actions) through `className`/cva in a common wrapper or a CLI re-add; `components/ui/*` is not hand-edited.
5. [unit] `nav.ts` holds the 8 entries in board order with two-letter codes (Dashboard DB, Flow FL, Exceptions EX, Engine EN, Review RV, Reports RP, Lab LB, Config CF), each with its required permission and an optional count source; `visibleNav` still filters by permission. `app/page.tsx` redirects to `/dashboard`.
6. [browser] Shell board: the app shell renders the dotted blueprint ground, the glass left rail (CA logo tile with glow, nav items with code chips and right-aligned mono counts for Flow in-flight and Exceptions open, active item with accent ring and glow, user row with initials avatar and role label) and a per-page glass `TopBar` (title, DEV/PROD env pill in warn tone, Live pill with glowing dot driven by the existing flow SSE connection, Sample data pill only when the API reports sample data, a right slot for page controls, search field with the ⌘K hint opening the existing command palette). Checked against the Shell board at 1440 wide.
7. [browser] Shell board: the glass `StatusFooter` shows Bus healthy/unhealthy pill, `lag N`, `dlq N` (warn when > 0), "Pollers 2/2 · intake Nm · receipt watcher Nm" and region `us-ashburn-1`, fed from `GET /engine/status` (engine-control-api) and refreshed by its SSE `status` event; when the call fails the footer shows "Bus status unavailable" and the page still works.
8. [browser] Shell board states: loading session (skeleton rail and bar), denied ("No role is mapped to your groups" with a Request access link), API down ("The cash app API is not answering. Pipeline workers keep running. Retrying in 8 seconds." with Retry now).
9. [browser] Shell board, responsive: at 375 px wide there is no horizontal page scroll; below 1024 px the rail collapses to a top bar with a menu button that opens it in `ui/sheet`; focus rings use the 4px accent halo; the live dot pulse respects `prefers-reduced-motion`.
10. [api] The existing `/me` (or `/health`) response gains `env` and `sample_data: bool` (additive) so the top bar can show the env and Sample data pills; OpenAPI regenerated (`npm run api:sync`).
11. [unit] `app/signed-out` and `app/auth/*` render on the dotted ground with the new tokens, logic unchanged.

## Out of scope

- Screen content of Dashboard, Engine, Exceptions, Review, Reports, Lab, Settings and the assistant (their own stories). The assistant dock is mounted by assistant-chat-redesign, not here.
- Nav counts for Review and Lab (added by failed-receipt-review and matching-lab-ui through the nav count source).
- Restyling Flow/Items pages (exceptions-workbench-restyle).

## Deps

- engine-control-api: `GET /engine/status` -> `EngineStatusOut {bus_healthy: bool, total_lag: int, dlq_total: int, pollers: [{name, interval_seconds, last_beat_at, healthy}], region: str, consumer_group: str}` and SSE `GET /engine/stream` event `status` with the same shape. plannable: true.

## Assumptions

- `DropZone` is owned by failed-receipt-review (its only first user), and the chat parts by assistant-chat-redesign; everything else in design.md §4 is owned here.
- `--radius` becomes 0.625rem (design.md §1). Light mode uses the payroll-compare light set (design.md §9).
- If `/me` already carries env, only `sample_data` is added; `sample_data` is true when the API is running against seeded/test data (planner pins the exact source, for example the `env` not being prod plus a seed marker).
