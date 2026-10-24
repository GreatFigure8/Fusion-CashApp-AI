# Design: Glass Orbit (direction B)

Picked by Jonathan: **B, Glass Orbit**. Refined dark glass on a blueprint dot ground, Geist and Geist Mono, electric-blue and teal accents, the assistant as a floating composer with chips on every screen.

Canvas open_url: https://claude.ai/artifact/NgfTaH1tfvxXVLaMVamDEc (published path `project/glass/`).

Exported boards (saved verbatim, `.dc.html` Claude Design board files) under `docs/sprints/bmn-ui-techy-redesign/design/project/glass/`:
Shell, Dashboard, Engine, Exceptions, Chat (assistant agent), Upload (Review), Lab, Reports, Settings. Also `project/Main.dc.html` and `project/canvas.json` (canvas layout). Every board loads `./support.js` (the Design runtime) which is not published in the artifact; it is not needed to build, the boards are the spec. The only external asset is Google Fonts Geist and Geist Mono, which this repo already ships through `next/font` (`app/layout.tsx`), so nothing is copied.

All figures on the boards are sample data. Board canvas is 1440 wide; every board also shows its empty, loading and error states (Engine, Chat, Lab also show permission/read-only states).

## 1. Tokens

The design is identical in value to the dark tokens of aix-payroll-compare (`D:\AIX-Payroll-Compare\webapp\src\app\globals.css`, the "ForgeOwn bench look"). The boards use raw hex; use the named tokens below.

### Colour (dark is the design; light uses the payroll-compare light set)

| Token (payroll-compare name) | Dark | Light (payroll-compare) | Used for |
|---|---|---|---|
| `--bg` | `#05060a` | `#f3f5f8` | page ground (with the dot grid) |
| `--s1` | `#0a0c11` | `#ffffff` | cards, rail (glass base) |
| `--s2` | `#0e1117` | `#f8f9fb` | composer, chips, confirm/result cards |
| `--s3` | `#151922` | `#eef1f5` | user bubble, inline code, kbd, avatar |
| `--tx` | `#e6eaf2` | `#0f1729` | text |
| `--soft` | `#8a94a6` | `#5a6b7f` | secondary text, labels |
| `--faint` | `#5d6778` | `#8a94a5` | nav counts, timestamps |
| `--line` | `#ffffff12` | `#0f172917` | hairlines, row dividers |
| `--line2` | `#ffffff1f` | `#0f172926` | card, input and chip borders |
| `--acc` | `#2f5bdb` | `#1e40af` | primary button, send button, logo tile |
| `--acc-hi` | `#4f7cff` | `#2563eb` | focus ring, active nav border, glow, meters |
| `--acc-ink` | `#9db8ff` | `#1e40af` | accent text, links, "Assistant" label |
| `--acc-soft` | `#4f7cff1f` | `#eff6ff` | active nav fill, selected chip/row |
| `--ok` / `-ink` / `-soft` | `#5fe6d8` / `#8cf2e7` / `#5fe6d817` | `#06b6d4` / `#0e5f7a` / `#ecfeff` | applied, live dot, healthy |
| `--warn` / `-ink` / `-soft` | `#ffc96b` / `#ffd98f` / `#ffc96b14` | `#f59e0b` / `#92400e` / `#fffbeb` | needs attention, paused, confirm card, DEV badge |
| `--err` / `-ink` / `-soft` | `#f87171` / `#fca5a5` / `#f8717117` | `#dc2626` / `#b91c1c` / `#fef2f2` | failed, dead letter, error cards |
| locked (violet) | `#b794ff` text `#d4bfff` bg `#b794ff1a` | existing `--status-locked` | locked by a person, audited/admin-only pills |
| `--dot` | `#ffffff12` | `#0f17291a` | blueprint dots |
| `--log` | `#07090d` | `#f7f9fc` | log/code well (not on the boards; reserved for artifact viewer) |

Pill backgrounds are the `-soft` tokens, pill text the `-ink` tokens. Muted pill: `#ffffff0d` bg, `--tx`-at-70% text (`#a9b2c3`, treat as `--soft` lightened; use `text-muted-foreground`). Secondary text on dark that the boards write as `#a9b2c3` maps to `--soft` (`#8a94a6`) or `text-foreground/80`; the board has two greys (`#a9b2c3` body-secondary, `#8a94a6` labels), keep both via `text-foreground/70` and `text-muted-foreground`.

The boards are dark only. The app keeps `next-themes` (default system); light mode is the payroll-compare light set above, an assumption (see section 9).

### Type

- Sans: Geist (`--font-sans`), 14px body, line-height 1.5. Headings 18 to 20px / 600 / letter-spacing -0.01em (page title in the top bar 18px, card title 20px).
- Mono: Geist Mono (`--font-mono`) for every number, money amount, id, status code, key, tool name, timestamp, table header and label.
- Label (`.lab`): Geist Mono 11px, uppercase, letter-spacing 0.08em, `--soft`.
- Table header: Geist Mono 11px, uppercase, 0.06em, `--soft`.
- KPI number (`.big`): Geist Mono 30px / 500 / -0.02em (40px in the shell specimen; 20px for per-currency amounts and mini stats).
- Chat: user bubble 15.5px / 1.6; assistant markdown 14px / 1.7; tool name 12.5px mono; kbd/hint row 10.75px mono uppercase 0.04em; composer textarea 15px / 1.6.
- Chips 13px (12.5px on the exceptions filter row). Buttons 13px / 500 (12.5px on dense engine cards).
- Payroll-compare scales Tailwind's ramp by 1.0625 (text-xs 12.75px). This repo keeps the stock ramp; use arbitrary sizes `text-[11px]`, `text-[12.5px]` or add `--text-label: 0.6875rem` in `@theme inline`. Decision: add the semantic utilities in section 8 instead of one-offs.

### Spacing, radius, shadow

- Spacing: 4px base; page padding 16, gap between panels 16, card header 14x18, card body 16x18, table cell 10x12 (8x12 header), chip 5x12 or 6x14, nav item 8x10 with min-height 40, touch targets 32 to 40.
- Radius: glass panel 16, inner card and result cards 12, buttons and inputs 10 (dense 9), nav item 10, code tag 6, pills fully round, KPI meter 3, composer 16, send button 8. `--radius` becomes 0.625rem (10px) so shadcn `rounded-lg` is 10 and `rounded-2xl` is about 18; panels use `rounded-2xl` or an explicit `rounded-[16px]`.
- Glass: `background #0a0c11b8` (s1 at 72%), `backdrop-filter: blur(14px)`, `border 1px --line2`, shadow `0 1px 0 #ffffff0a inset, 0 30px 80px -30px #000000e6` (= payroll-compare `--sh-lg`).
- Panel (non-glass, e.g. chat surface): solid `--s1`, same border, no blur.
- Glow: primary button `0 0 24px -8px #4f7cff`; active nav `inset 0 0 0 1px #4f7cff66, 0 0 28px -10px #4f7cff`; live dot `0 0 10px #5fe6d8`; logo tile `0 0 20px -4px #4f7cff`; selected sheet `0 0 0 1px #4f7cff55, 0 30px 80px -30px #000, 0 0 60px -30px #4f7cff`; composer focus halo `0 0 0 4px #4f7cff1f`; confirm card `0 0 40px -22px #ffc96b` with border `#ffc96b66`.

### The blueprint dot ground

Page background `--bg` plus `radial-gradient(circle, var(--dot) 1.4px, transparent 1.6px)`, `background-size: 22px 22px`. This is the existing payroll-compare `.bg-blueprint` utility; copy it as is. Apply it to the app shell root (the area behind floating panels), never to the panels.

## 2. Shell (replaces `components/shell/app-shell.tsx`, `nav.ts`, `(shell)/layout.tsx`)

Layout: dotted ground with 16px padding; a flex-wrap row: **left rail** (glass, `flex 1 1 200px`) and **main** column (`flex 999 1 560px`, `min-width:0`, gap 16). Under both: a **status footer** (glass strip), then the **assistant dock** (centered, `min(880px,100%)`).

- Rail: brand row (28px rounded-8 `--acc` tile "CA" in mono with glow, "CashApp" 600, mono label "AI" right). Nav items: a 26x22 mono two-letter code chip (DB FL EX EN RV RP LB CF), label, right-aligned mono count in `--faint`. Active item: `--acc-soft` fill, `--acc-ink` text, accent inset ring + glow, code chip border `--acc-hi`. Hover `#ffffff0a`. Bottom: user row (28px circular initials avatar, name 13px, role in 10px mono uppercase label) separated by a hairline.
- Nav entries (8): Dashboard `DB`, Flow `FL` (count = in-flight), Exceptions `EX` (open exceptions), Engine `EN`, Review `RV` (review queue), Reports `RP`, Lab `LB` (candidates), Config `CF`. Entries are permission-filtered as today (`visibleNav`).
- Top bar (glass, per page): page title 18/600, `DEV`/`PROD` env pill (warn tone, mono), `Live` pill with glowing dot (SSE connected), `Sample data` muted pill (dev only, removed when real), page controls right (window segmented control, search, toggles). Shell specimen shows a search field with `⌘K` kbd hint (opens existing `command-palette.tsx`).
- Status footer: `Bus healthy` pill (ok, dot), `lag 312`, `dlq 4` (warn mono), "Pollers 2/2 · intake 2m · receipt watcher 5m", right-aligned region `us-ashburn-1`. Fed from the engine status stream.
- Assistant dock: on every screen, see section 6.
- Mobile: rail collapses (see section 7).

Existing → new mapping:
- `components/shell/app-shell.tsx` → rewritten (rail + top bar + footer + dock); `nav.ts` → add Dashboard, Engine, Review, Lab, entries and codes; `user-menu.tsx`, `env-badge.tsx`, `breadcrumbs.tsx`, `command-palette.tsx`, `flow-stream.tsx` kept, restyled. shadcn `sidebar` primitive can host the rail.
- `app/(shell)/layout.tsx` → mounts the shell and the assistant dock once (not per page).
- `app/signed-out`, `app/auth/*` unchanged logic, restyled on the dotted ground.
- Shell states: loading session (skeleton rail + bar), "No role is mapped to your groups" with "Request access" link (empty/denied), "The cash app API is not answering. Pipeline workers keep running. Retrying in 8 seconds." with Retry now (error).

## 3. Screens

Common: every screen = top bar + panels; each card has a `.hd` header (title 600 left, mono label or pills right, bottom hairline) and `.bd` body. All money is mono and never summed across currencies. Statuses use the pill set from section 4.

### 3.1 Dashboard (`/dashboard`, new; becomes the landing route, `app/page.tsx` redirects to it instead of `/flow`)
- Top bar: "Progress", env, Live, Sample data, window segmented control `24h | 7d | 30d` (mono 11px, active `#4f7cff2e` fill).
- KPI row (grid auto-fit min 200): Receipts matched (30px mono, subtitle "Reserved and at least one line applied"); Automation rate as a 72px SVG ring (stroke `--acc-hi`, track `#ffffff14`) with 87.4% and "no human touch"; Awaiting receipt (accent colour, "Oldest 11d of 30d aging"); Open exceptions (warn colour, "12 locked · 4 dead-lettered").
- Money applied by currency: one tile per currency (label, 20px mono amount, "N receipts · residual X"). Never a cross-currency total.
- Two-up: Throughput area chart (24h, applied = `--acc-hi` line with 13% fill, escalated = `--warn` dashed, legend + "peak 61/h"); Auto-fix outcomes table (error code mono, count, 6px meter coloured `--ok` when rate > 60% else `--warn`, "84% fixed").
- Live activity feed: timestamped rows with a pill (Applied / Receipt arrived / Auto-fix / Escalated) and text; header pill "Streaming · 1 s ago".
- Model efficiency table: Role, Model (mono, accent), Calls, Cost, Cost unknown, Agreement, Human corr., Accuracy ("96.8% · n 212" and only where people corrected); footer pills: auto-fix rate, human-correction rate, Cohere cluster utilisation.
- States: loading (KPI skeletons + block), empty ("Nothing completed in this window", Show 30 days / Open Flow), error ("Couldn't load the aggregates", tiles marked stale with last-good time, Retry).
- Existing to reuse: `common/kpi-card.tsx` (extend: ring variant, mono value, accent), `common/live-indicator.tsx`, `common/money.tsx`, `common/data-table.tsx`, `components/flow/sparkline.tsx`, `ui/chart.tsx` (recharts). New: `components/dashboard/*` (money-by-currency, throughput-chart, autofix-table, model-efficiency-table, activity-feed), `app/(shell)/dashboard/page.tsx`. API: new aggregates router (llm_usage.py and reports.py are the nearest).

### 3.2 Flow (`/flow`, `/flow/[stage]`, restyle only)
Not a board; take the Glass look: stage tiles become `.sc` cards (see Engine), backlog bar the 5px meter. `components/flow/stage-tile.tsx`, `backlog-bar.tsx`, `flow-monitor.tsx`, `stage-items-table.tsx` restyled via tokens. Assumption (section 9).

### 3.3 Engine (`/engine`, new, admin or operator)
- Top bar: "Engine", env, Live, "Lag streamed · updated 1 s ago", `Admin only · audited` (locked tone pill), "Fusion reads · MCP healthy 180 ms" (ok pill), right: "OCI Streaming · group cashapp-dev".
- Stations card: header pills "11 running · 1 paused · 1 draining". Grid auto-fill min 210. Station card: mono name + state pill; row `lag N · N/min · dlq N`; 5px in-flight bar (`--acc-hi`, `--warn` when saturated), "in-flight 7 / 16"; buttons `Pause|Resume` (warn style) and `Drain`. Paused card border `#ffc96b66`. 12 stations: intake, classify, extract.reader_a, extract.reader_b, adjudicate, validate, resolve_customer, match_receipt, await_receipt, match_lines, apply, write_back.
- Throttle card (config v41): range sliders `concurrency.per_stage` (1 to 32), `concurrency.apply_per_receipt` (1 to 8, helper "Fusion applies take about 6 s a line; this is the back-pressure."), accent `--acc-hi`, "Save throttle…".
- Audit card: who · when · why list (time mono 44px column, name 500, reason quoted in `--soft`).
- Dead-letter queue: table with checkbox, event id, stage, item link, error pill (mono, err tone), attempts, dead-since; header pill "4 events" and primary "Replay 2 selected…".
- Pause dialog (modal over the main column with scrim `#05060ab3` + 2px blur): title "Pause the apply station?", body explains in-flight finish and nothing is lost, required Reason textarea, audit line "Recorded as <name · role> · <date> UTC · expected version 41", Cancel + warn-filled "Pause apply". Pattern applies to Drain, Throttle save, Replay.
- States: loading (card skeletons "Reading consumer lag…"), empty DLQ ("No dead letters", "Every event is inside its retry budget."), error ("Bus health unavailable", controls disabled, Retry), operator view (read-only: controls disabled with "needs admin").
- New: `app/(shell)/engine/page.tsx`, `components/engine/*` (station-card, throttle-panel, audit-list, dlq-table, confirm-dialog using `ui/alert-dialog` or `ui/dialog`). New API router for engine control; optimistic expected-version check. No third poller: it controls event flow only.

### 3.4 Exceptions (`/exceptions`, replaces/restyles `app/(shell)/exceptions/page.tsx` and `components/exceptions/*`)
- Top bar: "Exceptions", env, Live, Sample data, checkbox "Show applied items" (default off).
- Filter chips (pill buttons, active = `--acc-hi` border + `--acc-soft`): All 63, Ambiguous receipt 14, Amount variance 11, Invoice not found 17, Customer not found 6, Always a person 9, Locked 12.
- Split: list (glass table, `flex 999 1 480`) + detail sheet (`flex 1 1 420`, accent-glow border). Table cols Item (mono), Payer (masked `[Payer 0142]` style kept), Amount (mono, currency-prefixed, right), Reason (pill: warn/err/locked tone), Age, lock owner ("You", name). Selected row `#4f7cff14`. Footer "63 exceptions · 1,221 applied items hidden".
- Sheet: header (mono item id + amount, human reason line, close); lock banner ("Locked by you since 14:05. Automation won't act on this item."); "Why it's stuck" with the candidate receipts as two bordered tiles; "Auto-fixes tried 3 of 3" vertical timeline (10px nodes, step text, result and time in `--soft`, final "Escalated to a person"); Lines editor (invoice input, amount input, source pill `A+B` ok / `A` muted); receipt selector; actions: primary "Requeue to match receipt", "Unlock", "Full history" link.
- States: loading (row skeletons), empty ("No exceptions right now … Applied items stay hidden unless you show them."), error lock conflict ("M. Okafor locked this item first", View read-only).
- Existing to restyle, not rewrite: `exceptions-table.tsx`, `exceptions-filter-bar.tsx`, `exception-sheet.tsx` (uses `ui/sheet`; on desktop keep as an inline split panel, on narrow screens a sheet), `why-stuck.tsx`, `autofix-list.tsx`, `edit-form.tsx`, `receipt-picker.tsx`, `lock-controls.tsx`, `empty-states.tsx`, `common/lock-banner.tsx`, `common/history-timeline.tsx`, `common/status-badge.tsx`. `app/(shell)/items/[id]` stays the full-history page.

### 3.5 Assistant (full screen `/assistant`, plus the dock everywhere; see section 6)
New: `app/(shell)/assistant/page.tsx`. Replaces/extends `common/llm-chat.tsx` and `common/llm-chat/*` (composer, message-list, action-chips, suggestions, chat-reducer, chat-status, use-chat); this stays the single shared chat component, configured by props (context, system prompt key, tools, chips).

### 3.6 Review (`/review`, new: failed-receipt image submission)
- Top bar: "Review", env, Sample data, "Today 7 / 20 uploads" quota.
- Upload panel (glass): dashed drop zone ("Drop failed receipt images", "PNG, JPG, WEBP or PDF · up to 5 MB each · 10 files at a time · location data is stripped", "Choose files" button, hidden `<input type=file multiple>`). Thumbnails row: faux image with name, size (mono), 4px progress bar, status pill (Stored ok / Uploading 62% accent / Duplicate of WI-… locked / Over 5 MB err / Not an image err). Actions: Clear, primary "Submit N for in-depth review".
- Two columns: Review queue table (Item, File, Stage mono, Status pill, Age; "same stations · high effort") and the result panel for the selected item: preview with highlighted amount region (caption "page 1 · amount"), field table (Field, Value, Source pill `A = B` ok / `A, B differed` warn / `B only` muted), an adjudication note ("Reader B read 7,412.80 from blurred cents; the adjudicator took Reader A."), applied line ("Applied to RCPT-88231 · 2 lines · residual 0.00"), links Open item / History. Header pill "Applied · 0.94".
- States: empty queue, loading result ("Both readers done, adjudicating…"), upload error ("scan_big.png is over 5 MB. The other files were kept.").
- New: `app/(shell)/review/page.tsx`, `components/review/*` (drop-zone, upload-list, queue-table, result-panel), `app/api/review/...` Next proxy route, new API router + intake path. Reuse `common/artifact-viewer*` for the preview and `common/status-badge`.

### 3.7 Lab (`/lab`, new)
- Top bar: "Matching Lab", env, `Read-only replay` (locked pill), Sample data, "Replays never call Fusion".
- Split: left Lab assistant (the shared chat in `compact` config: header "Lab assistant · Connected · Haiku 5.5", one tool chip `matching.*`, hints ↵ and /); right results column:
  - Candidate card: "Candidate p_0192 vs live v41", "Replay complete · 42 s", pill "1,912 items · 30 days", config diff (mono; `− 5` red-tint line, `+ 3` green-tint line).
  - Four comparison tiles: Match differently 41, Newly matched +19, Newly failed +3, Newly ambiguous 0.
  - Money affected by currency table (Currency, Newly matched, Newly unmatched, Items).
  - Items that change table (Item, Amount, Before pill, After pill; Export CSV link).
  - Promote to live: pills "Replay ran on current v41", "You can write config", required Reason input, primary "Promote p_0192", Discard, audit caption "Records J. Stevenson · replay rp_3381 · expected version 41".
- States: empty ("No candidate yet"), loading (progress bar "1,140 of 1,912 items"), error stale ("Live config moved to v42. Promote is blocked until you replay against the new version.", Replay again), no permission ("Replay only … Promote needs config write.").
- New: `app/(shell)/lab/page.tsx`, `components/lab/*`; API lab router (replay, promote). Promote goes through the same config write as Settings.

### 3.8 Reports (`/reports`, replaces `app/(shell)/reports/page.tsx` and `components/reports/*`)
- Top bar: "Reports", env, Sample data, "Preview updates live".
- Split: form column (Build a report: Report select [Progress summary | Exceptions aging | Model efficiency], Window select [7d | 30d | MTD], Sections checkboxes [Headline numbers, Money by currency, Throughput, Exceptions by reason, Model efficiency], primary "Export HTML", caption "A single self-contained file with inline styles and no scripts. Safe to email."; Recent exports list: filename mono, who · when) and a **Preview** glass panel containing an `article.doc` that is the export document (light paper styling: title "Cash application progress", range, generated stamp, 4 headline numbers, money-by-currency table, daily throughput SVG, footnote on accuracy/cost caveats; "As of 14:02 UTC").
- The exported HTML is its own light, print-safe stylesheet, independent of the app theme.
- States: loading preview, empty ("Nothing to report yet", export disabled), error ("The export didn't finish … No file was created.", Try again).
- Existing: keep `components/reports/*` where they still apply (aging-table, failures-by-code-chart, daily-summary-*, export-buttons, partially-paid-*); restyle through tokens; `app/api/reports/[report]/export/route.ts` stays and gains the HTML export.

### 3.9 Settings (`/config`, replaces/restyles `app/(shell)/config/page.tsx` and `components/config/*`)
- Top bar: "Settings", env, pill "Stored in the database · v41", key search field.
- Split: left group nav (glass; Matching 9, Pollers 2, Concurrency 3, Models 8, Extraction 5, Auto-fix 12, Aging 3, Uploads 4, Access 3, fusion-sql-mcp 4) with a note "Only the database connection lives outside the database, in Vault. Every other setting is here, versioned and audited."; right body:
  - Group card (e.g. Matching) with header pill "1 unsaved change"; rows: mono key + help text, value input (dirty = accent border), last-changed ("2 Oct · J. Stevenson" / "seed" / "unsaved"); footer: diff summary `tolerance.CAD 0.10 → 0.15`, required reason input, Revert, primary "Save as v42".
  - **fusion-sql-mcp connection card** (below): header label "Connection" + "fusion-sql-mcp · Fusion reads", pill "Healthy · 180 ms"; body: `mcp.server_url` input (`https://greenlight-dev.internal:8000/mcp`), facts row (OAuth client `cashapp-dev`, "Secret in OCI Vault", Source `fusion dev-1`, "Last call 14:02:08 · run_query · 64 rows"), explanatory text ("Used for receipt search, invoice and credit memo lookups, lab replays and the assistant's read-only queries. Applying receipts stays on the direct Fusion client."), "Test connection" button with result line "Token valid · 6 tools · fusion_rest_get 210 ms".
  - Access: groups to roles table (CASHAPP_ADMINS Admin, CASHAPP_OPERATORS Operator, AR_ANALYSTS Viewer, with "Can" text) + "Map a group".
  - Change history: version, when · who, key old → new, quoted reason.
- States: loading, empty search ("No setting matches 'tolerence'. Did you mean tolerance?"), error conflict ("Someone saved v42 first. Your edit is kept.", Review the difference), error invalid ("tolerance.CAD must be 0.00 to 1.00 … Nothing was saved.").
- Existing: `config-tabs.tsx` → group nav; `setting-row.tsx`, `settings-panel.tsx`, `save-footer.tsx`, `review-dialog.tsx`, `history-list.tsx`/`history-sheet.tsx`, `access-panel.tsx`, `editors/*`, `config-staging-provider.tsx`/`staging.ts` kept; add `mcp-connection-card.tsx`. The MCP client secret stays in Vault; only the URL, client id and source are DB settings.

## 4. Components

Build once in `components/common/` (no per-page copies), expressed as Tailwind utilities over the tokens in section 8:

- `GlassPanel` (+ `PanelHeader`, `PanelBody`) wraps shadcn `Card` (`ui/card`), adds blur, border `--line2`, `--shadow-float`. Everything bordered on a screen is this.
- `Pill` / extend `status-badge.tsx`: tones `ok | accent | warn | err | locked | muted`, optional glowing dot, optional mono. Status enum mapping (one shared status enum; unchanged in the API): Applied → ok, In progress → accent, Awaiting receipt → muted, Needs attention → warn, Failed → err, Locked → locked. Keep `--status-*` shadcn vars aliased to these tokens so existing `status-badge` keeps working.
- `Label` (`.lab`): mono uppercase micro-label.
- `KpiCard` (extend): value mono 30px, label, delta/subtitle, `ring` and `meter` variants.
- `Meter` (5/6px bar with glow) and `Segmented` control (window selector).
- `NavRail`, `TopBar`, `StatusFooter` (shell).
- `DataTable` (extend): mono uppercase header, 10x12 cells, selected-row tint, numeric cols right/mono, horizontally scrollable on narrow.
- `FilterChip` (12.5px pill toggle) and `SuggestionChip` (13px pill, used by the assistant).
- `ConfirmDialog` (audited action: reason textarea + "Recorded as…" line + expected version).
- `DropZone`, `Timeline` (existing `history-timeline`), `DiffBlock`, `EmptyState`, `ErrorAlert`, `Skeleton` rows (`linear-gradient(90deg,#ffffff08,#ffffff14,#ffffff08)`, 12px, radius 6).
- Assistant parts: see section 6 (all inside `common/llm-chat/`).

shadcn primitives stay from the CLI (`components/ui` untouched except via CLI re-add); restyle through CSS vars and `className` in the common wrappers.

## 5. Empty, loading and error states

Every screen defines three (some a fourth). Consistent shape: a glass card `min-height 170 to 200`, mono label naming the state ("Loading", "Empty", "Error · cause", "Denied"), a 17px/600 headline, 13px `--soft` body, then at most one or two actions.
- Loading: skeletons shaped like the real content (KPI row, table rows, station grid), with a short caption of what is being read ("Reading consumer lag…", "Both readers done, adjudicating…"). Long jobs show a progress bar plus mono counts.
- Empty: say why it is empty and what to do next; never a bare "No data".
- Error: err-tinted border (`#f8717155`), label in `--err-ink`, say what still works ("Pipeline workers keep running", "Tiles show values from 13:57 UTC and are marked stale", "Nothing changed", "No file was created"), Retry. Conflicts keep the user's edit.
- Denied/read-only: controls stay visible but disabled with the permission named ("Pause · needs admin"); the assistant offers to draft the change for an admin.
Maps to `common/empty-state.tsx`, `common/error-alert.tsx`, `ui/skeleton.tsx`, `common/require-permission.tsx`, and `app/**/loading.tsx` / `error.tsx`.

## 6. The assistant

The same `common/llm-chat` component renders in three placements, configured by props (`context`, `systemPromptKey`, `tools`, `chips`, `variant: dock | page | compact`):
1. **Dock** on every screen (glass-free solid composer, floating, centered, `min(880px,100%)`).
2. **Full screen** `/assistant`.
3. **Compact** inside the Lab split.

**Floating composer (dock):** row of suggestion chips above (pill, `--s2` fill, `--line2` border, 13px, min-height 34, centered, wrap), then the composer: `--s2`, 16px radius, border `--line2`, halo `0 0 0 4px #4f7cff1f` plus drop shadow; inline mono accent label "ASSISTANT", single-line input 15px ("Ask or tell CashApp to do something…"), "Full screen" link (opens `/assistant` keeping the thread), 32px `--acc` send button (radius 8, arrow-up icon). Below: centered hint "Acts with your permissions · every change asks you to confirm · ⌘K". Chips are context-aware per route, e.g. "Where are items waiting longest?", "Pause apply until 15:00", "Export this week's report". On narrow screens the dock is pinned to the viewport bottom and the chips scroll horizontally.

**Full chat (payroll-compare structure, recoloured):**
- Header 40px, bottom hairline, mono uppercase 11.75px: "Assistant", Connected (glowing dot), model "Haiku 5.5 · zero retention", "Acting as J. Stevenson · admin".
- Thread: centered column max 880, padding 24x16, gap 18. **User message**: right-aligned bubble, `--s3` fill, `--line2` border, radius 12, max 78%, 15.5px. **Assistant text**: markdown, 14px/1.7, inline code mono on `--s3`.
- **Tool-activity rows**: grouped in a bordered strip (top/bottom hairlines, full bleed), each row: icon, mono tool name in `--tx` (`engine.status`, `engine.pause`, `metrics.read`, `fusion-sql-mcp · query`, `lab.replay`, `reports.export`), one-line description in `--soft` ("apply is running, 7 in flight"; "Read-only: INR receipts created in the last 7 days, 64 rows"), right-aligned mono duration. A running tool shows a pulsing dot and live progress ("1,140 of 1,912 items"). A tool waiting for the user reads "waiting for your confirmation".
- **Confirm card** (mutations only): warn-tinted border + glow, header label "CONFIRM A CHANGE" + "Audited" pill; key/value grid (What, Before, After, Who, Reason), buttons warn-filled **Confirm** and **Cancel**. Nothing mutating runs without it; the tool row stays "waiting" until pressed.
- **Result cards**: bordered `--s2` cards: state card (title + status pill + mini-stats grid, e.g. Apply station: In flight 3 → 0, Waiting 96, Resumes 15:00, History id); replay card (Changed, Newly matched +19, Newly failed +3, INR affected; actions "Promote…", "Discard", link "Open in Lab"); export card (file chip, mono filename, "84 KB · self-contained", Preview, Download).
- **Composer**: chips row above (`Where is time lost between stations?`, `Which auto-fix fails most?`, `Is the Cohere cluster oversized?`, `Work my oldest exception`), box with textarea (min 48px, 15px), toolbar row: `+` attach images (receipt images go to Review), a muted pill listing available tool groups ("Engine · Lab · Settings · Reports · Review · Exceptions · Fusion reads"), spacer, 32px send. Hint row (mono 10.75px, kbd chips): `↵` Send, `Ctrl+↵` New line, `/` Prompts, `+` Images, "Changes run only after you confirm".
- **Live context panel** (right, `flex 1 1 280`): live values (automation 7d, open exceptions, bus lag, apply status, Fusion reads status) and "Your tools" list with Allowed/Denied pills per tool group, footnote "The assistant can never do more than your role allows."
- **States:** empty welcome ("What should CashApp do?" + chips Show live progress / Pause a station / Submit failed receipts); loading tool running (pulsing dot + progress); error tool failed ("engine.pause returned 409 … Nothing changed."); denied ("Settings changes need config write. You're an operator. The assistant can draft the change for an admin.").
- Behaviour contract (from the story, restated): Haiku workhorse, structured outputs, zero retention; every chat action is a tool call executed by the same services with the user's Principal; the chat can never exceed the user's permissions.

Existing mapping: `common/llm-chat.tsx` + `llm-chat/{composer,message-list,action-chips,suggestions,assistant-markdown,chat-status,chat-reducer,chat-schemas,use-chat,defaults}.tsx` restyled and extended with: `tool-activity.tsx`, `confirm-card.tsx`, `result-cards.tsx` (state, replay, export), `live-context.tsx`, `dock.tsx`. `action-chips.tsx` is the chips row; `chat-status.tsx` is the header. API: existing `chat.py` gains the tool-calling surface (SSE).

## 7. Responsive behaviour

The boards are 1440 wide and use intrinsic wrapping rather than media queries. Reproduce that:
- Shell: rail `flex 1 1 200px`, main `flex 999 1 560px`. When the viewport cannot fit both (about < 800px), the rail wraps above main. Assumption: below 1024 collapse the rail to a top bar with a menu button opening it as a `ui/sheet`; dock pins to the bottom with horizontally scrolling chips and the composer shrinks to one line.
- KPI and station grids: `repeat(auto-fit, minmax(200px, 1fr))` (stations `auto-fill minmax(210px,1fr)`, currency tiles 170, comparison tiles 150).
- Two-up cards: `auto-fit minmax(400px, 1fr)` (340 on Engine/Shell), becoming a single column under about 420px.
- Exceptions split: list `flex 999 1 480` + sheet `flex 1 1 420`; on narrow viewports the detail opens as a full-width sheet.
- Tables: horizontally scrollable inside the card (`overflow-x:auto`, `white-space:nowrap` cells).
- Lab and Reports splits wrap (chat or form first, results or preview below).
- Chat thread max 880 and centred; user bubble max 78%; live-context panel drops under the thread.
- Touch targets stay 32 to 40px; focus uses the 4px accent halo; respect `prefers-reduced-motion` for the live dot pulse, skeleton shimmer and the assistant "breathe".

## 8. Translation: payroll-compare tokens and classes → this repo (Tailwind v4 + shadcn base-nova)

Source: `D:\AIX-Payroll-Compare\webapp\src\app\globals.css`. This repo's `web/app/globals.css` today is neutral oklch with `--status-*`. The change is to adopt the payroll-compare token layer, mapped onto the existing shadcn variables.

1. **Raw tokens** (`:root` light and `.dark`): add `--bg --s1 --s2 --s3 --tx --soft --faint --line --line2 --acc --acc-hi --acc-ink --acc-soft --ok --ok-ink --ok-soft --warn --warn-ink --warn-soft --err --err-ink --err-soft --dot --log --header --sh --sh-lg --scrim` with the exact values of section 1 (hex, no oklch conversion needed; Tailwind v4 accepts them).
2. **shadcn mapping** (keep the variable names the generated `components/ui/*` read): `--background:var(--bg) --foreground:var(--tx) --card:var(--s1) --popover:var(--s1) --primary:var(--acc-hi)` (dark: `var(--acc)` so white text on buttons stays ≥ 4.5:1, as payroll-compare does) `--primary-foreground:#fff --secondary/--muted/--accent:var(--s3) --muted-foreground:var(--soft) --destructive:var(--err) --border:var(--line) --input:var(--line2) --ring:var(--acc-hi) --chart-1:var(--acc-hi) --chart-2:var(--ok) --chart-3:var(--warn) --chart-4:var(--err) --chart-5:var(--soft) --radius:0.625rem` (payroll-compare 0.5rem; the glass boards use 10/16, so 0.625rem is the assumption), sidebar vars as in payroll-compare.
3. **Keep and alias** the repo's status vars so `status-badge`, flow tiles etc. keep working: `--status-success:var(--ok) --status-progress:var(--acc-hi) --status-waiting:var(--soft) --status-attention:var(--warn) --status-error:var(--err) --status-locked:#b794ff` (light: existing violet).
4. **`@theme inline`** additions (payroll-compare names): `--color-surface-1/2/3`, `--color-line`, `--color-line-strong`, `--color-faint`, `--color-brand(-hi|-ink|-soft)`, `--color-ok(-ink|-soft)`, `--color-warn(-ink|-soft)`, `--color-err(-ink|-soft)`, `--color-log`, `--color-header`, `--color-scrim`, `--shadow-panel:var(--sh)`, `--shadow-float:var(--sh-lg)`, `--font-mono:var(--font-geist-mono)`, `--animate-breathe`. This yields the classes the boards imply: `bg-surface-1/2/3`, `border-line`, `border-line-strong`, `text-faint`, `text-brand-ink`, `bg-brand-soft`, `text-ok-ink bg-ok-soft`, `text-warn-ink`, `text-err-ink`, `shadow-float`, `font-mono`.
5. **`.bg-blueprint` utility**: copy verbatim (22px dot grid, 1.4px dots) and put it on the shell root.
6. **Board class → Tailwind/shared component**:
   - `.glass` → `GlassPanel`: `rounded-2xl border border-line-strong bg-surface-1/70 backdrop-blur-[14px] shadow-float`.
   - `.lab` → `Label`: `font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground`.
   - `.pill` + `.ok .wa .er .ac .mu .lk` → `Pill` tones: `bg-ok-soft text-ok-ink`, `bg-warn-soft text-warn-ink`, `bg-err-soft text-err-ink`, `bg-brand-soft text-brand-ink`, `bg-white/5 text-muted-foreground`, locked `bg-[#b794ff1a] text-[#d4bfff]`.
   - `.btn` → shadcn `Button` `outline`; `.btn.pri` → `default` + `shadow-[0_0_24px_-8px_var(--acc-hi)]`; `.btn.warn` → new `warn` variant (outline in warn tone; filled `bg-warn text-[#1b1300]` for the confirm action).
   - `.nav`, `.nav.on`, `.code` → shadcn `sidebar` menu button classes with `data-[active=true]` ring + glow.
   - `.t` table → `ui/table` + `DataTable` header/cell classes.
   - `.chip`, `.chip.on` → `FilterChip`/`SuggestionChip`. `.seg` → `Segmented` (or `ui/tabs` pill style).
   - `.kpi`, `.big` → `KpiCard`. `.sk` → `ui/skeleton` with the shimmer gradient. `.dot` → `LiveDot` (`bg-ok shadow-[0_0_10px_var(--ok)]`).
   - `.card`, `.cardh`, `.kv`, `.mini`, `.mv` (chat) → `ResultCard`, `ConfirmCard` pieces.
   - `.ub`, `.act`, `.tool`, `.md`, `.comp`, `.box`, `.send`, `.hints`, `.k` (kbd) → `llm-chat` parts as in section 6.
   - `.step`, `.node` → `common/history-timeline` / `autofix-list`.
7. **Fonts**: the boards use Geist for body and Geist Mono. This repo already loads Geist Sans and Mono in `app/layout.tsx`; do not adopt payroll-compare's Inter. Payroll-compare's 1.0625 type scale is not adopted.
8. **Dark by default**: boards are dark. `next-themes` stays; recommend `defaultTheme="dark"` for the redesign (assumption, section 9).

## 9. Assumptions and open points (design leaves these open)

- Light theme is not on the boards; it uses the payroll-compare light token set. Contrast of the dark `--primary` fix is inherited from there.
- Flow monitor (`/flow`, `/flow/[stage]`) and item detail (`/items/[id]`) have no board; they are restyled with the Glass tokens and shared components, not redesigned.
- Responsive: the boards define only intrinsic wrapping at desktop; the < 1024 rail collapse, bottom-pinned dock, and mobile sheet for the exceptions detail are assumptions.
- `Dashboard` becomes the post-login landing page (the repo currently redirects `/` to Flow). Nav order follows the boards: Dashboard, Flow, Exceptions, Engine, Review, Reports, Lab, Config.
- Engine permission: boards show "Admin only · audited" and an operator read-only state; exact permission keys (for example `engine:control`) are a plan decision. Same for Lab promote (config write) and Review upload.
- The assistant dock appears on every screen, including Settings; the Lab has its own compact assistant in place of the dock chat (the dock still exists on that screen as on the others; the board shows it).
- "Sample data" pill and all figures are placeholders; the pill is shown only when the API reports seeded/non-real data.
- Quota text on Review ("7 / 20 uploads today"), upload limits (5 MB, 10 files, strip location data), and image formats are taken from the board copy and are config values, not constants.
- Accuracy is displayed only where people corrected (n shown); "Cost unknown" is shown, never imputed.
- The assistant connect/health row and `fusion-sql-mcp` health pill are driven by the settings connection test; the boards show 180 ms and 6 tools as sample values.
- Money pill/amount format: `CCY 1,234.00` mono, 2 decimals, currency always adjacent; INR groups in thousands as shown (no lakh grouping on the boards).
- Dock "Full screen" opens `/assistant` with the same thread; thread persistence is an API decision.
- Fonts via Google Fonts on the boards are only a canvas artefact.
