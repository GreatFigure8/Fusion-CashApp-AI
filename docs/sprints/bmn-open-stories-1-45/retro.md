# Retro: bmn-open-stories-1-45

Run mode. Stack `mixed`. Untested (Jonathan chose no tests), so there were no review findings,
test failures or FIX rounds to learn from. The evidence is the merge history, the follow-up
commits and report.md. No lessons were served (first run in this repo), and bmn.json has no
feedback entries, so there are no hits, revisions, retirements or F- lessons.

## New lessons

**L-open-stories-1-45-1 (global, alembic; planner, coder, merger).** Every migration story in a
wave set its `down_revision` to the head it saw when coded. After merging, the chain had several
heads and had to be re-linearised three times: `fc4e7a7` (wave 3), `5d88248` (s45 after s42) and
`6566611` (s15, s19, s35, s41 re-pointed). Rule: the planner pins each migration's
`down_revision` in merge order, and the merger checks `alembic heads` shows a single head after
every merge.

**L-open-stories-1-45-2 (global, workflow; planner, orchestrator).** s39's plan edits s15's
`plan_lines`, `MatchLinesRunner` and `ApplyRunner`, but `waves.json` put s15 and s39 in the same
wave (5). s39 committed at 13:42 (`02c1e8f`), before s15 existed on the branch (`6d0a744`,
13:45), so the edits couldn't be made. report.md left s39 partial, and the wiring landed only
in the follow-up commit `4eb75bd`. Rule: a story that edits another story's files runs in a
later wave.

**L-open-stories-1-45-3 (project; coder, merger).** Each branch passed its own gates, but the
integrated branch needed a "merge fallout" commit (`6566611`): the generated
`web/lib/api/openapi.json` (+8143 lines) and `schema.d.ts` (+2486) were stale, and pyright
failed at the s17/s15 seam in `services/write_back.py` (fixed with casts to `NoteItem` and
`Sequence[NoteLine]`). Rule: after a wave's last merge, regenerate the client once and run
pyright and tsc on the sprint branch before the next wave starts.

**L-open-stories-1-45-4 (project; orchestrator, cleaner).** `dev` is protected here. The run
couldn't merge into it and opened PR #47 instead. Rule: land the sprint branch through a PR
into dev, never by pushing.

**L-open-stories-1-45-5 (global, ui; orchestrator, designer).** The designer found no Claude
Design tools (ToolSearch `+claude_design` empty). It fell back to one shadcn/Tailwind direction
with no previews (design.md). Rule: check for the tools at INTAKE and record the fallback up
front.

## Not lessons

- The untested state of the whole run is Jonathan's choice, not a mistake.
- Fakes for the mailbox, the Fusion pod, the Cohere endpoint and the groups claim are
  environment limits recorded as assumptions.
- Terraform wasn't installed. That's a one-off tooling gap.
