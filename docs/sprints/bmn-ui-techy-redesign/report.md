# Report: ui-techy-redesign (issue #48, with the lab from #49)

## Your decision: release?
**Not recommended yet.** All 14 stories are coded and merged on `sprint/ui-techy-redesign`, but **nothing was tested** (you chose no test cycles), and the existing test suite needs updates for the new settings signatures, so it will fail as it stands. Nothing is merged into `dev`: `dev` is protected, so the work is in [PR #51](https://github.com/GreatFigure8/Fusion-CashApp-AI/pull/51), open and unmerged. Nothing is deployed and no migration has been applied anywhere.

## What was built
Design: **B, Glass Orbit** (Claude Design canvas https://claude.ai/artifact/NgfTaH1tfvxXVLaMVamDEc, frozen in `design.md`).
1. glass-theme-shell: tokens, shared glass components, app shell
2. live-progress-dashboard: metrics API + SSE, Dashboard (receipts matched, money applied per currency, model efficiency)
3. exceptions-workbench-restyle: exceptions, flow and items restyle
4. engine-control-api + engine-control-panel-ui: pause/resume/drain, throttle, DLQ replay; admin-only, audited
5. chat-agent-tool-registry + assistant-chat-redesign: one tool registry, Haiku agent, confirm-before-mutate, payroll-compare-style chat
6. matching-lab-replay-api + matching-lab-ui: read-only replay on past data, before/after, audited promote
7. failed-receipt-review: multi-image upload and in-depth review
8. html-progress-reports: self-contained HTML export, report panels restyled
9. db-stored-settings + settings-screen-redesign: all settings except DB connection info in the database
10. fusion-mcp-transport: Fusion reads and REST writes via fusion-sql-mcp; receipt apply SOAP stays direct; CLAUDE.md refined

## How it was tested
**Untested.** Gates only: ruff, pyright, eslint, `tsc` pass on the combined result; Alembic has one head (`s48_lab_replay`).

## Left open
- No tests written or run; no review pass.
- Existing tests need updates (EngineService `runtime=`, `build_mcp_client`, `FusionClientFactory`, `PreflightContext.from_runtime`).
- Lab board `Lab.dc.html` was not in the coder's checkout: the Lab UI follows the plan, not the board; unchecked visually. No screen has been checked in a browser.
- `services/chat/tools/engine.py` imports API schemas (layering).
- fusion-sql-mcp follow-ups in GreatFigure8/fusion-sql-mcp: OAuth client and source group for this app, a binary GET tool, a REST write allowlist. The app cannot reach Fusion through it until these exist.
- The migration helper `run_in_vcn.sh` uses a Terraform output (`job_launch_spec`) not in the repo; unverified against infra.
- Chain: 6 new migrations are unapplied (DEV first, per CLAUDE.md).
- #49 stays open as a pointer; close it with #51.

## Release checklist (nothing runs yet)
1. Merge PR #51 into `dev` (a person; `dev` is protected).
2. Apply migrations to the DEV ATP schema, then tests.
3. Version bump in `api/pyproject.toml` (0.1.0 -> 0.2.0, minor with a breaking settings change), `dev` -> `main`.
4. `deploy/release.sh` / release.yml to OCI (images to OCIR, alembic, terraform apply) with `fusion_write_enabled` per environment.
5. Smoke: `/health` reports the version.

## Assumptions
See `bmn.json`: lab = #49 folded in; MCP is the Fusion read/REST-write path; SOAP apply direct; merges to `dev` via PR.

## Git cleanup
Story, fix and harness branches were deleted as merged. The sprint branch `sprint/ui-techy-redesign` and the run worktree stay until PR #51 is merged.

## What I learned
- **One wave was wrong.** All 14 stories were coded in parallel because the splitter marked them "plannable", so two coders refused to start and a second wave was forced. Waves now follow the dependencies (L-comparison-wizard-from-fusion-2 and L-console-text-field-1, both revised).
- **Shared files need an owner.** `config_keys.py`, `permissions.ts`, `stream-paths.ts`, the Alembic `down_revision` chain and two duplicate schema names all needed merge fixes. split.md will now map each shared file and name to one owner (L-ui-techy-redesign-1; L-pre-payroll-quality-checks-1 revised). The Alembic lesson was never served because no `alembic` tag was passed (L-ui-techy-redesign-2).
- **Design hand-off gaps.** No judge vote was run at the pick, the boards were never rendered, and the Lab board was missing from a coder's checkout (F-guided-compare-flow-2 revised; L-ui-techy-redesign-3 and L-ui-techy-redesign-4).
- **Tooling.** `uv` wasn't on the coders' PATH, so its absolute path now goes into stack.md (L-ui-techy-redesign-5).
- **Your 8 instructions are now lessons** (F-ui-techy-redesign-0 to 7): `dev` changes only through a PR, the engine control panel, settings stored in the database, the chat agent as the main interface, and the fusion-sql-mcp split (MCP for reads and REST writes, SOAP apply direct). F-6, "all through MCP", is retired because F-7 replaced it.

Details: [retro.md](retro.md).
