# exceptions-workbench-restyle: Exceptions workbench, Flow and item pages in the Glass look

- Issue: #48 (AC 3)
- breaking: false
- Design screen owned: **Exceptions** (`design/project/glass/Exceptions.dc.html`, design.md §3.4); also restyles Flow (`/flow`, `/flow/[stage]`) and `/items/[id]`, which have no board (design.md §3.2, §9)

## Story

As an AR analyst, I want the exception workbench in the new look with filter chips, an inline detail panel, the auto-fix timeline and the lines editor, so that working a stuck item is quick and matches the rest of the app.

## Context

research.md: no structural change; the workbench already shows exceptions only with applied items hidden. design.md §3.4 lists the existing files to restyle, not rewrite: `components/exceptions/{exceptions-table,exceptions-filter-bar,exception-sheet,why-stuck,autofix-list,edit-form,receipt-picker,lock-controls,empty-states}.tsx`, `common/{lock-banner,history-timeline,status-badge}.tsx`. Flow files: `components/flow/{stage-tile,backlog-bar,flow-monitor,stage-items-table}.tsx`.

## Acceptance criteria

1. [browser] Exceptions board: top bar "Exceptions", env, Live, Sample data, checkbox "Show applied items" (default off; on, applied items appear and the footer count changes).
2. [browser] Exceptions board: filter chips with counts (All, Ambiguous receipt, Amount variance, Invoice not found, Customer not found, Always a person, Locked) using `FilterChip`, active chip with the accent border and soft fill; counts come from the existing exceptions query.
3. [browser] Exceptions board: split layout, glass list (Item mono, masked Payer, Amount mono currency-prefixed right-aligned, Reason pill warn/err/locked tone, Age, lock owner "You" or name; selected row tint; footer "N exceptions · N applied items hidden") beside the detail panel with the accent-glow border; below 1024 px the detail opens as a full-width `ui/sheet`.
4. [browser] Exceptions board: detail panel shows the header (mono item id, amount, reason line, close), the lock banner ("Locked by you since HH:MM. Automation won't act on this item."), "Why it's stuck" with candidate receipts as bordered tiles, "Auto-fixes tried N of M" as the vertical timeline ending "Escalated to a person", the lines editor (invoice and amount inputs, source pill `A+B` ok / `A` muted), the receipt selector, and actions "Requeue to match receipt" (primary), "Unlock", "Full history" link; requeue and unlock behave exactly as today.
5. [browser] Exceptions board states: loading (row skeletons), empty ("No exceptions right now … Applied items stay hidden unless you show them."), lock conflict ("<name> locked this item first", View read-only).
6. [browser] `/flow` and `/flow/[stage]`: stage tiles become glass station-style cards, backlog bar is the 5px `Meter`; `/items/[id]` uses `GlassPanel`, `Pill`, `history-timeline` restyled; no logic change, no horizontal page scroll at 375 px.
7. [unit] No new per-page CSS: a lint/grep test asserts no `style=` colour literals or hex colours in `components/exceptions/**`, `components/flow/**`, `components/items/**`; all colour comes from tokens.
8. [unit] Existing exceptions, flow and items tests still pass with selectors updated only where markup changed.

## Out of scope

- New exception behaviour or API changes. Chat tools for exceptions (chat-agent-tool-registry).

## Deps

- glass-theme-shell: `GlassPanel`, `Pill`, `FilterChip`, `Meter`, `DataTable` selected-row API, `StateCard`, `SkeletonRows`, `TopBar`, restyled `status-badge`/`lock-banner`/`history-timeline`. plannable: true.

## Assumptions

- Payer masking (`[Payer 0142]`) keeps the existing masking rule.
- Flow and Items are restyled here because they share the station/tile and timeline components with this screen; no separate story.
