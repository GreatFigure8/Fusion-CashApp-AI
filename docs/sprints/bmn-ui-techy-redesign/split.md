# Split: bmn-ui-techy-redesign

14 stories. Walking skeleton not needed (repo exists). Every design board is owned by exactly one story.

## Screen ownership

| Board (`design/project/glass/`) | Owner story |
|---|---|
| Shell | glass-theme-shell |
| Dashboard | live-progress-dashboard |
| Engine | engine-control-panel-ui |
| Exceptions | exceptions-workbench-restyle (also restyles Flow and Items, no board) |
| Chat (Assistant, incl. the dock) | assistant-chat-redesign |
| Upload (Review) | failed-receipt-review |
| Lab | matching-lab-ui |
| Reports | html-progress-reports |
| Settings | settings-screen-redesign |

## Dependency graph (all interfaces plannable: every story can plan and build in wave 1)

- chat-agent-tool-registry: none
- db-stored-settings: none
- engine-control-api: chat-agent-tool-registry
- fusion-mcp-transport: db-stored-settings, chat-agent-tool-registry
- glass-theme-shell: engine-control-api
- live-progress-dashboard: glass-theme-shell, chat-agent-tool-registry
- exceptions-workbench-restyle: glass-theme-shell
- engine-control-panel-ui: glass-theme-shell, engine-control-api, fusion-mcp-transport, live-progress-dashboard
- settings-screen-redesign: glass-theme-shell, db-stored-settings, fusion-mcp-transport
- failed-receipt-review: glass-theme-shell, chat-agent-tool-registry, db-stored-settings, live-progress-dashboard
- html-progress-reports: live-progress-dashboard, glass-theme-shell, chat-agent-tool-registry
- assistant-chat-redesign: glass-theme-shell, chat-agent-tool-registry, failed-receipt-review, live-progress-dashboard, engine-control-api
- matching-lab-replay-api: chat-agent-tool-registry, fusion-mcp-transport, db-stored-settings
- matching-lab-ui: glass-theme-shell, assistant-chat-redesign, matching-lab-replay-api, live-progress-dashboard

Suggested merge order (owners first): chat-agent-tool-registry, db-stored-settings, engine-control-api, fusion-mcp-transport, glass-theme-shell, live-progress-dashboard, then the rest; matching-lab-ui last.

## Shared owners (lessons L-pre-payroll-quality-checks-1, L-employee-level-fixes-1)

One owner per shared thing; everyone else imports it and never creates a placeholder at the owner's path. Dependents merge the owner's pushed wip branch.

| Shared thing | Path | Owner |
|---|---|---|
| Tokens, `.bg-blueprint`, `@theme inline` | `web/app/globals.css` | glass-theme-shell |
| `GlassPanel`, `Pill`, `MonoLabel`, `Meter`, `Segmented`, `FilterChip`, `SuggestionChip`, `ConfirmDialog`, `DiffBlock`, `SkeletonRows`, `StateCard`; `KpiCard`/`status-badge`/`data-table` extensions; `Button` warn variant; `TopBar`, `NavRail`, `StatusFooter` | `web/components/common/*`, `web/components/shell/*` | glass-theme-shell |
| `nav.ts` entries and count-source API | `web/components/shell/nav.ts` | glass-theme-shell (failed-receipt-review and matching-lab-ui only wire their count source) |
| `DropZone` | `web/components/common/drop-zone.tsx` | failed-receipt-review |
| `useEventStream` (every SSE consumer) | `web/hooks/use-event-stream.ts` | live-progress-dashboard |
| Chat parts, `AssistantDock`, mounting in `(shell)/layout.tsx` | `web/components/common/llm-chat/*` | assistant-chat-redesign |
| `ToolRegistry`, `ToolSpec`, `ToolContext`, `ConfirmPreview`, result-card schemas, `TOOLS` discovery | `api/src/cashapp/services/chat/tools/registry.py`, `api/src/cashapp/api/schemas/chat.py` | chat-agent-tool-registry |
| Tool modules | `services/chat/tools/{metrics,engine,fusion_reads,review,reports,lab}.py` | the story named in each file's story |
| `MetricsService` (every progress aggregate) | `api/src/cashapp/services/metrics/service.py` | live-progress-dashboard |
| `RuntimeSettings`, `ConfigKey.restart_required/secret_ref` | `api/src/cashapp/services/runtime_settings.py`, `domain/config_keys.py` | db-stored-settings |
| Feature config keys | `domain/config_keys.py` (append-only blocks) | chat.* registry, mcp.* fusion-mcp-transport, engine.* engine-control-api, uploads.*/review.* failed-receipt-review, lab.* matching-lab-replay-api |
| `Permission` members | `domain/principal.py` (append-only) | ENGINE_CONTROL engine-control-api, LAB_RUN matching-lab-replay-api |
| `McpClient`, `McpFusionClient` | `api/src/cashapp/integrations/mcp/*`, `integrations/fusion/*` | fusion-mcp-transport |
| CLAUDE.md refinements | `CLAUDE.md` | fusion-mcp-transport (non-negotiable 9, Fusion integration); db-stored-settings (settings line) |

## Migrations

Stories with an Alembic revision: chat-agent-tool-registry, db-stored-settings, engine-control-api, html-progress-reports, matching-lab-replay-api. Each writes one revision; the merger re-points `down_revision` in merge order so `alembic heads` stays one (prior run fallout: linear chain). DEV ATP only.

## Breaking

- chat-agent-tool-registry: `/chat/stream` event set replaced (web client moves in assistant-chat-redesign in the same run).
- db-stored-settings: `CASHAPP_*` env contract reduced to the bootstrap set.
- fusion-mcp-transport: Fusion transport/config contract (REST/BIP via MCP; SOAP direct).

## Assumptions

- Flow and Items have no board; they are restyled by exceptions-workbench-restyle (shared tile/timeline components).
- "Replays never call Fusion" on the Lab board is read as "never write to Fusion" (Item 7: replays read through MCP).
- Cross-repo follow-ups for GreatFigure8/fusion-sql-mcp (not stories here): register the cash app OAuth client and source group; a binary GET tool if `get_raw` is still needed; confirm the REST write allowlist covers receipt comment/attachment paths.
