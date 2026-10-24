# engine-control-panel-ui: The Engine control panel screen

- Issue: #48 (addition: engine control panel, scope item 1)
- breaking: false
- Design screen owned: **Engine** (`design/project/glass/Engine.dc.html`, design.md §3.3)

## Story

As an admin, I want an Engine screen showing every station's lag, throughput, in-flight and dead letters with Pause, Resume, Drain, Throttle and Replay controls that ask for a reason, so that I can manage the processor from the UI; as an operator I want the same view read-only.

## Context

design.md §3.3. API from engine-control-api; the MCP health pill from fusion-mcp-transport. Built only from glass-theme-shell's shared components (`ConfirmDialog`, `Pill`, `Meter`, `GlassPanel`, `DataTable`, `StateCard`). New files: `web/app/(shell)/engine/page.tsx`, `web/components/engine/{station-card,throttle-panel,audit-list,dlq-table}.tsx`, thin Next proxy route handlers for the mutations. Next 16 APIs: read `web/node_modules/next/dist/docs` before coding (research.md dissent).

## Acceptance criteria

1. [browser] Engine board: `/engine` top bar shows "Engine", env, Live, "Lag streamed · updated N s ago", `Admin only · audited` (locked pill), "Fusion reads · MCP healthy N ms" (ok pill; err pill "MCP unreachable" from `GET /integrations/mcp/status`), and "OCI Streaming · group <consumer_group>".
2. [browser] Engine board: Stations card with header pills "N running · N paused · N draining" and a grid of 12 station cards (mono name, state pill, `lag N · N/min · dlq N`, 5px in-flight meter turning warn when saturated, "in-flight N / M", Pause or Resume (warn style) and Drain buttons); a paused card has the warn border. Values update live over `/engine/stream` without a reload.
3. [browser] Engine board: Pause (and Drain, Throttle save, Replay) opens `ConfirmDialog` with the station named, the "in-flight finish, nothing is lost" body, a required Reason, the line "Recorded as <name · role> · <date> UTC · expected version N", Cancel and a warn-filled confirm; on confirm the station shows PAUSED and the Audit card gains the row (who · when · why).
4. [browser] Engine board: Throttle card (config vN) with range sliders `concurrency.per_stage` 1-32 and `concurrency.apply_per_receipt` 1-8 with the "Fusion applies take about 6 s a line; this is the back-pressure." helper, and "Save throttle…" through the confirm dialog.
5. [browser] Engine board: Dead-letter queue table (checkbox, event id, stage, item link to `/items/[id]`, err-tone error pill, attempts, dead since), header pill "N events" and primary "Replay N selected…"; the result lists replayed and skipped events with reasons.
6. [browser] Engine board states: loading (card skeletons "Reading consumer lag…"), empty DLQ ("No dead letters", "Every event is inside its retry budget."), error ("Bus health unavailable", controls disabled, Retry), and operator view (all controls visible but disabled, labelled "needs admin").
7. [browser] A 409 version conflict keeps the dialog open with the reason kept and says "Someone changed the engine first; review and try again."
8. [unit] The Engine nav entry is visible to roles holding REPORTS_READ; controls render enabled only with ENGINE_CONTROL (UI hides, API enforces).

## Out of scope

- The status footer (glass-theme-shell). Engine chat tools (engine-control-api).

## Deps

- glass-theme-shell: `ConfirmDialog{title, body, confirmLabel, tone, expectedVersion, onConfirm({reason})}`, `Pill`, `Meter`, `GlassPanel`, `DataTable`, `StateCard`, `TopBar`. plannable: true.
- engine-control-api: `GET /engine/status`, `GET /engine/stream`, `POST /engine/stations/{station}/pause|resume|drain`, `PUT /engine/throttle`, `GET /engine/dead-letters`, `POST /engine/dead-letters/replay`, `GET /engine/audit` (shapes in its story). plannable: true.
- fusion-mcp-transport: `GET /integrations/mcp/status` -> `McpStatusOut{healthy, latency_ms, ...}`. plannable: true.
- live-progress-dashboard: `useEventStream` hook in `web/hooks/`. plannable: true.

## Assumptions

- The board's 1-32 / 1-8 slider bounds are the API's validation bounds.
