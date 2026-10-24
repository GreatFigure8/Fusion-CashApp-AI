# Retro: ui-techy-redesign

Ledger: `docs/bmn/lessons/bmn-ui-techy-redesign.jsonl` (25 events; `check` ok; 16 global events exported). The brief named `ui-techy-redesign.jsonl`, but the helper requires `<run>.jsonl`, so the file is `bmn-ui-techy-redesign.jsonl`, the same pattern as the earlier `bmn-open-stories-1-45.jsonl`.

The run was untested and had no review pass. So only the workflow lessons it was served could be judged, using the merge history and what the orchestrator saw.

## Served lessons that recurred (hit + revise)

- **L-comparison-wizard-from-fusion-2** (coders start only from a merged sprint tip). All 14 stories ran as one wave even though many had dependencies, because the splitter marked every interface `plannable:true`. The matching-lab-ui and exceptions-workbench-restyle coders refused to stub their dependencies, and exceptions-workbench-restyle landed only partly ("helpers only; re-dispatch after wave-1 merge"). Wave 2 had to be forced (commits after `ebc015e`). Revised rule: waves come from the dependencies. "Plannable" means a story can be planned in parallel, never coded in parallel.
- **L-console-text-field-1** (dependent coders merge the foundation before they type-check). Other wave-1 coders went ahead and committed code that failed the type-check. Two `fix(merge)` commits had to reconcile it with DB-stored settings: `5b0e450` and `3b6994d`. Revised rule: a coder whose dependency isn't merged returns "blocked" and is dispatched again from the new tip.
- **F-guided-compare-flow-2** (judge vote at the design pick). The vote was skipped, and `design.md` has no tally. Revised rule: write the tally line before showing the pick.
- **L-pre-payroll-quality-checks-1** (one owner per shared helper or schema). Two stories each defined `PollerOut` and `MoneyByCurrencyOut`, and `3b6994d` renamed them so OpenAPI has one name for each. Revised rule: split.md lists the schema names with their owner story, and each planner greps for a name before defining it.

## Unserved lessons that recurred (hit, served: false)

- **L-open-stories-1-45-1** (pin Alembic `down_revision` order). `ae9d31c` re-pointed six migrations into one chain. The lesson was active but wasn't served, because `select` got no `alembic` tag.
- **L-open-stories-1-45-2** (a story that edits another story's files goes in a later wave). Same single-wave cause as above. This lesson was cut by the per-brief cap.

## New lessons

1. **L-ui-techy-redesign-1** (global). split.md maps each shared registry file (config keys, permissions, route/stream path maps) to an owner and a merge order. Other plans only append to these files. Cause: 14 parallel planners worked without a map, and `config_keys.py`, `stream-paths.ts` and `permissions.ts` conflicted repeatedly. `ENGINE_CONTROL` dropped out of `permissions.ts` until `3b6994d` restored it.
2. **L-ui-techy-redesign-2** (global, orchestrator). Pass a `select --tag` for each tool the repo uses (alembic, playwright, vitest, terraform), not only for the routed skills. That is how the Alembic lesson went unserved.
3. **L-ui-techy-redesign-3** (global, ui). Commit every design board that a plan cites into the sprint branch before coders fork. Cause: `Lab.dc.html` was missing from the matching-lab-ui coder's checkout, so the Lab UI follows the plan and nobody has checked it visually.
4. **L-ui-techy-redesign-4** (global, ui). The designer renders each board in the Browser pane and takes a screenshot. If it can't, it marks the board "unrendered" in design.md and the pick question says so. Cause: the boards were only checked statically.
5. **L-ui-techy-redesign-5** (project). Resolve the absolute path of `uv` into stack.md at INTAKE and put it into every brief that runs the api/ gates. Cause: `uv` wasn't on the coders' PATH.

## Jonathan's feedback (F- lessons, source: jonathan)

- **F-0**: `dev` is protected, so work lands through a PR into `dev` (PR #51).
- **F-1**: the processing engine gets a control panel: pause, resume, drain, throttle, DLQ replay.
- **F-2** (global): every setting except the database connection info lives in the database and can be edited in the UI. The same entry also asked for the lab, real-time progress and exportable HTML reports, all of which were built this run.
- **F-3**: the chat agent is the main interface. Every action is also a chat tool, and the agent can discuss optimising the processing.
- **F-4**: the API connects to fusion-sql-mcp as an MCP client.
- **F-5**: receipts and invoices are looked up through fusion-sql-mcp.
- **F-6**: "all Fusion connectivity via MCP". Written and then **retired** in the same file, because F-7 replaced it the same day.
- **F-7**: Fusion reads and REST writes go through fusion-sql-mcp, and the SOAP `createApplyReceipt` call is made directly from the API with Vault credentials.

Six scope additions came in during research and design: the engine control panel, the lab, DB-stored settings, realtime progress, HTML reports, the chat agent, and the MCP path (decided over three messages). Each was folded in as feedback. No separate lesson was written about the scope churn itself: those were Jonathan's decisions, not a mistake that bmn repeated.

## Lessons checked and not hit

L-open-stories-1-45-3: the OpenAPI client was regenerated once, in `3b6994d`. L-open-stories-1-45-4: work landed through PR #51. F-legacy-data-crosswalk-0/1 and L-open-stories-1-45-5: the Claude Design canvas existed and a direction was picked. Nothing was retired.
