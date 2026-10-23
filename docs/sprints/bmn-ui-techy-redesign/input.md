# Story (GitHub issue #48, verbatim from Jonathan)

The UI for the cash app is lacking and kind of plain. It needs a techy feel to it. What this UI needs to do is show the user progress and manage exceptions to the process. It primarily needs to report on progress: receipts matched, money made, model efficiency. The matching algorithm is everything in this app, so we need ways to refine it. I like refining it through chat, so we need an assistant UI chat that looks like the aix-payroll-compare chat (local checkout: D:\AIX-Payroll-Compare). We need the capability in the UI to submit receipt images that failed for in-depth review, and other things, but this is enough for a start on a UI.

Issue: https://github.com/GreatFigure8/Fusion-CashApp-AI/issues/48

Acceptance criteria (from the issue):
- Redesigned dark, techy visual theme applied through shared components, no per-page duplicates.
- Progress dashboard: receipts matched, money applied (by currency), model efficiency (per-model accuracy, cost, adjudicator agreement, auto-fix rate) (inferred).
- Exception workbench restyled to match; exceptions only, applied items hidden by default (inferred).
- One shared assistant chat component styled like the aix-payroll-compare chat, configured by props (context, system prompt key, actions), usable for refining matching rules.
- Upload one or more failed receipt images and submit for in-depth review; appears as a work item with artifact stored and a review result visible in the UI.

Repo rules: see CLAUDE.md (python API owns data/logic; web/ is a thin Next.js client; shared components once; Haiku is the chat workhorse; zero data retention).
Local rule: `dev` is protected in this repo. Never push dev. Land work on dev by pull request (`gh pr create --base dev`, merged with `gh pr merge --merge`).

## Addition from Jonathan (mid-run, during RESEARCH)

"oh one other thing we need to take into consideration... we need a control panel for the processing engine. a way to control the flow of the data through the engine (Kafka)."

Treated as part of this story: an engine control panel in the UI (admin/operator permission, enforced in the API, audited with the Principal) to control flow through the stations and the bus behind the `EventBus` interface: per-station pause/resume, drain, consumer lag and throughput per topic, concurrency/throttle (Fusion apply back-pressure), retry and dead-letter queues with replay/requeue. No scheduler, and no third poller (CLAUDE.md non-negotiables 4 and 5): this controls event flow, it does not add polling.

## Scope summary from Jonathan (mid-run, during DESIGN)

"so in short, what we need are 1. control panel to monitor and manage the processor 2. the lab in 48 3. all settings other than database connection information stored in the database like we always do. 4. real-time reporting on progress and status 5. exportable html reports on progress to users"

Interpretation recorded as an assumption: "the lab" = the matching test console (issue #49: refine matching through chat, replay changed matching read-only against real past data, show before/after, promote only by permission-checked audited action). It is folded into this run (#48) instead of waiting. #49 stays open as a pointer until this run ships it.
Plus: (3) every setting except database connection info lives in the database (config service, admin-editable in the UI); no new env/file settings. (4) real-time reporting on progress and status via SSE. (5) exportable, self-contained HTML progress reports for users.

## Item 6 from Jonathan (the main one)

"and 6.  and this is the main one, we need a chat process that can do all of the above through chat as well as have a conversation with the user about optimization of processing."

Meaning: the one shared assistant chat is an agent, not just Q&A. Through chat a user can do everything above: monitor and control the engine (pause/resume/drain/throttle/DLQ replay), run the matching lab, change settings, view live progress and generate/export HTML reports, submit failed receipt images, work exceptions. It also holds an open conversation about optimizing processing (reading the stored metrics, suggesting changes, testing them in the lab). Constraints that stay: Haiku is the chat workhorse (CLAUDE.md), structured outputs, zero retention; every chat action is a tool call executed by the same services the UI uses, with the user's Principal (same permission checks and audit trail, no separate path); mutating actions show a confirm card (who/what/before-after) and are executed only on the user's confirmation; the chat can never exceed the user's own permissions.

## Item 7 from Jonathan

"and 7.  We need to be able to connect to the fusion-sql-mcp server"

Context found (D:\fusion-sql-mcp, repo GreatFigure8/fusion-sql-mcp, "AIX Greenlight MCP"): a shared MCP server (Python, :8000 /mcp, JWT/OAuth, one OAuth client per app) giving read access to Oracle/ADB, SQL Server, MySQL sources and Oracle Fusion pods (BI Publisher SQL, REST describe/get/write).
Interpretation recorded as an assumption: the cash app API gets an `McpClient`-style integration behind an interface (like FusionClient/LlmClient) that connects to that server as its own OAuth client; the server URL is a DB setting, the client id/secret come from OCI Vault (never in the DB or env); the chat agent gets read-only tools over it (explore sources, run read-only queries, Fusion REST describe/get) to investigate data while optimizing processing and to feed the lab with real data; connection status/health is visible in the engine/settings screens. Fusion writes (apply receipt) stay on the direct FusionClient: non-negotiable 9 is unchanged. Tool calls through it are audited with the user's Principal.

## Item 7, clarified by Jonathan

"that's where we will connect to fusion to search for receipts and invoices"

Correction to the earlier reading: the fusion-sql-mcp server is not just a chat convenience. It is the app's read path to Fusion: receipt search (matching, the receipt watcher), invoice and credit memo lookups, and the lab's real-data replay all go through it. Design consequence: the single `FusionClient` interface stays the only thing stages call; its read methods get an MCP-backed implementation (fusion_rest_get / run_query on the server) and the chat tools use the same read methods (no second path). Receipt apply (SOAP createApplyReceipt) and other writes are NOT assumed to be available through the MCP: they stay on the direct implementation unless the server proves it can do them; the planner must verify the server's tool list (D:\fusion-sql-mcp, backend) before pinning the interface. CLAUDE.md's "Fusion integration" section is refined in this run to say reads go through the Greenlight MCP (record the refinement there). Auth: own OAuth client, secret in OCI Vault; URL and non-secret settings in the DB.

## Item 7, decision by Jonathan (supersedes the 'writes stay direct' part above)

"I like the idea of the fusion traffic being direct but the mcp server also provides value because  there's no thinking about connectivity...it just works.  so we're going to go through the MCP server for fusion connectivity"

Decision: ALL Fusion connectivity goes through the fusion-sql-mcp server, reads and writes. This revises CLAUDE.md non-negotiable 9 and the "Fusion integration" section (direct REST/SOAP/BIP): the single FusionClient interface stays, but its transport is the MCP server (fusion_rest_get / fusion_rest_describe / fusion_rest_write / run_query, HDL tools where useful). Connectivity, auth to Fusion and pod selection belong to the server, so the app carries no Fusion credentials; it only holds its own OAuth client for the server (secret in OCI Vault, URL and non-secret settings in the DB). Never OIC remains. The "never apply receipts in a production pod outside a release-approved configured environment" rule stays in force and is enforced by the app's config plus the server's own access control.
Known gap to resolve in planning: the server's tools (checked 2026-10-23) are fusion_rest_get/describe/write, fusion_hdl_submit/status and run_query; no SOAP tool was found, and receipt apply has no REST equivalent (SOAP createApplyReceipt, reference doc section 3). Planner must confirm against the server code whether a SOAP/apply path exists; if not, a story adds an apply tool to the server (separate repo, GreatFigure8/fusion-sql-mcp: cross-repo work is reported, not assumed done here) and until it exists apply is gated off by config. CLAUDE.md is updated in this run to record the refinement.
