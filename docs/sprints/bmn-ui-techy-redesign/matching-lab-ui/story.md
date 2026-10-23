# matching-lab-ui: The Matching Lab screen

- Issue: #48 (scope item 2; #49)
- breaking: false
- Design screen owned: **Lab** (`design/project/glass/Lab.dc.html`, design.md §3.7)

## Story

As an admin, I want a Matching Lab where I talk to the lab assistant about a matching change, see the candidate replayed against the last 30 days with a before/after comparison, and promote it with a reason, so that refining the matcher is a guided, evidence-based workflow.

## Context

design.md §3.7. Left: the shared chat in `compact` variant with `systemPromptKey="matching"` and the LAB tool group. Right: results column from matching-lab-replay-api. New: `web/app/(shell)/lab/page.tsx`, `web/components/lab/{candidate-card,comparison-tiles,money-affected-table,changed-items-table,promote-panel}.tsx`.

## Acceptance criteria

1. [browser] Lab board: `/lab` top bar "Matching Lab", env, `Read-only replay` (locked pill), Sample data, "Replays never write to Fusion".
2. [browser] Lab board: left Lab assistant (shared `LlmChat` compact: header "Lab assistant · Connected · Haiku 5.5", one `matching.*` tool chip, ↵ and / hints); asking it to try a change creates a candidate and a replay, and the results column follows the replay the chat started.
3. [browser] Lab board: candidate card ("Candidate p_NNNN vs live vN", "Replay complete · N s", pill "N items · 30 days", config diff via `DiffBlock` with red/green tinted lines); four comparison tiles (Match differently, Newly matched +N, Newly failed +N, Newly ambiguous N).
4. [browser] Lab board: Money affected by currency table (Currency, Newly matched, Newly unmatched, Items; never summed across currencies) and Items that change table (Item, Amount, Before pill, After pill; Export CSV link to `/lab/replays/{id}/items.csv`).
5. [browser] Lab board: Promote to live panel (pills "Replay ran on current vN", "You can write config"; required Reason; primary "Promote p_NNNN"; Discard; caption "Records <name> · replay rp_NNNN · expected version N"), confirmed through `ConfirmDialog`; after promote the live version increments and the candidate shows Promoted.
6. [browser] Lab board states: empty ("No candidate yet"), loading (progress bar "N of M items" over `/lab/replays/{id}/stream`), stale ("Live config moved to vN. Promote is blocked until you replay against the new version.", Replay again), no permission ("Replay only … Promote needs config write.", promote disabled).
7. [unit] Lab nav entry visible with LAB_RUN; its count shows open candidates from `GET /lab/candidates`.
8. [browser] At narrow widths the split wraps (chat first, results below) with no horizontal page scroll.

## Out of scope

- Replay logic and tools (matching-lab-replay-api).

## Deps

- glass-theme-shell: `GlassPanel`, `Pill`, `DiffBlock`, `ConfirmDialog`, `KpiCard`, `DataTable`, `StateCard`, `TopBar`, nav count source. plannable: true.
- assistant-chat-redesign: `LlmChat` with `variant="compact"`, `systemPromptKey`, `tools`, `chips`, and an `onToolResult(card)` callback so the page can follow `replay_card` results. plannable: true.
- matching-lab-replay-api: `/lab/*` endpoints and `ReplayResult` shape in its story. plannable: true.
- live-progress-dashboard: `useEventStream` hook. plannable: true.

## Assumptions

- The page follows the most recent replay of the current user's latest candidate when opened without a query string; `?candidate=` selects one.
