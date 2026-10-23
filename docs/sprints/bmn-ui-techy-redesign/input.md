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
