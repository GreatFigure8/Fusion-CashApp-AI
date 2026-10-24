# Plan: fusion-mcp-transport

Story: [story.md](story.md). Skills applied: python-web-app:building-python-web-apps (routes -> services -> data, SDK isolated behind a service/integration module), python-llm-features:building-llm-backed-features (chat tool descriptions are prompt surface; fail closed; live calls marked `live`). claude-api not needed: this story makes no Claude call (chat tools only register specs). No `web/` source changes (only the regenerated `web/lib/api/openapi.json`), so no nextjs.md rule ids apply.

## 1 Approach

- research.md's consensus is "reuse the existing seams" (Recommendation, line 7). Here the seam is `FusionClient` (`integrations/fusion/client.py:48`). Its Protocol stays **unchanged**, so stations, the watcher, lab replay and auto-fix are untouched. Following input.md Item 7 (final decision), one new implementation, `McpFusionClient`, composes two transports.
  - **Reads and REST writes:** an `McpClient` (official `mcp` SDK 2.3, streamable HTTP, `client_credentials` JWT, scope `greenlight/mcp`).
  - **Apply and unapply:** the existing direct SOAP path. Its HTTP core moves from `transport.py` into `soap.py`.
- `HttpFusionClient`, the REST half of `transport.py` and the BIP `runReport` envelope are deleted, so there is one read path.
- `run_report(path, params)` keeps its signature and its `bytes` return. It looks the path up in a catalog of SQL data models packaged in `integrations/fusion/datamodels/`, binds the parameters as escaped literals, and runs the SQL through `run_query` (with `keep_result` + `fetch_rows`). It renders the rows back as the BIP `DATA_DS/G_1` XML that callers already parse, so `evidence.py`, preflight and the signal study keep their parsers.
- Every MCP call goes through one recorder, which writes `MCP_CALL_LOG` (hashes and counts, never SQL or bodies). That feeds "Last call" and the audit.
- The status and test endpoints are a new auto-discovered router. The chat tools are a new tool module (registry discovery).
- Deviation from split.md (recorded under Assumptions): this story needs one Alembic revision for `MCP_CALL_LOG`.

## 2 Files

All paths are under `api/src/cashapp/` unless they start with `api/`, `docs/`, `fusion/`, `web/` or `CLAUDE.md`.

**Create**

| Path | Purpose |
|---|---|
| `integrations/mcp/__init__.py` | Re-exports `McpClient`, `McpHealth`, `McpToolResult`, `McpCallEntry`, `REQUIRED_TOOLS`, `StreamableHttpMcpClient`, `FakeMcpClient`, `build_mcp_client`. |
| `integrations/mcp/client.py` | `McpClient` Protocol, `McpHealth`, `McpToolResult`, `McpClientOptions`, `REQUIRED_TOOLS`, `StreamableHttpMcpClient`. One long-lived `ClientSession` per process. It reconnects on a transport error, or when the connection tuple (`server_url`, `token_url`, `client_id`, `client_secret_ref`) read from `RuntimeSettings` changes, so it is hot and needs no restart. It retries with jittered backoff on transport errors, 5xx and one 401 (the 401 retry refreshes the token), up to `McpClientOptions.max_attempts=3`. Results are parsed from the text content with `json.loads(parse_float=Decimal)`, never from the float `structuredContent`. |
| `integrations/mcp/token.py` | `ClientCredentialsTokenProvider`. It POSTs `token_url` with HTTP Basic `client_id:secret` and the body `grant_type=client_credentials&scope=<mcp.scope>`. The secret is resolved through `cashapp/secrets.py` from `mcp.client_secret_ref` at use. The token is cached until `expires_in - 60 s`, guarded by an `asyncio.Lock` so only one refresh runs at a time. `invalidate()` forces a refresh. The token, the secret and the response body are never logged. |
| `integrations/mcp/errors.py` | `McpError(code: ErrorCode, message, retryable, outcome_unknown)` and `error_from_tool_text(text, *, write) -> FusionError`. It maps the server's `ToolError` texts (fusion-sql-mcp `rest_tools.py`, `fallback.py`, `rest.py:121-128`): `Fusion answered (\d{3})` goes to the existing `errors.error_from_http(status, text)`; "No answer from the pod" goes to `FUSION_TRANSIENT`; "Write-back is off" and "not on … write allowlist" go to `FUSION_WRITE_DISABLED`; anything else goes to `FUSION_FAULT` (not retryable). Transport failures and 5xx go to `FUSION_TRANSIENT`. For a write the outcome is unknown unless the request was certainly not sent. |
| `integrations/mcp/sql.py` | `assert_single_select(sql)` strips comments and string literals, then requires exactly one statement starting with `SELECT` or `WITH`. It refuses a `;` mid-text, any DML/DDL/PLSQL keyword at statement start, and `{{slices}}`. `render_data_model(sql, params) -> str` replaces each `:P_NAME` bind with an Oracle literal (single quotes doubled; each value checked against a per-bind pattern from the catalog). It fails with `FUSION_FAULT` on an unbound or unknown bind, and strips leading `--` comment lines. `sql_hash(sql) -> str` is sha256 hex. |
| `integrations/mcp/recorder.py` | `McpCallEntry{tool, source, target_hash, target_label, rows, duration_ms, outcome, error_code, principal_id, principal_kind}`, the `McpCallRecorder` Protocol, `DbMcpCallRecorder` (its own short UoW, swallows and logs its own failure) and `InMemoryMcpCallRecorder`. `target_label` holds a REST path with its query stripped, or `sql:<first 12 chars of the hash>`. The principal comes from a `contextvars` actor set by the caller (router or tool), with the system principal as the default. |
| `integrations/mcp/fake.py` | `FakeMcpClient`: scripted handlers `on_tool(name, fn)` plus helpers `rest_pages(path_prefix, pages)` and `query_result(marker, columns, rows)`. It records every call, can be told to fail N times with a transport error, a ToolError text or a 401, and implements `health()`. |
| `integrations/mcp/factory.py` | `build_mcp_client(runtime, secrets, recorder) -> McpClient`, registered in `workers/container.py` and `api/mcp_deps.py`. |
| `integrations/fusion/mcp_client.py` | `McpFusionClient` implements every `FusionClient` method (section 7). It reuses the mappers and `query.py` (`q_in`, `q_literal`, `chunked`, `FIELDS_*`). `_rest_paged()` sends `onlyData=true`, `fields`, `limit`, `offset` and follows `has_more`, one server call per page, up to `max_pages`. `verify_framework()` runs the `in (...)` probe. `apply_receipt`/`unapply_receipt` delegate to `soap.SoapTransport` after `WriteGuard.check`. |
| `integrations/fusion/datamodels/__init__.py` | `DataModel{path, sql_file, binds: dict[str, re.Pattern]}`. `CATALOG` keys the existing report paths (`/Custom/CashApp/CashAppRelationships.xdo`, `/Custom/CashApp/CashAppReceiptSignals.xdo`). `load_sql(path)` uses `importlib.resources`. |
| `integrations/fusion/datamodels/relationships.sql`, `receipt_signals.sql` | `git mv` from `fusion/bip/`, content unchanged, so one copy is packaged in the image. |
| `data/models/mcp_call_log.py` | ORM `McpCallLog` (section 4). |
| `data/repositories/mcp_call_log.py` | `McpCallLogRepository(BaseRepository[McpCallLog])` with `latest() -> McpCallLog \| None`, `purge_before(cutoff) -> int`. |
| `domain/mcp_calls.py` | `McpCallOutcome(StrEnum)`: OK, ERROR, REFUSED. |
| `api/alembic/versions/s48_mcp_call_log.py` | The one revision (section 4). |
| `services/mcp_status.py` | `McpStatusService(mcp, fusion_factory, uow_factory, runtime, clock)`. `status() -> McpStatus` runs a live `health()`, cached in-process for 15 s, plus the latest log row. `test(principal) -> McpTestResult` runs a token fetch, `list_tools`, one `fusion_rest_get` probe (`receivablesInvoices`, `limit=1`, `fields=TransactionNumber`) and `verify_framework()`. |
| `services/fusion_explore.py` | `FusionExploreService(mcp, fusion_factory, runtime)`: `query(sql, max_rows)`, `rest_get(path, params)` (delegates to `McpFusionClient.rest_get`, the same read path), `rest_describe(path)`, `list_sources()`. The SQL guard runs before any server call. The row cap is `min(max_rows, mcp.max_rows)`. |
| `services/chat/tools/fusion_reads.py` | `TOOLS: list[ToolSpec]`: `fusion.query`, `fusion.rest_get`, `fusion.rest_describe`, `fusion.list_sources` (section 7). |
| `api/schemas/mcp.py` | `McpStatusOut`, `McpLastCallOut`, `McpTestOut` (section 7). |
| `api/mcp_deps.py` | `get_mcp_client()` (lru_cache) and `McpClientDep`. Tests override them with `FakeMcpClient`. |
| `api/routers/integrations_mcp.py` | `router` with prefix `/integrations/mcp`: `GET /status` (CONFIG_READ), `POST /test` (CONFIG_WRITE). Auto-discovered. |

**Change**

| Path | Change |
|---|---|
| `integrations/fusion/client.py` | Keep the Protocol, `ReceiptDateBasis` and the `_map_*` helpers; delete `HttpFusionClient`. |
| `integrations/fusion/soap.py` | Gains `SoapTransport`: the retry core moved from `transport.py` with the same write-retry semantics (`_NOT_PROCESSED`, `{401, 503}`, `outcome_unknown`), plus `post_soap()` and `get_wsdl()`. It is built from the pod's `base_url`, `username` and `password_ref`, resolved through `secrets.py`. It is the only module allowed to open an HTTP client to a Fusion host. |
| `integrations/fusion/transport.py` | **Delete.** `loads_decimal` moves to `integrations/fusion/jsonutil.py`, which is also used by `mcp/client.py`. |
| `integrations/fusion/bip.py` | Delete `BIP_PATH`, `build_run_report_envelope` and `parse_run_report_response`. Add `rows_to_data_ds_xml(columns, rows) -> bytes`: `<DATA_DS><G_1><COL>v</COL>…</G_1></DATA_DS>`, upper-cased column names, XML-escaped, `None` omitted. Keep `parse_relationships_xml` and `RELATIONSHIPS_PARAM`. |
| `integrations/fusion/factory.py` | `FusionClientFactory(runtime, mcp, recorder, secrets)`. `for_pod(name=None) -> McpFusionClient` resolves the pod from `fusion.pods` and the MCP source as `pods[pod].mcp_source or mcp.fusion_source`, failing with a clear `KeyError` that names the pod. `build_fusion_client(...)` now takes the container's runtime settings and MCP client. |
| `integrations/fusion/guard.py` | `WriteGuard.from_runtime(runtime, env, pod_name, source_environment)` is the only constructor (it replaces `from_settings`). It refuses when `fusion.write_enabled` is false, when the pod is `is_production` and `env != "prod"`, or when the MCP `list_sources` entry for the source says `environment == "production"` and `env != "prod"`. `WRITE_METHODS` gains nothing: every REST write path already goes through `set_receipt_comment`, `attach_to_receipt` or `rest_post`. |
| `integrations/fusion/__init__.py` | Export `McpFusionClient`; drop `HttpFusionClient`, `FusionClientOptions` (renamed `McpFusionOptions{chunk_size=50, page_size=500, max_pages=200}` in `mcp_client.py`). |
| `integrations/fusion/CONTRACTS.md` | Add a "Transport" column (MCP or SOAP) to every row. Mark the BIP `runReport` row "removed (ad-hoc SQL via run_query)". Add rows for the MCP tool names and arguments, `RestOutput{status, body, has_more, duration_ms, account_used}`, `QueryOutput{columns, rows, truncated, total_rows, result_id, status, error}`, and the server-sent `REST-Framework-Version` (fusion-sql-mcp `rest.py:221`, `models.py:257`). |
| `services/matching/evidence.py` | Bring it into line with `receipt_signals.sql`. The binds become `P_DATE_FROM`/`P_DATE_TO` (min/max receipt date, `YYYY-MM-DD`). The columns become `CASH_RECEIPT_ID` and `PAYER_BANK_ACCOUNT_HASH`, which today's parser misreads as `RECEIPT_ID`/`PAYER_BANK_ACCOUNT`, an existing defect that this path change brings to light. |
| `api/fusion_deps.py`, `api/routers/exceptions.py`, `workers/container.py` | Build through the new factory; the container registers `McpClient` and `McpCallRecorder`. Worker start calls `verify_framework()`: a 400 aborts start with a clear message; a transport error is logged and start continues. |
| `tools/preflight/checks.py`, `tools/preflight/cli.py` | Checks become: `REQUIRED_TOOLS` present, the framework probe, SOAP `?WSDL` via `SoapTransport.get_wsdl` (the `createApplyReceipt` operation), the relationships data model via `run_report`, and the `attachments` child via `rest_describe`. The BIP WSDL check is removed. |
| `tools/receipt_signal_study/__main__.py`, `collect.py`, `tools/testdata/cli.py` | Use the new factory. `testdata` POSTs go through `rest_post`, which is `fusion_rest_write` (guarded). |
| `domain/config_keys.py` | Append the `mcp.*` block (section 5). Extend db-stored-settings' pod model with `mcp_source: str \| None = None` (append-only field). |
| `api/pyproject.toml`, `api/uv.lock` | Add `mcp>=2.3,<3` (the version the server pins; its client uses `httpx2`). |
| `CLAUDE.md` | Rewrite non-negotiable 9 and "Fusion integration" (AC10). Reads and REST writes go through the fusion-sql-mcp (Greenlight) server behind `FusionClient`. The SOAP `createApplyReceipt`/unapply is the one direct call, made from the API with credentials from Vault. Never OIC. Relationships and receipt signals are ad-hoc SQL data models run through `run_query`, so no catalog report is created per tenant. Record "refined 2026-10-23 (bmn-ui-techy-redesign, fusion-mcp-transport)". |
| `fusion/bip/README.md`, `fusion/SETUP.md`, `fusion/bip/*.report.md` | Note that the SQL moved to `integrations/fusion/datamodels/` and runs through the MCP. Catalog report creation is no longer required. |
| `docs/reference/settings.md` | Add the `mcp.*` rows (that file is created by db-stored-settings). |
| `web/lib/api/openapi.json` | Regenerated with `npm run api:sync`. |

## 3 Test plan

Nobody writes or runs these until step 5. Every test lives in `api/tests/`.

| AC | Test (path::name) | Type |
|---|---|---|
| 1 | `test_mcp_client.py::test_call_tool_returns_decimal_parsed_body` | unit |
| 1 | `test_mcp_client.py::test_list_tools_and_health_shape` | unit |
| 1 | `test_mcp_client.py::test_token_cached_until_expiry_then_refreshed` | unit (httpx mock transport, fake clock) |
| 1 | `test_mcp_client.py::test_401_invalidates_token_and_retries_once` | unit |
| 1 | `test_mcp_client.py::test_transport_error_and_5xx_retry_with_backoff_then_fusion_transient` | unit |
| 1 | `test_mcp_client.py::test_write_retry_only_when_not_sent_else_outcome_unknown` | unit |
| 1 | `test_mcp_client.py::test_secret_resolved_from_vault_ref_never_logged` | unit (caplog) |
| 1 | `test_mcp_client.py::test_reconnects_when_connection_settings_change` | unit |
| 1 | `test_mcp_errors.py::test_tool_text_mapping` (parametrized: 400, 404 NotAuthorizedOrNotFound, 500, no answer, write-back off, allowlist, unknown) | unit |
| 2 | `test_mcp_config_keys.py::test_mcp_keys_registered_with_types_defaults_groups` | unit |
| 2 | `test_mcp_config_keys.py::test_client_secret_ref_is_secret_ref_and_rejects_plaintext` | unit |
| 2 | `test_mcp_config_keys.py::test_pod_mcp_source_resolution_and_fallback` | unit |
| 3 | `test_fusion_client_contract.py` parametrized over `FakeFusionClient` and `McpFusionClient`+`FakeMcpClient`: `::test_find_transactions_invoices_and_credit_memos`, `::test_find_receipts_by_receipt_and_creation_date`, `::test_receipts_created_since_ordered_and_limited`, `::test_get_receipt`, `::test_list_receipt_and_transaction_applications`, `::test_get_customer_account_and_not_found`, `::test_get_payment_terms`, `::test_list_receipt_attachments`, `::test_customer_relationships`, `::test_rest_get` | unit |
| 3 | `test_mcp_fusion_client.py::test_paging_follows_has_more_one_call_per_page` | unit |
| 3 | `test_mcp_fusion_client.py::test_paging_stops_on_empty_page_and_max_pages_fault` | unit |
| 3 | `test_mcp_fusion_client.py::test_params_include_only_data_fields_and_escaped_q` | unit |
| 3 | `test_mcp_fusion_client.py::test_verify_framework_fails_loudly_on_400` | unit |
| 3 | `test_mcp_fusion_client.py::test_run_report_renders_sql_binds_and_returns_data_ds_xml` | unit |
| 3 | `test_mcp_fusion_client.py::test_run_report_keep_result_fetches_all_rows` | unit |
| 3 | `test_mcp_fusion_client.py::test_unbound_bind_or_bad_value_is_fusion_fault` | unit |
| 3 | `test_mcp_fusion_client.py::test_writes_use_fusion_rest_write_paths_and_bodies` | unit |
| 3 | `test_mcp_fusion_client.py::test_apply_and_unapply_go_to_soap_not_mcp` | unit (httpx mock for SOAP, spy MCP) |
| 3 | `test_mcp_fusion_client.py::test_get_raw_wsdl_via_soap_else_fault` | unit |
| 3 | `test_receipt_evidence.py::test_signals_binds_and_columns_match_sql` | unit |
| 4 | `test_fusion_factory.py::test_for_pod_returns_mcp_client_and_unknown_pod_error` | unit |
| 4 | `test_fusion_static.py::test_no_fusion_http_outside_soap` (AST scan of `src/cashapp`: no `httpx` import in `integrations/fusion/*` except `soap.py`; no `/fscmRestApi`, `/crmRestApi` or `xmlpserver` URLs built for an HTTP call outside `integrations/fusion/query.py` (path constants) and `soap.py`; `HttpFusionClient` and `transport.py` gone) | unit (static) |
| 5 | `test_fusion_guard.py::test_apply_refused_when_write_disabled` | unit |
| 5 | `test_fusion_guard.py::test_apply_refused_on_production_pod_outside_prod` | unit |
| 5 | `test_fusion_guard.py::test_rest_writes_refused_when_write_disabled` (parametrized: comment, attach, rest_post) | unit |
| 5 | `test_fusion_guard.py::test_rest_writes_refused_on_production_pod_outside_prod` | unit |
| 5 | `test_fusion_guard.py::test_writes_refused_when_mcp_source_reports_production` | unit |
| 5 | `test_fusion_guard.py::test_refusal_happens_before_any_io` | unit |
| 6 | `test_mcp_recorder.py::test_every_call_recorded_with_principal_or_system` | unit |
| 6 | `test_mcp_recorder.py::test_sql_and_bodies_never_stored_or_logged` | unit (caplog + row inspection) |
| 6 | `test_mcp_recorder.py::test_recorder_failure_does_not_fail_the_call` | unit |
| 6 | `test_mcp_call_log_repo.py::test_latest_and_purge_before` | integration (`-m atp`) |
| 7 | `test_integrations_mcp_router.py::test_status_shape_and_last_call` | api |
| 7 | `test_integrations_mcp_router.py::test_status_unhealthy_when_server_down` | api |
| 7 | `test_integrations_mcp_router.py::test_status_requires_config_read` | api |
| 7 | `test_integrations_mcp_router.py::test_test_endpoint_shape_and_error` | api |
| 7 | `test_integrations_mcp_router.py::test_test_requires_config_write_and_records_principal` | api |
| 7 | `test_integrations_mcp_router.py::test_secret_never_in_responses` | api |
| 8 | `test_chat_tools_fusion_reads.py::test_four_tools_registered_read_only_no_confirm_group_fusion_reads` | unit |
| 8 | `test_chat_tools_fusion_reads.py::test_query_guard_refuses_non_select` (parametrized: DML, two statements, PL/SQL block, comment-hidden `;`, `{{slices}}`) | unit |
| 8 | `test_chat_tools_fusion_reads.py::test_query_row_cap_from_config` | unit |
| 8 | `test_chat_tools_fusion_reads.py::test_tools_need_reports_read` | unit |
| 8 | `test_chat_tools_fusion_reads.py::test_rest_get_uses_fusion_client_read_path` | unit |
| 9 | `test_mcp_live.py::test_list_tools_contains_required` | integration (`-m live`) |
| 9 | `test_mcp_live.py::test_standard_receipts_page_decodes` | integration (`-m live`) |
| 9 | `test_mcp_live.py::test_invoice_lookup_decodes` | integration (`-m live`) |
| 9 | `test_fusion_contracts_doc.py::test_every_row_has_transport_mcp_or_soap` | unit |
| 10 | `test_claude_md.py::test_non_negotiable_9_refined_with_date` | unit (static) |
| mig | `test_migration_mcp_call_log.py::test_upgrade_downgrade` | integration (`-m atp`) |

There are 61 named tests (parametrized cases count once). No browser criteria: the Settings and Engine boards that consume this story belong to settings-screen-redesign and engine-control-panel-ui.

## 4 Data

`MCP_CALL_LOG` (ORM `data/models/mcp_call_log.py`, auto-imported by `alembic/env.py`):

| Column | Type |
|---|---|
| `ID` | identity PK |
| `CREATED_AT` | `UtcDateTime`, not null, default now |
| `TOOL` | `VARCHAR2(40)`, not null |
| `SOURCE` | `VARCHAR2(100)`, null |
| `TARGET_LABEL` | `VARCHAR2(200)`, null. A REST path without its query string, or `sql:<12-char hash>`. |
| `TARGET_HASH` | `VARCHAR2(64)`, null |
| `ROW_COUNT` | `NUMBER`, null |
| `DURATION_MS` | `NUMBER`, not null |
| `OUTCOME` | `VARCHAR2(10)` (`McpCallOutcome`) |
| `ERROR_CODE` | `VARCHAR2(40)`, null |
| `PRINCIPAL_ID` | `VARCHAR2(200)`, null |
| `PRINCIPAL_KIND` | `VARCHAR2(10)` (`USER`/`SYSTEM`) |

The table has one index, `IX_MCP_CALL_LOG_AT (CREATED_AT)`. No SQL text, body or params are stored.

Migration: `api/alembic/versions/s48_mcp_call_log.py`, revision `s48_mcp_call_log`. Following split.md's merge order (chat-agent-tool-registry, db-stored-settings, engine-control-api, **fusion-mcp-transport**), `down_revision` is the engine-control-api revision, and the merger re-points it so there is a single head. It also seeds the `mcp.*` key defaults through the ConfigService seeding path that db-stored-settings defines. DEV ATP only; never run during the plan.

Retention: `McpCallLogRepository.purge_before` is called by the existing retention service with the history-payload retention cutoff (`services/retention`), so no new key is needed.

## 5 Config

These DB config keys are owned here, in an append-only block in `domain/config_keys.py`, group `fusion-sql-mcp`. None is `restart_required`, because the client reconnects when they change.

| Key | Type | Default | Notes |
|---|---|---|---|
| `mcp.server_url` | https URL str | `""` (unset means unhealthy, with the error "not configured") | |
| `mcp.token_url` | https URL str | `""` | |
| `mcp.client_id` | str | `""` | |
| `mcp.client_secret_ref` | SecretRef | (none) | `secret_ref=True`, a Vault OCID |
| `mcp.scope` | str | `"greenlight/mcp"` | |
| `mcp.fusion_source` | str | `""` | |
| `mcp.timeout_seconds` | int | 60 | 1 to 600 |
| `mcp.max_rows` | int | 2000 | 1 to 50000. The chat query cap and the `run_query` page size. |

This story also reads these keys:
- `fusion.pods`: the pod's `base_url`, `username` and `password_ref` (SOAP), `is_production`, and the new `mcp_source`.
- `fusion.default_pod` and `fusion.write_enabled`.

Env: none new. `env` (bootstrap) decides "release-approved" (`prod`). There are no Fusion REST credentials anywhere.

## 6 Risks and gates

- **Pinned dependencies.** The `mcp` 2.3 client API is `mcp.client.streamable_http.streamable_http_client(url, http_client=httpx2.AsyncClient(...))` plus `ClientSession`, as read from the server's venv on 2026-10-23. The coder confirms it against the installed SDK. The `RuntimeSettings.get` sync/async shape and the `ToolContext.services` resolution follow the dep plans exactly.
- **Money precision.** The server parses Fusion JSON with floats. Two-decimal amounts survive a shortest-repr round trip, and the client parses the result text with `Decimal`. A contract test covers values such as `0.1` and `1234567.89`.
- **REST action calls.** These need the content type `application/vnd.oracle.adf.action+json` (for example the testdata `completeTransaction`), and `fusion_rest_write` may send plain JSON. Record this as an UNVERIFIED row in CONTRACTS.md and as a cross-repo follow-up.
- **Binary downloads.** `get_raw` has no MCP equivalent. Only SOAP `?WSDL` is served, by `SoapTransport`. Any other path raises `FUSION_FAULT` "not available over MCP" (story assumption).
- **SQL execution.** `run_query` takes no bind parameters, so rendering is literal substitution with per-bind patterns. The guard refuses everything except one SELECT/WITH. Leading SQL comments are stripped because the server's statement check may reject them.
- **Throughput.** One page per call means more round trips. The page size is capped by the server's `fusion_rest_max_rows`, and paging stops at `max_pages`.
- **Coder gates:** lint and type-check only (`cd api && uv run ruff check . && uv run ruff format --check . && uv run pyright`). If `openapi.json` changes: `cd web && npx eslint . && npx next typegen && npx tsc --noEmit`.

## 7 Interfaces provided

**settings-screen-redesign** and **engine-control-panel-ui** (plannable: true):

```
GET /integrations/mcp/status      (CONFIG_READ)  -> 200 McpStatusOut
McpStatusOut {
  healthy: bool, latency_ms: int | null, server_url: str, client_id: str, source: str,
  secret_in_vault: true, error: str | null,            # error is additive (null when healthy)
  last_call: McpLastCallOut | null
}
McpLastCallOut { at: datetime (UTC ISO), tool: str, rows: int | null, duration_ms: int }

POST /integrations/mcp/test       (CONFIG_WRITE, no body) -> 200 McpTestOut
McpTestOut { token_valid: bool, tools_count: int, probe_tool: "fusion_rest_get",
             probe_ms: int | null, error: str | null }
```

Errors use the single API error shape: 401/403 from auth. The test endpoint never returns 5xx for a server failure; it reports it in `error`. The pill copy maps "Healthy · {latency_ms} ms" to `healthy`, and "Unreachable" (Settings) or "MCP unreachable" (Engine) to `!healthy`.

**matching-lab-replay-api** (plannable: true): it gets the unchanged `FusionClient` Protocol (`integrations/fusion/client.py`), built by `FusionClientFactory.for_pod(name: str | None = None) -> FusionClient`. The read methods it uses keep their exact current signatures:
- `find_receipts(*, customer_numbers: Sequence[str], date_from: date, date_to: date, by: ReceiptDateBasis = "receipt_date") -> list[FusionReceipt]`
- `get_receipt(receipt_id: int) -> FusionReceipt`
- `find_transactions(numbers: Sequence[str]) -> list[FusionTransaction]`

For its spy it should use `FakeFusionClient` (unchanged) or `McpFusionClient(FakeMcpClient)`. Writes on either are the `WRITE_METHODS` set.

**assistant-chat-redesign** (display only, plannable: true): the tool names are `fusion.query`, `fusion.rest_get`, `fusion.rest_describe` and `fusion.list_sources`, in group `FUSION_READS`, `mutating=False`, `confirm_required=False`, permission `REPORTS_READ`.
- Inputs:
  - `FusionQueryIn{sql: str, max_rows: int | None}`
  - `FusionRestGetIn{path: str, params: dict[str, str] | None}`
  - `FusionRestDescribeIn{path: str}`
  - `FusionListSourcesIn{}`
- Outputs:
  - `FusionQueryOut{columns, rows, truncated, total_rows}` (rendered as a `table_card`)
  - `FusionRestOut{status, body, has_more}`
  - `FusionSourcesOut{sources: [{name, kind, environment}]}`

## Assumptions

- **Migration.** split.md lists no migration for this story. The call log needs persistence that is shared across the API and worker processes ("Last call" must show worker calls), so this story adds one revision, `s48_mcp_call_log`, placed in merge order after engine-control-api.
- **`mcp.scope`.** This key is added beyond the story's list, with default `greenlight/mcp`, so a second identity domain needs no code change.
- **Required tools.** `REQUIRED_TOOLS` contains the six tools the client calls: `list_sources`, `run_query`, `fetch_rows`, `fusion_rest_get`, `fusion_rest_describe`, `fusion_rest_write`. AC9's "seven tools" is read as these six plus `describe_table`, which the live probe also checks but health does not require.
- **Source resolution.** `fusion.pods[pod].mcp_source` wins. `mcp.fusion_source` is the fallback, and also the source used by chat tools and the health probe.
- **Chat tool permission.** All four chat tools use `REPORTS_READ`; the story names it only for `fusion.query`.
- **Data models.** `run_report` keeps its `bytes` XML contract by rendering `DATA_DS/G_1` from the `run_query` rows. That avoids changing three callers' parsers. The SQL files move into the package (`git mv`, one copy).
- **Evidence defect.** The bind and column mismatch in `evidence.py` is fixed here because it lies on the moved path.
- **Status cache.** `GET /integrations/mcp/status` caches the live health check for 15 s per process, to avoid a server call on every page render.
