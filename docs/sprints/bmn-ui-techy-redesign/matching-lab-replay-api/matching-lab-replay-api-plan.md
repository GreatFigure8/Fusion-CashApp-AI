# Plan: matching-lab-replay-api

Story: [story.md](story.md). Deps: chat-agent-tool-registry, fusion-mcp-transport, db-stored-settings (all plannable; this story builds in wave 1 against their pinned interfaces, never copies or stubs their files; lesson L-comparison-wizard-from-fusion-2).
Skills applied: python-web-app:building-python-web-apps (routes -> services -> repositories; job status written before hand-off, failure writes its own terminal value), python-llm-features:building-llm-backed-features (tool field descriptions are prompt surface; lab context is aggregates only), python-library-quality:guarding-destructive-operations (replay-item purge and promote refuse before the first mutation), claude-api (no new model call here: lab chat uses the registry's Haiku loop).

## 1 Approach

- research.md runner-up **a5** (shadow-replay matching lab), built now because Jonathan folded #49 in (input.md scope item 2), with research.md's two blockers solved here: (a) **a pure matcher** - the scorer (`score_candidates`) and line planner (`plan_lines`) are already pure; this story lifts the remaining decision logic out of the two stage runners into `services/matching/decision.py` so runners and the lab call one function; (b) **receipt candidates** are re-read live through `FusionClient` read methods on the MCP transport (input.md Item 7 final), not snapshotted.
- research.md a3's propose-and-confirm pattern and dissent: fail-closed key filter (`matching.*` only) + `validate_value` + per-key hard bounds; promote is admin-only (CONFIG_WRITE) and goes through the same `ConfigWriter` as `PUT /config/{key}` with reason and expected version; candidate id and replay id recorded on the config history rows.
- Replay = a background `asyncio` task in the API process started by the POST (no scheduler, no poller; non-negotiables 4/5). Bounded by `lab.max_items` / `lab.max_concurrency`. Progress persisted on `LAB_REPLAY` (done/total + heartbeat) and pushed to an in-process hub for SSE; a RUNNING replay whose runner is gone (restart) is reported and persisted as FAILED.
- Read-only is structural: the replay receives a `ReadOnlyFusion` wrapper (read methods only; no write attribute exists), no `EventBus`, no `ReservationService`, and writes only `LAB_*` rows.
- "Live config version" (the board's `v41`): there is no global config version today (versions are per key, `CONFIG_SETTING.VERSION`). Defined here as the **lab config version** = number of distinct change sets on lab-eligible keys in `CONFIG_CHANGE` (a promote is one change set, so one bump for all its keys; any `PUT /config/matching.*` is one bump). See Assumptions.

## 2 Files to create / change

API (`api/src/cashapp/`):

| File | New/Change | Purpose |
|---|---|---|
| `domain/lab.py` | new | `LAB_KEYS` (explicit tuple of the five `matching.*` keys, fail-closed), `LAB_BOUNDS` per-key hard bounds, `ReplayStatus` (RUNNING, DONE, FAILED, STALE), `CandidateStatus` (OPEN, PROMOTED, DISCARDED), `ReplayOutcome` labels (`matched`, `no_receipt`, `ambiguous`, `variance`, `lines_failed`, `no_input`), `format_candidate_id`/`parse_candidate_id` (`p_%04d`), `format_replay_id`/`parse_replay_id` (`rp_%04d`), `classify_change(before, after) -> ChangeKind`. Pure. |
| `domain/config_keys.py` | change (append-only `lab.*` block) | `lab.max_items`, `lab.max_concurrency`, `lab.default_window_days`, `lab.max_window_days`, `lab.chat_wait_seconds` (section 5). |
| `domain/principal.py` | change (append-only) | `Permission.LAB_RUN = "lab:run"`; added to `Role.OPERATOR` set (ADMIN gets every permission already). `SYSTEM_PRINCIPAL` unchanged in intent (it holds all minus APPLY_REVERSE/CONFIG_WRITE, so it gains LAB_RUN; harmless, never used for lab). |
| `domain/retention.py` | change | `PurgeReport.lab_replay_items: int = 0`. |
| `services/matching/decision.py` | new | The one matcher entry point. `ReceiptMatchInputs` (frozen dataclass: payment_amount, currency, payment_date, anchor, related, references, invoice_numbers, payer_bank_account, fix_hints, resume_applied, human_receipt_id), `extraction_inputs(extraction)` (moved from `stations/match_receipt/runner.py::_extraction_inputs`), `decide_receipt(inputs, receipts, config: MatchingConfig, *, aliases, evidence) -> ReceiptMatchDecision{scored: ScoredCandidates, winner: Candidate|None, decided_by, rule, human_problem: str|None, outcome: MatchOutcome}` (scorer call + the human-hint resolution now inline in the runner), `decide_lines(lines, found_transactions, owners, receipt_remaining, existing, payment_currency, config: MatchingConfig, *, header_amount, discount) -> LinePlan` (wraps `index_transactions` + `plan_lines` with `tolerance=config.tolerance_for(currency)`), `MatchDecision{receipt: ReceiptMatchDecision, lines: LinePlan|None}`. No I/O, no DB, no bus, no Fusion. |
| `stations/match_receipt/runner.py` | change | `process()` builds `ReceiptMatchInputs` and calls `decide_receipt`; I/O (search, aliases, evidence, reservation, history) unchanged. `_extraction_inputs` removed (imported from decision.py). |
| `stations/match_lines/runner.py` | change | Calls `decide_lines` instead of `index_transactions` + `plan_lines` directly; persistence unchanged. |
| `services/lab/__init__.py` | new | exports `LabService`, errors. |
| `services/lab/service.py` | new | `LabService` (section 7 signatures): create_candidate, list_candidates, replay, get_replay, items_csv rows, promote, discard. Owns transactions; takes `Principal` as an argument. |
| `services/lab/errors.py` | new | `LabError` base; `LabKeyNotAllowed`, `LabOutOfBounds`, `LabInvalidValue` (wraps `ConfigValidationError`), `LabNotFound`, `LabForbidden`, `LabStale(live_version)`, `LabReplayNotDone`, `LabReplayRunning`, `LabCandidateClosed`, `LabReasonRequired`, `LabWindowOutOfRange`. |
| `services/lab/replay.py` | new | `ReplayEngine.run(replay_id)`: loads candidate, live `ConfigSnapshot`, builds candidate `MatchingConfig` (live snapshot with candidate overrides applied through `validate_value`), selects past items, evaluates each item with `decide_receipt`/`decide_lines` under both configs, writes `LAB_REPLAY_ITEM` rows + progress, finishes DONE/FAILED with `duration_ms`. Semaphore of `lab.max_concurrency`. Catches per-item `FusionError` as item outcome `no_input` (counted, never fails the run); an unexpected exception fails the run with a stored message. |
| `services/lab/inputs.py` | new | `PastItemInputs` loader: per past item reads the stored adjudication final extraction, latest customer resolution, latest match round (chosen receipt id = "before" stored decision), then `ReadOnlyFusion.find_receipts`/`get_receipt`/`find_transactions`/`list_receipt_applications`, aliases (`AliasLookup`, read), evidence (`fetch_receipt_evidence`, read). Marks `receipt_since_applied` when the stored chosen receipt now has unapplied <= 0.005. |
| `services/lab/readonly.py` | new | `ReadOnlyFusion`: wraps a `FusionClient` and exposes only `find_receipts`, `get_receipt`, `find_transactions`, `list_receipt_applications`, `run_report`, `get_payment_terms`, `customer_relationships`. No write method exists on it (pyright-enforced). |
| `services/lab/tasks.py` | new | `LabTaskRegistry` (process-wide: holds task references, `BOOT_ID`, `ReplayProgressHub` with `publish(replay_id, ProgressEvent)` / `subscribe(replay_id) -> AsyncIterator`), `start(replay_id, coro_factory)`; tasks are kept in a set until done (no GC loss). |
| `services/lab/csv.py` | new | `replay_items_csv(rows) -> Iterator[str]`; header `item_id,amount,currency,before,after,receipt_before,receipt_after,since_applied`; text cells starting with `= + - @ \t \r` prefixed with `'` (CSV injection). |
| `services/config.py` | change | `ConfigWriter.set` refactored onto private `_write_one(...)`; new `ConfigWriter.set_many(uow, changes: Sequence[KeyChange], principal, reason, *, tag: ChangeTag) -> dict[str, int]` (same validation, permission, per-key `expected_version`, audit; one transaction; every change row gets `tag.change_set_id`, `tag.lab_candidate_id`, `tag.lab_replay_id`). `ConfigAudit.record` gains optional `tag`. `KeyChange`, `ChangeTag` dataclasses. `PUT /config/{key}` behaviour unchanged. |
| `data/models/config.py` | change (append-only columns) | `ConfigChange.change_set_id: int|None`, `lab_candidate_id: int|None`, `lab_replay_id: int|None`. |
| `data/models/lab.py` | new (auto-imported by alembic env) | `LabCandidate`, `LabReplay`, `LabReplayItem` (section 4). |
| `data/repositories/lab.py` | new | `LabCandidateRepository(BaseRepository[LabCandidate])` (`list_recent(limit, open_only)`, `get_for_update(id)`, `count_open()`), `LabReplayRepository` (`latest_for(candidate_id)`, `get_for_update`, `running_for(candidate_id)`, `mark_progress(id, done, total, at)`, `finish(id, status, summary, at, duration_ms, error)`), `LabReplayItemRepository` (`add_many`, `page(replay_id, offset, limit, changed_only)`, `all_for(replay_id)`), `LabPastItemRepository` (`past_items(since, limit) -> list[int]`: work items with at least one `MATCH_CANDIDATE` round, created since `since`, newest first). |
| `data/repositories/config.py` | change | `ConfigChangeRepository.lab_version(keys) -> int` (count of distinct `COALESCE(CHANGE_SET_ID, -ID)` over rows whose key in keys); `ConfigSettingRepository.versions(keys) -> dict[str, int]`. |
| `data/repositories/retention.py` | change | `lab_item_candidates(cutoff, limit) -> list[int]` (LAB_REPLAY ids with status DONE/FAILED and `FINISHED_AT < cutoff` that still have items) and `purge_lab_items(replay_ids) -> int` (delete items only of those replays, re-checking status/finished_at in the DELETE's WHERE). |
| `services/retention/service.py` | change | `_purge_lab_items` step run under the `history_payload_days` cutoff; dry-run counts only; guard before the first delete (never a RUNNING replay, never without a cutoff). |
| `api/routers/retention.py` | change | `PurgeReportResponse.lab_replay_items`. |
| `api/schemas/lab.py` | new | Pydantic v2 request/response models (section 7). |
| `api/routers/lab.py` | new (auto-discovered) | The eight endpoints (section 7); maps `LabError` to the single error shape; SSE via `sse_starlette.EventSourceResponse(ping=PING_SECONDS)`. |
| `api/lab_deps.py` | new | `LabServiceDep` (builds `LabService` from uow factory, `RuntimeConfigDep`, `FusionClient` dep for the default pod, clock, `LabTaskRegistry` singleton). |
| `services/chat/tools/lab.py` | new (auto-discovered `TOOLS`) | `lab.propose`, `lab.replay`, `lab.promote`, `lab.discard` (section 7). |
| `services/chat/prompts.py` (or wherever the registry story puts `PromptKey.MATCHING` text) | change | none expected: `MATCHING` prompt key and its text are owned by chat-agent-tool-registry; this story only routes lab tools to it (group LAB). If the registry ships no MATCHING tool-group binding, the lab tools are offered under the principal's tool set like every other group. |

Web (generated only, no hand-written web code in this story):

| File | Change | Purpose |
|---|---|---|
| `web/lib/api/openapi.json`, `web/lib/api/schema.d.ts` | regenerated by `npm run api:sync` | OpenAPI contract for matching-lab-ui (TS-5 typegen before type-check, TS-10 type-only imports in generated types). `web/lib/api/stream-paths.ts` is NOT edited here (matching-lab-ui owns the web proxy entry for `/lab/replays/{id}/stream`). |

Docs:
| `api/src/cashapp/integrations/fusion/CONTRACTS.md` | no change | lab uses existing read rows only. |
| `docs/reference/settings.md` (owned by db-stored-settings) | append `lab.*` rows at merge (append-only block, coder adds if the file exists at its base; otherwise noted in validation.md for the merger). |

## 3 Test plan (nobody writes or runs these until step 5)

All API tests are pytest; `[unit]` = no DB (in-memory/sqlite uow from `tests/support/db.py`, `tests/support/fusion.py` fake), `[api]` = FastAPI `TestClient`/httpx `AsyncClient` with `tests/support/auth.py` principals, `[atp]` = `-m atp`.

| AC | Test (path::name) | Type |
|---|---|---|
| 1 | `api/tests/services/matching/test_decision.py::test_decide_receipt_matches_score_candidates_for_same_inputs` | unit |
| 1 | `…/test_decision.py::test_decide_receipt_human_hint_not_found_sets_problem` / `::test_decide_receipt_human_hint_currency_mismatch` / `::test_decide_receipt_human_hint_no_unapplied` | unit |
| 1 | `…/test_decision.py::test_decide_receipt_ambiguous_never_first_wins` | unit |
| 1 | `…/test_decision.py::test_decide_lines_uses_currency_tolerance_and_caps_amount` | unit |
| 1 | `…/test_decision.py::test_decision_module_imports_no_io` (static: module imports no `data.`, `pipeline.`, `integrations.fusion.client`, `sqlalchemy`) | unit |
| 1 | `api/tests/stations/test_match_receipt_runner.py::test_runner_delegates_to_decide_receipt` (spy) and `api/tests/stations/test_match_lines_runner.py::test_runner_delegates_to_decide_lines` | unit |
| 1 | existing matching/station tests, if present at the coder's base, run unchanged (regression on shared path) | unit |
| 2 | `api/tests/services/lab/test_service_candidates.py::test_create_candidate_returns_p_id_base_version_and_changes` | unit |
| 2 | `…::test_create_candidate_refuses_non_matching_key` (e.g. `retries.max_attempts`, `matching.unknown`) -> `LabKeyNotAllowed`, nothing written | unit |
| 2 | `…::test_create_candidate_refuses_out_of_bounds_per_key` (parametrized over LAB_BOUNDS edges, incl. bool-as-int) | unit |
| 2 | `…::test_create_candidate_refuses_invalid_value_via_validate_value` | unit |
| 2 | `…::test_create_candidate_refuses_empty_changes_and_noop_changes` | unit |
| 2 | `…::test_create_candidate_requires_lab_run` | unit |
| 2 | `api/tests/services/lab/test_service_replay.py::test_replay_returns_rp_id_running_then_done` | unit |
| 2 | `…::test_get_replay_result_shape_counts_money_by_currency_and_config_diff` (two currencies, never summed; MoneyStr 2 dp) | unit |
| 2 | `…::test_get_replay_marks_receipt_since_applied_not_newly_matched` | unit |
| 2 | `…::test_discard_closes_candidate_and_refuses_replay_or_promote_after` | unit |
| 2 | `…::test_replay_window_days_bounds` (`0`, `> lab.max_window_days` refused) | unit |
| 3 | `api/tests/services/lab/test_replay_read_only.py::test_replay_makes_zero_fusion_writes_and_zero_publishes` (spy FusionClient records every call; spy EventBus; asserts write methods `apply_receipt`, `unapply_receipt`, `set_receipt_comment`, `attach_to_receipt`, `rest_post` never called, `publish` never called) | unit |
| 3 | `…::test_replay_changes_no_work_item_reservation_or_outbox_rows` (row counts of WORK_ITEM, WORK_ITEM_HISTORY, RECEIPT_RESERVATION, MATCH_CANDIDATE, OUTBOX equal before/after) | unit |
| 3 | `…::test_readonly_fusion_exposes_no_write_method` | unit |
| 3 | `…::test_replay_evaluates_live_and_candidate_side_by_side` (one Fusion read per item feeds both decisions) | unit |
| 4 | `api/tests/services/lab/test_promote.py::test_promote_requires_config_write` | unit |
| 4 | `…::test_promote_requires_done_replay_of_that_candidate` (RUNNING, FAILED, other candidate's replay -> refused) | unit |
| 4 | `…::test_promote_stale_when_live_version_moved` -> `LabStale` message "Live config moved to v{N}", nothing written | unit |
| 4 | `…::test_promote_stale_when_expected_version_differs` | unit |
| 4 | `…::test_promote_requires_reason` | unit |
| 4 | `…::test_promote_writes_all_keys_one_lab_version_bump_with_candidate_and_replay_ids_on_history` | unit |
| 4 | `…::test_promote_uses_same_writer_as_put_config` (spy `ConfigWriter._write_one`; same audit row shape as `PUT /config/{key}`) | unit |
| 4 | `…::test_promote_rolls_back_all_keys_on_one_conflict` | unit |
| 4 | `…::test_promote_twice_refused_candidate_closed` | unit |
| 5 | `api/tests/migrations/test_lab_migration.py::test_upgrade_downgrade_lab_tables` | atp |
| 5 | `…::test_single_alembic_head` (`alembic heads` == 1) | unit |
| 5 | `api/tests/services/retention/test_lab_purge.py::test_purge_deletes_items_of_finished_replays_past_cutoff` | unit |
| 5 | `…::test_purge_never_touches_running_replay_or_recent_replay` | unit |
| 5 | `…::test_purge_dry_run_counts_and_deletes_nothing` | unit |
| 5 | `…::test_purge_disabled_when_history_payload_days_null` | unit |
| 6 | `api/tests/services/lab/test_replay_bounds.py::test_replay_caps_items_at_lab_max_items` | unit |
| 6 | `…::test_replay_concurrency_never_exceeds_lab_max_concurrency` (counting fake) | unit |
| 6 | `…::test_progress_done_total_persisted_and_published` | unit |
| 6 | `…::test_running_replay_from_previous_boot_reported_failed` (BOOT_ID differs, heartbeat stale -> FAILED persisted) | unit |
| 6 | `…::test_replay_failure_writes_failed_with_message` | unit |
| 6 | `…::test_one_running_replay_per_candidate` -> `LabReplayRunning` | unit |
| 6 | `…::test_no_scheduler_or_poller_registered` (static: lab package imports nothing from `pollers`/`workers`, no `asyncio.sleep` loop outside the SSE fallback) | unit |
| 7 | `api/tests/api/test_lab_router.py::test_post_candidates_201_and_403_without_lab_run` | api |
| 7 | `…::test_get_candidates_limit` | api |
| 7 | `…::test_post_replay_202_and_get_replay` | api |
| 7 | `…::test_replay_stream_sse_progress_done_and_heartbeat` (event names, `X-Accel-Buffering: no`) | api |
| 7 | `…::test_items_csv_content_type_and_injection_escaped` | api |
| 7 | `…::test_promote_409_stale_error_shape` (`code == "STALE"`, message "Live config moved to vN") | api |
| 7 | `…::test_promote_403_for_operator` | api |
| 7 | `…::test_discard_204_then_404_or_409` | api |
| 7 | `…::test_unknown_ids_404` and `::test_malformed_ids_422` | api |
| 7 | `api/tests/domain/test_principal.py::test_lab_run_granted_admin_and_operator_only` | unit |
| 7 | `api/tests/api/test_openapi.py::test_lab_routes_in_openapi` (the dumped schema contains the 8 paths; web `openapi.json` regenerated) | unit |
| 8 | `api/tests/services/chat/tools/test_lab_tools.py::test_lab_tools_registered_in_group_lab` (discovered via `TOOLS`) | unit |
| 8 | `…::test_lab_propose_creates_candidate_no_confirm_live_config_unchanged` | unit |
| 8 | `…::test_lab_replay_emits_tool_progress_and_returns_replay_card` | unit |
| 8 | `…::test_lab_promote_confirm_required_preview_has_diff_summary_version` | unit |
| 8 | `…::test_lab_promote_denied_without_config_write_not_offered` | unit |
| 8 | `…::test_lab_tool_and_router_promote_same_audit_rows` | unit |
| 8 | `…::test_lab_tools_use_matching_prompt_key` | unit |

Browser criteria: none in this story (no screen owned). The Lab board (`design/project/glass/Lab.dc.html`, design.md §3.7) is verified by matching-lab-ui's Playwright tests against this API.

Count: 60 named tests (plus the unchanged existing matching tests).

## 4 Data

ORM models (`data/models/lab.py`, upper snake case in the database, identity PKs, native JSON via `JsonDoc`, money via `MoneyNumeric`):

- `LAB_CANDIDATE`: `ID` identity PK; `CHANGES` JSON (`{key: value}` validated JSON); `BASE_VERSION` int (lab config version at creation); `BASE_KEY_VERSIONS` JSON (`{key: per-key version}` for the promote's per-key `expected_version`); `BASE_VALUES` JSON (live values at creation, for `config_diff.before`); `RATIONALE` varchar2(2000); `STATUS` (OPEN/PROMOTED/DISCARDED); `CREATED_BY`, `CREATED_BY_NAME`, `CREATED_AT`; `CLOSED_BY`, `CLOSED_AT`, `CLOSE_REASON` nullable; `PROMOTED_VERSION` nullable. Index `IX_LAB_CAND_STATUS_AT (STATUS, CREATED_AT)`.
- `LAB_REPLAY`: `ID` PK; `CANDIDATE_ID` FK `FK_LAB_REPLAY_CAND`; `STATUS` (RUNNING/DONE/FAILED; STALE is computed, never stored); `WINDOW_DAYS`; `LIVE_VERSION` (lab version the replay ran against); `DONE`, `TOTAL`; summary columns `CHANGED`, `NEWLY_MATCHED`, `NEWLY_FAILED`, `NEWLY_AMBIGUOUS`, `MONEY_BY_CURRENCY` JSON; `STARTED_BY`, `STARTED_AT`, `HEARTBEAT_AT`, `FINISHED_AT`, `DURATION_MS`, `RUNNER_BOOT_ID` varchar2(36), `ERROR` varchar2(1000). Index `IX_LAB_REPLAY_CAND (CANDIDATE_ID, STARTED_AT)`, `IX_LAB_REPLAY_STATUS_FIN (STATUS, FINISHED_AT)`.
- `LAB_REPLAY_ITEM`: `ID` PK; `REPLAY_ID` FK `FK_LAB_RI_REPLAY`; `WORK_ITEM_ID` (no FK: purge of work items must not be blocked; plain BigInteger + index); `AMOUNT` MoneyNumeric; `CURRENCY` CHAR(3); `BEFORE_OUTCOME`, `AFTER_OUTCOME` varchar2(20); `BEFORE_RECEIPT_ID`, `AFTER_RECEIPT_ID` nullable; `CHANGED` bool; `SINCE_APPLIED` bool; `DETAIL` JSON (rules, reasons, line counts; no artifact text). Index `IX_LAB_RI_REPLAY_CHANGED (REPLAY_ID, CHANGED)`.
- `CONFIG_CHANGE` + columns `CHANGE_SET_ID` (nullable int; promote uses the candidate's id), `LAB_CANDIDATE_ID`, `LAB_REPLAY_ID` (nullable int, no FK so config history never depends on lab rows).

ONE Alembic revision: `api/alembic/versions/s48_lab_replay.py`, `revision = "s48_lab_replay"`. Coder sets `down_revision` to the single head at its base (today `s45_retention_purge`); per split.md "Migrations" the merger re-points it in merge order so it follows chat-agent-tool-registry, db-stored-settings, engine-control-api, html-progress-reports (lab merges after those). Creates the three tables + indexes, adds the three `CONFIG_CHANGE` columns; downgrade drops them. No data seeding (lab.* keys use registry defaults; a missing row means default, version 0). Applied to DEV ATP only by db-sync; never run by the coder.

## 5 Config / env

No env variables. DB config keys owned here (append-only `lab.*` block in `domain/config_keys.py`, group `lab`, not restart_required, not secret_ref):

| Key | Type | Default | Validation |
|---|---|---|---|
| `lab.max_items` | int | 2000 | 1..20000 |
| `lab.max_concurrency` | int | 4 | 1..16 (each worker does Fusion reads through the MCP; kept low to protect the pod) |
| `lab.default_window_days` | int | 30 | 1..`lab.max_window_days` |
| `lab.max_window_days` | int | 90 | 1..365 |
| `lab.chat_wait_seconds` | int | 120 | 0..600 (how long `lab.replay` in chat waits before returning a RUNNING card) |

Read existing keys: `matching.date_window_days`, `matching.tolerances`, `matching.bank_fee_bands`, `matching.scorer_weights`, `matching.min_score` (the lab-eligible set), `retention.history_payload_days` (replay item purge), `mcp.*` / `fusion.*` through `FusionClient` (fusion-mcp-transport). Per-key hard bounds (`domain/lab.py::LAB_BOUNDS`): date_window_days 0..30; each tolerance 0.00..5.00 (Decimal); bank-fee band max_fee <= 100.00 and min_fee >= 0; each scorer weight 0..10; min_score 0..10.

## 6 Risks and the coder's gates

- **Shared-file collisions:** `services/config.py` and `data/models/config.py` are also touched by db-stored-settings (last_changed fields, restart note); `domain/config_keys.py` and `domain/principal.py` are append-only blocks (split.md). Coder edits only the named functions/blocks; `ConfigWriter.set` signature unchanged.
- **Runner refactor regression:** the decision lift must be behaviour-identical; no change to stored payloads/history shapes. Keep `score_candidates` and `plan_lines` untouched.
- **MCP read cost:** 2000 items x (1-2 receipt searches + evidence + transactions) through the MCP server. Bounded by `lab.max_concurrency`; per-item Fusion errors are `no_input`, never retried in a loop.
- **Multi-replica API:** a replay runs in the replica that received the POST; SSE on another replica falls back to reading `LAB_REPLAY` progress every 2 s (bounded to the stream's lifetime; not a poller, it is request-scoped like `/flow/stream`).
- **Stale definition:** lab version counts change sets on lab keys only; a non-matching config change does not stale a replay (correct: it cannot change the matcher).
- **Registry contract drift:** `ToolContext` progress callback name (section 7) must match chat-agent-tool-registry's plan; coder imports, never redefines.
- **Purge guard:** delete only items of DONE/FAILED replays with `FINISHED_AT < cutoff`, checked inside the DELETE predicate; dry-run counts only.
- Gates (coder, no tests): `cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`; after regenerating the client `cd web && npm ci && npm run api:sync && npx eslint . && npx next typegen && npx tsc --noEmit`.

## 7 Interfaces provided (pinned)

### 7.1 For matching-lab-ui (plannable: true)

Routes (all JSON, single error shape `ErrorEnvelope`; ids are strings `p_NNNN` / `rp_NNNN`; money is `MoneyStr` = decimal string, 2 dp):

| Method + path | Permission | Request | Response |
|---|---|---|---|
| `POST /lab/candidates` | LAB_RUN | `CandidateCreateIn{changes: dict[str, JsonValue] (min 1), rationale: str (1..2000)}` | 201 `CandidateOut` |
| `GET /lab/candidates?limit=20&status=OPEN` | LAB_RUN | `limit` 1..100 default 20; `status` optional | 200 `CandidateListOut{items: list[CandidateOut], open_count: int, live_version: int}` |
| `POST /lab/candidates/{id}/replays` | LAB_RUN | `ReplayStartIn{window_days: int \| null}` (null = `lab.default_window_days`) | 202 `ReplayStartOut{id, candidate_id, status: "RUNNING", total}` |
| `GET /lab/replays/{id}` | LAB_RUN | - | 200 `ReplayResultOut` |
| `GET /lab/replays/{id}/stream` | LAB_RUN | - | SSE (below) |
| `GET /lab/replays/{id}/items.csv` | LAB_RUN | - | 200 `text/csv`, `Content-Disposition: attachment; filename="rp_NNNN-items.csv"` |
| `POST /lab/candidates/{id}/promote` | CONFIG_WRITE | `PromoteIn{replay_id: str, reason: str (1..1000), expected_version: int}` | 200 `PromoteOut{candidate_id, replay_id, new_version: int, keys: list[str], promoted_by: str, promoted_at}` |
| `POST /lab/candidates/{id}/discard` | LAB_RUN | `DiscardIn{reason: str \| null}` | 200 `CandidateOut` (status DISCARDED) |

Schemas:
```
CandidateOut{id: str, status: "OPEN"|"PROMOTED"|"DISCARDED", base_version: int, live_version: int,
  changes: dict[str, JsonValue], config_diff: list[ConfigDiffRow], rationale: str,
  created_by: str, created_by_name: str, created_at: datetime,
  latest_replay: ReplaySummaryOut | null, promoted_version: int | null}
ConfigDiffRow{key: str, before: JsonValue, after: JsonValue}
ReplaySummaryOut{id: str, status: "RUNNING"|"DONE"|"FAILED"|"STALE", done: int, total: int}
ReplayResultOut{id: str, candidate_id: str, status: "RUNNING"|"DONE"|"FAILED"|"STALE",
  window_days: int, live_version: int, base_version: int, done: int, total: int,
  changed: int, newly_matched: int, newly_failed: int, newly_ambiguous: int,
  money_by_currency: list[MoneyByCurrency], items: list[ReplayItemOut],
  config_diff: list[ConfigDiffRow], duration_ms: int | null, started_at: datetime,
  finished_at: datetime | null, error: str | null, stale_message: str | null}
MoneyByCurrency{currency: str, newly_matched: MoneyStr, newly_unmatched: MoneyStr, items: int}
ReplayItemOut{item_id: int, amount: MoneyStr, currency: str,
  before: ReplayOutcome, after: ReplayOutcome, receipt_before: int | null,
  receipt_after: int | null, since_applied: bool}
ReplayOutcome = "matched"|"no_receipt"|"ambiguous"|"variance"|"lines_failed"|"no_input"
```
`items` in `ReplayResultOut` holds changed items only, at most 200 (the CSV has all rows). `stale_message` = "Live config moved to v{N}" when status is STALE.

Errors (status, `error.code`): 409 `STALE` ("Live config moved to v{N}"), 409 `REPLAY_NOT_DONE`, 409 `REPLAY_RUNNING`, 409 `CANDIDATE_CLOSED`, 422 `KEY_NOT_ALLOWED`, 422 `OUT_OF_BOUNDS`, 422 `INVALID_VALUE` (details = validate_value errors), 422 `REASON_REQUIRED`, 422 `WINDOW_OUT_OF_RANGE`, 422 `INVALID_ID`, 404 `CANDIDATE_NOT_FOUND` / `REPLAY_NOT_FOUND`, 403 standard.

SSE `GET /lab/replays/{id}/stream` (`text/event-stream`, `X-Accel-Buffering: no`, `Cache-Control: no-cache`, ping comment every `PING_SECONDS` (15 s), monotonic `id`):
- `event: progress` `data: {"replay_id": "rp_0001", "status": "RUNNING", "done": 1140, "total": 1912}`
- `event: done` `data: {"replay_id", "status": "DONE"|"STALE", "done", "total", "changed", "newly_matched", "newly_failed", "newly_ambiguous", "duration_ms"}` then the stream closes
- `event: failed` `data: {"replay_id", "status": "FAILED", "message"}` then closes
- A stream opened on a finished replay emits one `done`/`failed` and closes.

Web proxy note: matching-lab-ui adds the `/lab/replays/<id>/stream` pattern to `web/lib/api/stream-paths.ts` (currently exact-match only); this story does not edit web code.
Nav count: `GET /lab/candidates?limit=1&status=OPEN` -> `open_count`.

### 7.2 For chat-agent-tool-registry consumers / assistant (tools in `services/chat/tools/lab.py`, group `LAB`; plannable: true)

```
lab.propose  input LabProposeIn{changes: dict[str, JsonValue], rationale: str}
             output CandidateOut-equivalent LabCandidateCard (table_card-free: returns
             {candidate_id, base_version, config_diff}), permission LAB_RUN, mutating False,
             confirm_required False, audit_label "lab.propose"
lab.replay   input LabReplayIn{candidate_id: str, window_days: int | None}
             permission LAB_RUN, mutating False, confirm_required False, audit_label "lab.replay";
             reports progress through ToolContext's progress callback (tool_progress{call_id,
             done, total}); waits up to lab.chat_wait_seconds, returns replay_card
lab.promote  input LabPromoteIn{candidate_id, replay_id, reason, expected_version}
             permission CONFIG_WRITE, mutating True, confirm_required True,
             preview ConfirmPreview{what: "Promote p_NNNN to live", before/after: config diff
             lines, who, reason prompt, extra: replay summary + "expected version N"},
             audit_label "lab.promote"; handler = LabService.promote (same as router)
lab.discard  input LabDiscardIn{candidate_id, reason: str | None}, permission LAB_RUN,
             mutating True, confirm_required True, preview = candidate diff, audit_label "lab.discard"
```
`replay_card` (schema owned by chat-agent-tool-registry in `api/schemas/chat.py`) is filled with: `replay_id`, `candidate_id`, `status`, `done`, `total`, `changed`, `newly_matched`, `newly_failed`, `newly_ambiguous`, `money_by_currency` (list as above), `open_in_lab_href = "/lab?candidate=p_NNNN"`. If the registry's `replay_card` lacks a field, the tool fills only what it has (no second card type).
Required from the registry (consumed, not provided): `ToolSpec`, `ToolGroup.LAB`, `ToolContext{principal, uow_factory, clock, services}` plus a progress callback on the context (registry's chosen name, e.g. `await ctx.progress(done, total)`), `ConfirmPreview`, `ReplayCard`, `PromptKey.MATCHING`.

### 7.3 Python service contract (for the router, the tools and tests)

```python
class LabService:
    def __init__(self, uow_factory: UowFactory, config: RuntimeConfig, fusion: FusionClient,
                 tasks: LabTaskRegistry, clock: Clock, aliases: AliasLookup) -> None
    async def create_candidate(self, changes: Mapping[str, object], rationale: str,
                               principal: Principal) -> Candidate
    async def list_candidates(self, principal: Principal, *, limit: int = 20,
                              status: CandidateStatus | None = None) -> CandidateList
    async def replay(self, candidate_id: str, window_days: int | None,
                     principal: Principal) -> Replay
    async def get_replay(self, replay_id: str, principal: Principal) -> ReplayResult
    def stream(self, replay_id: str, principal: Principal) -> AsyncIterator[ProgressEvent]
    async def items_csv(self, replay_id: str, principal: Principal) -> AsyncIterator[str]
    async def promote(self, candidate_id: str, replay_id: str, reason: str,
                      expected_version: int, principal: Principal) -> Promotion
    async def discard(self, candidate_id: str, principal: Principal,
                      reason: str | None = None) -> Candidate
```
`Candidate`, `Replay`, `ReplayResult`, `Promotion`, `ProgressEvent` are frozen dataclasses in `services/lab/service.py` mirroring the schemas above.

## Assumptions

- **Lab config version** = count of distinct change sets on `LAB_KEYS` in `CONFIG_CHANGE` (`COALESCE(CHANGE_SET_ID, -ID)`); there is no global config version in the code today and adding a counter table is outside the story's three tables. A promote of three keys is one bump; each `PUT /config/matching.*` is one bump.
- `matching.*` keys plus "the date window/tolerance keys" are the same set today (`matching.date_window_days`, `matching.tolerances`); `discount.*` stays out (story: "only matching.*").
- Per-key hard bounds live in `domain/lab.py` (the lab's own policy), not on `ConfigKey`; if chat-agent-tool-registry ships key-spec bounds, the lab applies both (the stricter wins).
- "Before" is recomputed with the live config over the same freshly read candidates (side by side, AC3), not taken from the stored historical decision; the stored decision is used only to flag `since_applied`.
- Past items = work items with at least one `MATCH_CANDIDATE` round created within `window_days`, newest first, capped at `lab.max_items`; items without a stored extraction or resolution are `no_input` and never counted as changed.
- `lab.discard` is mutating with confirm (it closes the candidate); `lab.propose` and `lab.replay` are not mutating live state (they write only LAB rows) so no confirm, per the story.
- Restart detection uses `RUNNER_BOOT_ID` + `HEARTBEAT_AT` (stale after 60 s) evaluated on read, so no startup hook in `main.py` is needed (no story edits `main.py`).
- No hand-written web code here; the regenerated `openapi.json`/`schema.d.ts` are the only web files.
- The worktree has no existing matching tests at planning time (`api/tests` holds support files only); AC1's "existing matching tests unchanged" applies to any present at the coder's base.
