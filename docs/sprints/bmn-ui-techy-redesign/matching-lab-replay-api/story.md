# matching-lab-replay-api: Replay candidate matching rules read-only against real past data, then promote

- Issue: #48 (scope item 2, "the lab"; folds in #49)
- breaking: false
- Design screen owned: none (API; the Lab screen is owned by matching-lab-ui)

## Story

As an admin refining the matcher, I want to try a candidate change to the matching settings, replay it read-only over real past items and see exactly what would change before I promote it, so that the matching algorithm improves on evidence and never by guesswork.

## Context

input.md scope item 2 (issue #49: refine through chat, replay read-only against real past data, before/after, promote only by a permission-checked audited action) and Item 7 clarified (lab replay reads go through the fusion-sql-mcp server via `FusionClient`). research.md runner-up a5 and dissent: hard per-key bounds, affected-items estimate, admin-only confirm, record proposal id and config version on decisions. Matching code: `services/matching/{receipts,lines,discount,evidence,reservations}.py`, `domain/receipt_matching.py`, scorer/tolerance keys `matching.*` in `domain/config_keys.py`.

## Acceptance criteria

1. [unit] The receipt and line matching decisions are callable as pure functions of `(extraction, candidates, config snapshot) -> MatchDecision` with no DB, bus or Fusion side effects; the live stage runners call the same functions (one matcher, refactored if needed, existing matching tests unchanged and green).
2. [unit] `cashapp/services/lab/service.py` `LabService`: `create_candidate(changes: dict[key, value], rationale, principal) -> Candidate{id "p_NNNN", base_version, changes}` (only `matching.*` keys plus the date window/tolerance keys, each checked with `validate_value` and per-key hard bounds); `replay(candidate_id, window_days, principal) -> Replay{id "rp_NNNN"}` runs asynchronously; `get_replay(id) -> ReplayResult{status RUNNING|DONE|FAILED|STALE, done, total, changed, newly_matched, newly_failed, newly_ambiguous, money_by_currency: [{currency, newly_matched: MoneyStr, newly_unmatched: MoneyStr, items}], items: [{item_id, amount, currency, before, after}], config_diff: [{key, before, after}], duration_ms}`; `promote(candidate_id, replay_id, reason, expected_version, principal)`; `discard(candidate_id, principal)`.
3. [unit] Replay is read-only: it reads past items' stored extractions and decisions from ATP and receipt candidates through `FusionClient` read methods (MCP transport), evaluates live config and candidate config side by side, and never reserves, applies, writes to Fusion, emits bus events or changes work items. A test with a spy `FusionClient` and bus asserts zero write calls and zero publishes.
4. [unit] Promote requires CONFIG_WRITE, a DONE replay of that candidate whose `base_version` equals the current live config version (else 409 `STALE` "Live config moved to vN"), a reason, and goes through the same ConfigService write as `PUT /config/{key}` (one version bump for all changed keys), recording candidate id and replay id on the config history row.
5. [unit] New tables `LAB_CANDIDATE`, `LAB_REPLAY`, `LAB_REPLAY_ITEM` (Alembic, one revision); replay item rows are purged with history payload retention.
6. [unit] Replay progress is reported (done/total) and the work is bounded (`lab.max_items`, `lab.max_concurrency`, DB config keys owned here); it runs as a background task in the API process started by the request (no scheduler, no poller) and resumes as FAILED on restart.
7. [api] New auto-discovered router `lab.py`: `POST /lab/candidates` (LAB_RUN), `GET /lab/candidates?limit=`, `POST /lab/candidates/{id}/replays {window_days}` (LAB_RUN), `GET /lab/replays/{id}`, `GET /lab/replays/{id}/stream` (SSE progress, heartbeat), `GET /lab/replays/{id}/items.csv`, `POST /lab/candidates/{id}/promote {replay_id, reason, expected_version}` (CONFIG_WRITE), `POST /lab/candidates/{id}/discard`. `Permission.LAB_RUN = "lab:run"` added (ADMIN and OPERATOR). OpenAPI regenerated.
8. [unit] Chat tools in `cashapp/services/chat/tools/lab.py` (group LAB): `lab.propose {changes, rationale}` (creates a candidate, LAB_RUN, not mutating live config, no confirm), `lab.replay {candidate_id, window_days}` (LAB_RUN, streams `tool_progress`, returns `replay_card`), `lab.promote` (mutating, confirm_required, CONFIG_WRITE, preview = config diff + replay summary + version), `lab.discard`. The `MATCHING` prompt key is used for lab chat.

## Out of scope

- The Lab screen (matching-lab-ui). Changing non-matching settings through the lab.

## Deps

- chat-agent-tool-registry: `ToolSpec`, `TOOLS` discovery, `ConfirmPreview`, `replay_card`, `PromptKey.MATCHING`. plannable: true.
- fusion-mcp-transport: `FusionClient` read methods (`find_receipts`, `get_receipt`, `find_transactions`) on the MCP transport (same signatures as today). plannable: true.
- db-stored-settings: `ConfigKey` spec and `RuntimeSettings` for `lab.*` keys. plannable: true.

## Assumptions

- Board copy "Replays never call Fusion" becomes "Replays never write to Fusion": Item 7 says lab replays read real data through the MCP server.
- Receipt candidates for a past item are re-read from Fusion as they are now (remaining amounts may have changed since); the result marks items whose receipt was since applied as "receipt since applied" rather than counting them as newly matched.
