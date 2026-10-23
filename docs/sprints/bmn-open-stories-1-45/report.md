# Report: bmn-open-stories-1-45

Release? No. Nothing deployed; deploy is Jonathan's call.

- Built: all 45 open stories (#1-#45), 5 waves, merged into sprint/open-stories-1-45 (PR #47 into dev). Gates: ruff, pyright, tsc, eslint passed.
- Tested: NOT tested, not reviewed (Jonathan chose no tests). Treat as unverified.
- Design: Claude Design unavailable; design.md written from shadcn/Tailwind conventions.
- Left open: s39 (earned-discount) partial: apply-path hooks in s15 (plan_lines, MatchLinesRunner, ApplyRunner) not wired. Fakes used and unverified for mailbox (s33), Fusion pod (s12/s17/s32/s38/s39), Cohere endpoint, identity-domain groups claim. Terraform not validated (not installed). s25/s44 are IaC/plans only.
- Assumptions: see research.md and story files. dev is protected, so PR instead of merging to dev.
- Not done: RETRO and cleanup of the sprint branch/worktree (still needed by PR #47).
