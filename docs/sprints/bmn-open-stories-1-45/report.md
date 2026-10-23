# Report: bmn-open-stories-1-45

Release? No. Nothing deployed; deploy is Jonathan's call.

- Built: all 45 open stories (#1-#45), 5 waves, merged into sprint/open-stories-1-45 (PR #47 into dev). Gates: ruff, pyright, tsc, eslint passed.
- Tested: NOT tested, not reviewed (Jonathan chose no tests). Treat as unverified.
- Design: Claude Design unavailable; design.md written from shadcn/Tailwind conventions.
- Left open: s39 (earned-discount) now wired into plan_lines, MatchLinesRunner and ApplyRunner (commit 4eb75bd), still untested. Fakes used and unverified for mailbox (s33), Fusion pod (s12/s17/s32/s38/s39), Cohere endpoint, identity-domain groups claim. Terraform not validated (not installed). s25/s44 are IaC/plans only.
- Assumptions: see research.md and story files. dev is protected, so PR instead of merging to dev.
- Not done: cleanup of the sprint branch/worktree (still needed by PR #47).

## What I learned
**Served:** 0 lessons from earlier runs (first run in this repo) · untested: code lessons not judged
**New:**
- L-open-stories-1-45-1 · global · Pin each wave migration's down_revision in merge order; one `alembic heads` after every merge. Evidence: chain re-linearised 3 times (fc4e7a7, 5d88248, 6566611).
- L-open-stories-1-45-2 · global · A story that edits another story's files goes in a later wave. Evidence: s39 shared wave 5 with s15, committed first and was left partial until 4eb75bd.
- L-open-stories-1-45-3 · project · After a wave's last merge, regenerate the OpenAPI client and run pyright and tsc on the sprint branch. Evidence: fix commit 6566611 (stale openapi.json/schema.d.ts, write_back casts).
- L-open-stories-1-45-4 · project · dev is protected: land through a PR into dev. Evidence: PR #47.
- L-open-stories-1-45-5 · global · Check for Claude Design tools at INTAKE and record the fallback up front. Evidence: design.md fallback.

**From your feedback:** none
**Retired:** none
Ledger: `docs/bmn/lessons/bmn-open-stories-1-45.jsonl` (global lessons also in `~/.claude/bmn/lessons/`) · details in `retro.md`. Promoting proven lessons into the plugin: "/dev-bother-me-nope learn".
