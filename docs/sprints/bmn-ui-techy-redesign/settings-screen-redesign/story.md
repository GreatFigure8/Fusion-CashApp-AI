# settings-screen-redesign: Settings screen with group nav, audited saves and the fusion-sql-mcp connection card

- Issue: #48 (scope items 3 and 7)
- breaking: false
- Design screen owned: **Settings** (`design/project/glass/Settings.dc.html`, design.md §3.9)

## Story

As an admin, I want one Settings screen where every database-stored setting is grouped, searchable, edited with a reviewed diff and a reason, and where I can see and test the fusion-sql-mcp connection, so that I can tune the system and its Fusion connectivity without a deploy.

## Context

design.md §3.9. Existing: `web/app/(shell)/config/page.tsx`, `components/config/{config-tabs,setting-row,settings-panel,save-footer,review-dialog,history-list,history-sheet,access-panel,config-staging-provider,staging}.tsx` and `editors/*` (kept and restyled; `config-tabs` becomes the group nav). New: `components/config/mcp-connection-card.tsx`. Write path stays `PUT /config/{key}` (CONFIG_WRITE, reason, expected_version).

## Acceptance criteria

1. [browser] Settings board: `/config` top bar "Settings", env, pill "Stored in the database · vN", key search field.
2. [browser] Settings board: left glass group nav from `GET /config/groups` with counts (Matching, Pollers, Concurrency, Models, Extraction, Auto-fix, Aging, Uploads, Access, fusion-sql-mcp, plus every group db-stored-settings adds) and the note "Only the database connection lives outside the database, in Vault. Every other setting is here, versioned and audited."
3. [browser] Settings board: group card with header pill "N unsaved change(s)"; rows show mono key and help text, value editor (dirty = accent border), last-changed ("<date> · <name>" / "seed" / "unsaved"), a "restart required" muted pill for `restart_required` keys and a "Vault secret" locked pill for `secret_ref` keys (OCID shown, value never); footer diff summary (`key old → new`), required reason, Revert, primary "Save as vN+1".
4. [browser] Settings board: fusion-sql-mcp connection card: header "Connection" + "fusion-sql-mcp · Fusion reads", health pill ("Healthy · N ms" ok / "Unreachable" err) from `GET /integrations/mcp/status`; `mcp.server_url` input (saved through the same audited write), facts row (OAuth client id, "Secret in OCI Vault", source, "Last call HH:MM:SS · tool · N rows"), the explanatory text (reads and REST writes go through the server; applying receipts stays on the direct SOAP call), and "Test connection" (`POST /integrations/mcp/test`) with the result line "Token valid · N tools · <tool> N ms" or the error.
5. [browser] Settings board: Access card (groups to roles table with "Can" text, "Map a group") and Change history (version, when · who, key old → new, quoted reason) restyled; existing behaviour unchanged.
6. [browser] Settings board states: loading, empty search with a did-you-mean suggestion ("No setting matches 'tolerence'. Did you mean tolerance?"), conflict ("Someone saved vN first. Your edit is kept.", Review the difference), invalid ("<key> must be <range> … Nothing was saved.").
7. [browser] A viewer or operator sees every value read-only with "needs config write" on the save controls; secret refs are never editable as plain text.
8. [unit] The did-you-mean search is a small pure function over key names (edit distance) with tests; no per-page CSS.

## Out of scope

- Moving settings into the DB (db-stored-settings). The MCP client (fusion-mcp-transport).

## Deps

- glass-theme-shell: `GlassPanel`, `Pill`, `DiffBlock`, `StateCard`, `TopBar`, `ConfirmDialog`. plannable: true.
- db-stored-settings: `GET /config` entry fields `group, restart_required, secret_ref, last_changed_at, last_changed_by`; `GET /config/groups` -> `[{group, label, count, description}]`. plannable: true.
- fusion-mcp-transport: `GET /integrations/mcp/status` -> `McpStatusOut{healthy, latency_ms, server_url, client_id, source, secret_in_vault, last_call}`; `POST /integrations/mcp/test` -> `McpTestOut{token_valid, tools_count, probe_tool, probe_ms, error?}`. plannable: true.

## Assumptions

- Group labels and order come from the API (`GET /config/groups`), not a web-side list.
