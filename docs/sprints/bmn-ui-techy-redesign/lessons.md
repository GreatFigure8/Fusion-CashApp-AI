## orchestrator
- [F-legacy-data-crosswalk-0] Claude Design is always available: it is the 'Design' Artifact type (Artifact quickstart intent 'design'); the designer starts there and never searches ToolSearch for claude_design tools or falls back to HTML.
- [F-customer-conversion-1] When Jonathan says a run is taking too long, cut testing to the critical tests (the reported failure path, data safety, regressions on shared paths) and list what was skipped.
- [F-guided-compare-flow-0] When Jonathan asks to vet a redesign, fan out one researcher per section or workflow, have judges score and vote, and adopt the winner even when it means redesigning from scratch.
- [F-guided-compare-flow-2] At the design pick, run a judge vote (fan out, fan in) over the directions and present your pick first, marked Recommended, with the vote result in one line.
- [F-guided-compare-flow-6] When Jonathan makes this run the release owner for other sessions, ship them together: confirm each session's work is in dev, run every migration and one deploy of the combined tip, then close all their issues.
- [F-guided-compare-flow-7] When another session's merged work must ship in this release, merge origin/dev into the sprint (--no-ff) before the last test run so it is tested together, and repoint its specs at screens this run retired.
- [F-conversation-skills-500-0] For a new bmn issue: run the planning phase, park at 'awaiting approval for coding', then tell Jonathan in one line which issue is ready to be coded and where its plans are; never code before his approval.
- [F-conversation-skills-500-1] On 'approved for coding' for a parked run, code the parked plans as written: no re-research, re-split or re-plan; merge origin/dev into the sprint, then dispatch every coder in the same turn.

## stack-scout
- [F-fill-template-atp-source-2] Write explicit worker counts into every CPU-heavy gate in stack.md (vitest --maxWorkers and --shard counts sized to 36 cores, eslint --concurrency=auto) so every brief inherits the max-thread setting without Jonathan forcing it.

## researcher
- [F-guided-compare-flow-0] When Jonathan asks to vet a redesign, fan out one researcher per section or workflow, have judges score and vote, and adopt the winner even when it means redesigning from scratch.

## synthesizer
- [F-guided-compare-flow-0] When Jonathan asks to vet a redesign, fan out one researcher per section or workflow, have judges score and vote, and adopt the winner even when it means redesigning from scratch.
- [L-one-element-crosswalk-1] When an issue's ACs say seed, sync or copy data into a second store that already has an owner, question it: design one store with readers on it (view or pinned snapshot), and keep a copy only with its reason written in split.md.

## designer
- [F-legacy-data-crosswalk-0] Claude Design is always available: it is the 'Design' Artifact type (Artifact quickstart intent 'design'); the designer starts there and never searches ToolSearch for claude_design tools or falls back to HTML.
- [F-guided-compare-flow-2] At the design pick, run a judge vote (fan out, fan in) over the directions and present your pick first, marked Recommended, with the vote result in one line.
- [F-guided-compare-flow-3] When Jonathan picks 'X + grafts', freeze direction X with the named grafts from the other directions folded in, and record each graft and its source in design.md.
- [F-review-leftovers-1] Open every design question with one plain sentence on the problem the screens solve and what each option changes for the user, before naming or linking the options.
- [F-legacy-data-crosswalk-1] No UI story is planned or coded before Jonathan picks a direction on the Design canvas; if the canvas cannot be created, stop the run at DESIGN and say so in one line, never proceed on a fallback.
- [L-open-stories-1-45-5] At INTAKE, check with ToolSearch whether Claude Design tools exist; if not, record the fallback in bmn.json assumptions up front and brief the designer for the shadcn/Tailwind fallback directly.

## splitter
- [L-one-element-crosswalk-1] When an issue's ACs say seed, sync or copy data into a second store that already has an owner, question it: design one store with readers on it (view or pinned snapshot), and keep a copy only with its reason written in split.md.
- [F-fusion-register-background-pull-0] Use all the CPU in every run without waiting to be reminded: at intake plan streamed planners, file-level coder slices and merge batches that overlap at the 20-agent cap, and keep it full to the end of CODE.
- [F-fusion-result-jobs-0] Treat a reminder to use all the CPU as standing for the whole run: start each planner and coder as its story or plan lands and fill every test run to the agent cap, without raising a limit the project pins (e2e workers).
- [F-chat-framework-1] When the previous run left a known defect or an unrun data step, offer to fold it into the next run as a first-wave story, so later stories build on the fixed code.
- [L-regal-chat-issue-fixes-3] Every plan claim about the code (a path exists, no caller passes X) cites file:line and the git grep proving it; every planned test path is checked against the runner config it must match (Playwright testDir/testMatch, vitest include).
- [L-pre-payroll-quality-checks-1] When 2+ stories in a wave need a new shared helper, client, style utility or response schema, the splitter names one owner story, its path and its signature in split.md; other planners import it, never add their own.
- [L-guided-compare-flow-4] When two or more same-wave stories need the same helper, label map, status set or component, the planner names one owner slice that exports it and every other plan imports it; no plan defines its own copy.
- [L-employee-level-fixes-1] Never let a contract story create placeholder files at paths another story writes for real; each owner creates its own files and dependents merge the owner's pushed wip branch, so merges never hit add/add conflicts.

## planner
- [F-customer-conversion-1] When Jonathan says a run is taking too long, cut testing to the critical tests (the reported failure path, data safety, regressions on shared paths) and list what was skipped.
- [F-guided-compare-flow-3] When Jonathan picks 'X + grafts', freeze direction X with the named grafts from the other directions folded in, and record each graft and its source in design.md.
- [L-one-element-crosswalk-1] When an issue's ACs say seed, sync or copy data into a second store that already has an owner, question it: design one store with readers on it (view or pinned snapshot), and keep a copy only with its reason written in split.md.
- [F-legacy-data-crosswalk-1] No UI story is planned or coded before Jonathan picks a direction on the Design canvas; if the canvas cannot be created, stop the run at DESIGN and say so in one line, never proceed on a fallback.
- [F-fusion-register-background-pull-0] Use all the CPU in every run without waiting to be reminded: at intake plan streamed planners, file-level coder slices and merge batches that overlap at the 20-agent cap, and keep it full to the end of CODE.
- [F-fusion-result-jobs-0] Treat a reminder to use all the CPU as standing for the whole run: start each planner and coder as its story or plan lands and fill every test run to the agent cap, without raising a limit the project pins (e2e workers).
- [L-admin-act-for-absent-owner-1] Each UI plan lists, per design.md screen it builds, every label, state icon/colour, copy string and shared component (NextActionCard, split-pane) as a checklist; the coder ticks each in validation.md; the reviewer flags any unticked.
- [L-comparison-wizard-from-fusion-2] Start a wave's coders only from the sprint tip after the previous wave is merged and pushed; a coder never copies, stubs or stands in for a dep's files. Same-wave deps share only a pinned interface listed in both plans.

## coder
- [L-admin-act-for-absent-owner-1] Each UI plan lists, per design.md screen it builds, every label, state icon/colour, copy string and shared component (NextActionCard, split-pane) as a checklist; the coder ticks each in validation.md; the reviewer flags any unticked.
- [L-comparison-wizard-from-fusion-2] Start a wave's coders only from the sprint tip after the previous wave is merged and pushed; a coder never copies, stubs or stands in for a dep's files. Same-wave deps share only a pinned interface listed in both plans.
- [L-console-text-field-1] When coders in one wave build on a foundation slice, merge it into the sprint the moment it lands and have each dependent coder merge the sprint before type-checking; never copy its files into a tree to type-check.
- [L-open-stories-1-45-3] After a wave's last merge, regenerate web/lib/api/openapi.json and schema.d.ts once from the integrated API and run pyright and tsc on the sprint branch before the next wave starts.

## merger
- [F-guided-compare-flow-7] When another session's merged work must ship in this release, merge origin/dev into the sprint (--no-ff) before the last test run so it is tested together, and repoint its specs at screens this run retired.
- [L-admin-act-for-absent-owner-2] Before dispatching testers, list every test path each will add in its brief and give a shared path (e.g. a hoisted helper's test) one owner; others add cases in their own file. FIX merges test branches once, before fixers fork.
- [L-console-text-field-1] When coders in one wave build on a foundation slice, merge it into the sprint the moment it lands and have each dependent coder merge the sprint before type-checking; never copy its files into a tree to type-check.
- [L-employee-level-fixes-1] Never let a contract story create placeholder files at paths another story writes for real; each owner creates its own files and dependents merge the owner's pushed wip branch, so merges never hit add/add conflicts.
- [L-open-stories-1-45-3] After a wave's last merge, regenerate web/lib/api/openapi.json and schema.d.ts once from the integrated API and run pyright and tsc on the sprint branch before the next wave starts.

## db-sync
- [L-generic-components-2] Every tester, fixer and db-sync brief opens with its own worktree path and 'cd there'; the run worktree is named read-only (no checkout, reset or detach there); the orchestrator runs git reflog -3 there after each returns.

## tester
- [F-customer-conversion-1] When Jonathan says a run is taking too long, cut testing to the critical tests (the reported failure path, data safety, regressions on shared paths) and list what was skipped.
- [F-guided-compare-flow-7] When another session's merged work must ship in this release, merge origin/dev into the sprint (--no-ff) before the last test run so it is tested together, and repoint its specs at screens this run retired.
- [F-fusion-result-jobs-0] Treat a reminder to use all the CPU as standing for the whole run: start each planner and coder as its story or plan lands and fill every test run to the agent cap, without raising a limit the project pins (e2e workers).
- [F-customer-conversion-2] When Jonathan asks for speed, run one test round, one FIX round whose reproducing tests are the re-check, then release; no second test run.
- [L-admin-act-for-absent-owner-2] Before dispatching testers, list every test path each will add in its brief and give a shared path (e.g. a hoisted helper's test) one owner; others add cases in their own file. FIX merges test branches once, before fixers fork.
- [L-guided-compare-flow-3] Before stopping any subagent, confirm whose it is (its description and parent); never stop a worker's helpers. Tester and reviewer briefs say: do not spawn subagents while the run fills the agent cap.

## reviewer
- [L-admin-act-for-absent-owner-1] Each UI plan lists, per design.md screen it builds, every label, state icon/colour, copy string and shared component (NextActionCard, split-pane) as a checklist; the coder ticks each in validation.md; the reviewer flags any unticked.
- [L-regal-chat-issue-fixes-3] Every plan claim about the code (a path exists, no caller passes X) cites file:line and the git grep proving it; every planned test path is checked against the runner config it must match (Playwright testDir/testMatch, vitest include).
- [L-guided-compare-flow-2] A reviewer reads its diff with git diff/git show <base>...<sha> from its own worktree only; it never runs /code-review or any tool that checks out a ref, and never runs git in the main checkout.
- [L-guided-compare-flow-3] Before stopping any subagent, confirm whose it is (its description and parent); never stop a worker's helpers. Tester and reviewer briefs say: do not spawn subagents while the run fills the agent cap.
- [L-conversation-title-overwrite-4] The reviewer passes /code-review the run's exact diff range (dev_base...integration sha, or the run's paths), never its default target, and checks the files it reviewed match the run diff before using its findings.

## fixer
- [F-customer-conversion-2] When Jonathan asks for speed, run one test round, one FIX round whose reproducing tests are the re-check, then release; no second test run.
- [L-chat-authored-quality-checks-4] Give a FIX item whose repair crosses layers (service, DTO, route, UI caller) to one fixer that owns every file on that path; never split it by story file ownership so a fixer reports half of it blocked.

## cleaner
- [L-open-stories-1-45-4] dev is protected in this repo: land the sprint branch through a PR into dev (merge commit), never a direct push or local merge into dev.

## release-prep
- [F-guided-compare-flow-6] When Jonathan makes this run the release owner for other sessions, ship them together: confirm each session's work is in dev, run every migration and one deploy of the combined tip, then close all their issues.
- [F-conversation-title-overwrite-3] A bare 'release' at step 7 approves the report's checklist as shown (its version, every site): run it end to end and report the result; ask nothing about version or sites.
- [F-regal-chat-issue-fixes-3] When Jonathan answers the step-7 decision with 'Release', run the whole release checklist as one unit (release, publish to every site, close issues) with no further question.
- [F-chat-2026-10-20-close-issues-on-approve-1] When Jonathan approves the release or a PR, close every GitHub issue the shipped work resolves (gh issue close N --reason completed, comment 'Shipped in vX.Y.Z: <one line>'); name unclear links in the report, don't close them.
- [F-customer-conversion-4] Never release dev as it stands; release only this run's tested sprint, because dev can carry another session's untested work.
- [F-customer-conversion-5] Never offer Jonathan a shortcut his rules already exclude (shipping untested dev, skipping tests on what ships); offer only release paths that keep them.
- [F-customer-conversion-6] When dev holds another unfinished sprint, release as a hotfix from main (origin/main + the sprint branch + release note), then merge main back into dev.

## retro
none yet
