# fusion-mcp-transport: Fusion reads and REST writes through the fusion-sql-mcp server; SOAP apply stays direct

- Issue: #48 (item 7, final decision)
- breaking: true (Fusion deploy/config contract: REST/BIP no longer use pod basic-auth from config; the app needs an MCP OAuth client; CLAUDE.md non-negotiable 9 is refined)
- Design screen owned: none (the connection card on Settings is owned by settings-screen-redesign)

## Story

As the cash app, I want every Fusion read (receipt search, the receipt watcher, invoice and credit memo lookups, lab replays, the assistant's queries) and every Fusion REST write to go through the fusion-sql-mcp (Greenlight) server, with only the SOAP receipt apply called directly, so that Fusion connectivity "just works" and the app carries no Fusion REST credentials.

## Context

input.md Item 7 final decision. Server verified in `D:\fusion-sql-mcp\backend\src\fusion_sql_mcp` (2026-10-23): tools `list_sources`, `list_databases`, `list_schemas`, `list_tables`, `describe_table`, `run_query(source, sql, max_rows, account, keep_result, slices)` + `fetch_rows(result_id, offset, max_rows)` (server.py:735,797), `fusion_rest_get(source, path, params, account)`, `fusion_rest_describe(source, path, account)`, `fusion_rest_write(source, method POST|PATCH|DELETE, path, body, account)` (fusion/rest_tools.py:275-318), `fusion_hdl_submit/status`. Auth: OAuth `client_credentials` JWT, scope `greenlight/mcp` (oauth.py:4-8, README "OAuth"). There is **no SOAP tool and no BIP `runReport` of a catalog report**: only ad-hoc SQL through BIP. Today's client: `integrations/fusion/{client.py (FusionClient Protocol :48, HttpFusionClient :259), transport.py, soap.py, bip.py, factory.py, CONTRACTS.md}`.

## Acceptance criteria

1. [unit] `cashapp/integrations/mcp/`: `McpClient` Protocol (`list_tools()`, `call_tool(name, args) -> dict`, `health() -> McpHealth{ok, latency_ms, tools: list[str], token_valid, error}`) with `StreamableHttpMcpClient` (official `mcp` Python SDK, streamable HTTP to `mcp.server_url`), token from `client_credentials` against `mcp.token_url` with `mcp.client_id` and the secret from `mcp.client_secret_ref` (Vault `SecretRef`, never DB plaintext or env), token cached until expiry, retries with backoff on transport errors and 5xx, a typed error mapping into `FUSION_TRANSIENT` / `FUSION_FAULT`, and a `FakeMcpClient` for tests.
2. [unit] New DB config keys owned here: `mcp.server_url`, `mcp.token_url`, `mcp.client_id`, `mcp.client_secret_ref` (secret_ref), `mcp.fusion_source` (the server's Fusion source label for the pod, e.g. `fusion dev-1`), `mcp.timeout_seconds`, `mcp.max_rows`; `fusion.pods` maps each pod to its MCP source label.
3. [unit] `FusionClient` stays the only interface stages call. A new `McpFusionClient` composes: reads (`find_transactions`, `find_receipts`, `receipts_created_since`, `get_receipt`, `list_receipt_applications`, `list_transaction_applications`, `get_customer_account`, `get_payment_terms`, `list_receipt_attachments`, `rest_get`) via `fusion_rest_get` with the same paths, `fields=`, `onlyData`, `q=` escaping and `has_more`/`offset` paging (one server call is one page; `limit` is capped by the server's `fusion_rest_max_rows`). The `REST-Framework-Version` header is sent by the server (`fusion_rest_framework_version`, default "4", fusion-sql-mcp models.py:257, rest.py:221); a startup/health check fails loudly if a probe `in (...)` query returns 400; `customer_relationships` and `run_report` via `run_query` with the existing data-model SQL (`relationships.sql`, `receipt_signals.sql`) using `keep_result` + `fetch_rows` for large results; REST writes (`set_receipt_comment` PATCH, `attach_to_receipt` POST, `rest_post`) via `fusion_rest_write`; and `apply_receipt` / `unapply_receipt` on the **existing direct SOAP path** (`soap.py`) with credentials from the pod's Vault ref. Same return models, same error codes; existing contract tests run against both implementations.
4. [unit] `FusionClientFactory.for_pod()` returns the MCP-backed client; the direct REST/BIP code paths are deleted (no second read path), the SOAP transport is kept. A static test asserts no REST or BIP HTTP call to a Fusion host remains outside `soap.py`.
5. [unit] The production-pod rule stays: `apply_receipt` and every `fusion_rest_write` refuse unless `fusion.write_enabled` is true and the pod is not `is_production` outside a release-approved environment (existing `guard.py`); a test covers each refusal.
6. [unit] Every MCP tool call is recorded (tool, source, path or SQL hash, rows, duration, outcome, Principal or system principal) for the "Last call" fact on Settings and for audit; SQL text and payloads are never logged in full outside the DB.
7. [api] `GET /integrations/mcp/status` (CONFIG_READ) -> `McpStatusOut{healthy, latency_ms, server_url, client_id, source, secret_in_vault: true, last_call: {at, tool, rows, duration_ms} | null}`; `POST /integrations/mcp/test` (CONFIG_WRITE) runs token + `list_tools` + one `fusion_rest_get` and returns `McpTestOut{token_valid, tools_count, probe_tool, probe_ms, error?}`. New auto-discovered router.
8. [unit] Chat tools registered in `cashapp/services/chat/tools/fusion_reads.py` (group FUSION_READS, all read-only, no confirm): `fusion.query` (read-only SELECT/WITH through `run_query`, row cap from config, REPORTS_READ), `fusion.rest_get`, `fusion.rest_describe`, `fusion.list_sources`; a SQL guard refuses anything but one SELECT/WITH before calling the server.
9. [integration] `-m live` probes (skipped by default) against the DEV MCP server: list_tools contains the seven tools above; one `standardReceipts` page and one invoice lookup decode into the existing models. `CONTRACTS.md` gains a "Transport" column (MCP or SOAP) per row.
10. [unit] CLAUDE.md non-negotiable 9 and the "Fusion integration" section are refined to: Fusion reads and REST writes go through the fusion-sql-mcp (Greenlight) server behind `FusionClient`; the SOAP `createApplyReceipt` (and unapply) is the one direct call, from the API, credentials from Vault; never OIC. The refinement is recorded with the date.

## Out of scope

- Any change to the fusion-sql-mcp repo (follow-ups listed under Assumptions). The Settings connection card UI.

## Deps

- db-stored-settings: `ConfigKey` with `secret_ref` and `restart_required` flags; `RuntimeSettings.get(key)`; `fusion.pods` JSON key (pod -> base_url, is_production, password_ref). plannable: true.
- chat-agent-tool-registry: `ToolSpec`, `TOOLS: list[ToolSpec]` module discovery, `ToolContext`. plannable: true.

## Assumptions

- `unapply_receipt` is SOAP on the same service, so it stays direct with apply ("the receipt SOAP call").
- Binary downloads (`get_raw`) are not supported by `fusion_rest_get` (JSON only); `get_raw` callers are moved to JSON reads where possible, otherwise `get_raw` raises `FUSION_FAULT` "not available over MCP" and the follow-up below is filed.
- Cross-repo follow-ups (GreatFigure8/fusion-sql-mcp, not stories here): register a `cashapp-dev` OAuth client and source group; a binary GET tool if `get_raw` is still needed; confirm `fusion_rest_write` allowlist contains `standardReceipts` comment/attachment paths for the cash app's client.
