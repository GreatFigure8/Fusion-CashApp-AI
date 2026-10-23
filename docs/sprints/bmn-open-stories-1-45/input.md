# Input: execute all open stories (GitHub issues labelled bmn)

## #1 [story] Scaffold the monorepo: api (uv, FastAPI, async SQLAlchemy on ATP, Alembic), web (Next.js, Tailwind, shadcn), infra skeleton

### Goal

The repo has the three projects CLAUDE.md describes, wired so every later story has a home and BMN's code gates (lint + type-check) run clean.

### Acceptance criteria

- [ ] `api/` is a uv project (Python 3.12+) with a FastAPI app, an async SQLAlchemy engine for ATP via `python-oracledb`, and Alembic initialised. `ruff` and `pyright` pass.
- [ ] `web/` is Next.js App Router with TypeScript `strict` + `noUncheckedIndexedAccess`, Tailwind and shadcn initialised. `next typegen && tsc --noEmit` and `eslint .` pass.
- [ ] `infra/` holds a Terraform skeleton targeting `us-ashburn-1`. *(inferred)*
- [ ] CLAUDE.md's *Repository layout* and *Commands* sections are updated to the real paths and commands.

### Constraints and out of scope

No business logic and no deploys. Follows the layering in CLAUDE.md.

### Touches a screen a person looks at?

No


## #2 [story] Data layer foundation: generic repository, unit of work, work item/history/outbox tables, shared status enum

### Goal

The single data layer every station uses exists: a generic repository over SQLAlchemy, a unit of work that owns transactions, the core tables, and one status vocabulary.

### Acceptance criteria

- [ ] `BaseRepository[ModelT]` provides get, list (filtering and paging), add, update and delete. Repositories never commit; a unit of work owns the transaction.
- [ ] An Alembic migration creates the work item, work item history and outbox tables (stage, status, attempts, last error, lock fields). *(inferred)*
- [ ] One status module defines the payment statuses, line statuses, failure precedence and info flags from `docs/reference/prior-implementation-lessons.md` §5, and nothing else defines them.
- [ ] Money helpers: `Decimal` at 2 dp with `ROUND_HALF_UP`, and equality as `|a − b| ≤ 0.005`.

### Constraints and out of scope

No query is written outside a repository.

### Touches a screen a person looks at?

No


## #3 [story] Pipeline runtime: abstract StageRunner, EventBus on OCI Streaming, outbox relay, retry and DLQ, idempotent consumers

### Goal

Every station runs on one shared runtime: an event arrives, the item is claimed and processed, and the state change and next event are committed together.

### Acceptance criteria

- [ ] An abstract `StageRunner` consumes, claims the item, takes an idempotency guard, calls the stage service, persists result + transition + outbox event in one transaction, and hands failures to the auto-fix engine.
- [ ] `EventBus` interface with an OCI Streaming (Kafka-compatible, SASL_SSL) implementation. Offsets are committed only after persisting; one consumer group per environment.
- [ ] An outbox relay publishes committed events. Each stage has a retry path and a dead-letter path.
- [ ] A redelivered event is harmless: the consumer checks the item's stage and status before acting.
- [ ] Consumer lag and DLQ depth are exposed for the metrics in #29.

### Constraints and out of scope

The database is the system of record; the bus only carries 'item X is ready for stage Y'.

### Touches a screen a person looks at?

No


## #4 [story] Sign-in and authorization: OCI Identity Domains confidential app, token validation in the API, group-to-role mapping

### Goal

People sign in with OCI Identity Domains, and the API decides what each person may do from their OCI groups.

### Acceptance criteria

- [ ] Next.js is the confidential client (authorization code + PKCE). The session is an encrypted httpOnly cookie, the client secret comes from OCI Vault, and tokens never reach the browser.
- [ ] The Python API validates every access token against the identity domain's JWKS (issuer, audience, expiry).
- [ ] A database table maps OCI groups to app roles, and one shared dependency turns a token into a `Principal` (user, groups, roles) that services receive as an argument.
- [ ] A bootstrap admin group-to-role mapping is seeded, so the first admin can sign in and configure the rest.
- [ ] Pipeline workers act as a system principal and never borrow a user's token.

### Constraints and out of scope

Authorization is enforced in the API; the UI only hides what a user can't do.

### Touches a screen a person looks at?

No *(inferred)*


## #5 [story] FusionClient: REST, SOAP apply, BI Publisher, typed errors, Vault credentials

### Goal

All Fusion traffic goes through one client that encodes what worked in the previous build and maps every failure to a typed error code.

### Acceptance criteria

- [ ] REST calls send `REST-Framework-Version: 4`, `onlyData=true` and explicit `fields=`; follow `hasMore` pagination; escape every `q=` value. Invoice and credit-memo lookups are batched.
- [ ] SOAP `createApplyReceipt` is keyed on `ReceiptId` and `CustomerTrxId` with signed amounts and the accounting-date rule. Parsing fails closed, including faults inside HTTP 200 envelopes, and filters the known noise codes.
- [ ] BI Publisher `runReport` with Base64 decoding.
- [ ] Faults map to typed error codes (overapply, already applied, lock, GL date, transient). Credentials come from OCI Vault, and several pods (dev, test, prod) are selectable by configuration.
- [ ] Wraps the receipt attachment and unapply calls needed by #17 and #38, each confirmed on a non-production pod first.

### Constraints and out of scope

Never guess an endpoint, payload or field name; confirm against a non-production pod (the `aix-greenlight` MCP helps).

### Touches a screen a person looks at?

No


## #6 [story] Intake poller: mailbox and drop-folder sources, content-hash dedupe, Object Storage

### Goal

New remittance artifacts are picked up from the mailbox and the drop folder on a configurable interval and become work items, once each.

### Acceptance criteria

- [ ] A long-running async loop whose interval comes from the runtime configuration (#28).
- [ ] `MailboxSource` and `FolderSource` sit behind interfaces; the mailbox implementation follows the decision in #33.
- [ ] Each artifact is deduplicated on a content hash, stored untouched in OCI Object Storage, and becomes a work item through the outbox.
- [ ] Processed mail and files are marked so they're never read twice.

### Constraints and out of scope

This is one of exactly two allowed pollers; it only emits events.

### Touches a screen a person looks at?

No


## #7 [story] Classify station: Haiku decides whether an artifact is remittance advice

### Goal

Every artifact is triaged as remittance advice or not, cheaply, before any expensive extraction runs.

### Acceptance criteria

- [ ] Haiku 5.5 returns a structured decision (remittance or not, reason, confidence), under zero data retention.
- [ ] Non-remittances are archived with their reason, never dropped.
- [ ] A person can override the decision and push an item back into the line.
- [ ] Model ID and effort come from the runtime configuration.

### Constraints and out of scope

None stated.

### Touches a screen a person looks at?

No


## #8 [story] Extraction fan-out: Opus 5.5 and Cohere Command A Vision read the same artifact

### Goal

Two independent readers extract the same remittance using one shared schema, and both results are saved for the adjudicator.

### Acceptance criteria

- [ ] One Pydantic extraction schema covers: invoice numbers as strings (suffixes like `-1`), several dates, lines without amounts, ambiguous `$`, PO/SO/ERS references, bank fees, tariff lines, discounts claimed, and source location + confidence per field.
- [ ] Reader A: Claude Opus 5.5 through the Anthropic SDK with structured outputs; `refusal` stop reasons are handled.
- [ ] Reader B: Cohere Command A Vision through the OCI SDK with `servingType: DEDICATED` against the Ashburn cluster endpoint from configuration.
- [ ] Each reader's output is persisted separately with its prompt and schema version.

### Constraints and out of scope

Zero data retention on every Claude call; no Fable models.

### Touches a screen a person looks at?

No


## #9 [story] Adjudicate fan-in: Opus 5.5 chooses between the two readings per field

### Goal

A single trusted extraction comes out of the two readings, with every value traceable to the reader it came from.

### Acceptance criteria

- [ ] The fan-in waits for both readers with a configurable timeout.
- [ ] Opus 5.5, as a separate call, sees only the two outputs, never the artifact, and returns the final extraction, the source per field (A, B or both), the disagreements and a confidence score.
- [ ] If one reader failed or timed out, the decision is made on the one result and records which reader was missing. If both failed, the item gets `EXTRACTION_FAILED`.
- [ ] The adjudication is stored with both raw readings and its prompt/schema version.

### Constraints and out of scope

The adjudicator does nothing else.

### Touches a screen a person looks at?

No


## #10 [story] Validate station: code checks on the adjudicated extraction

### Goal

Obvious data problems are caught by code, not the LLM, before anything touches Fusion.

### Acceptance criteria

- [ ] Header amount vs sum of lines: a mismatch sets the `payment-header-line-mismatch` flag; it is not a failure.
- [ ] Invoice-number formats, dates and currencies are checked; zero-amount lines are rejected.
- [ ] An ambiguous currency (`$`) is deferred to customer resolution (#11), not failed here.
- [ ] Every failure produces a typed error code for the auto-fix engine.

### Constraints and out of scope

No LLM calls in this station.

### Touches a screen a person looks at?

No


## #11 [story] Customer resolution: payer aliases, anchor customer, pay-on-behalf relationships

### Goal

Each remittance is tied to the right Fusion customer account(s) before receipt matching.

### Acceptance criteria

- [ ] Learned payer aliases (#37) are consulted first.
- [ ] Otherwise the anchor customer is the `BillToCustomerNumber` of the first invoice found, querying both invoices and credit memos.
- [ ] Pay-on-behalf relationships come from the BIP report: one hop, both directions, deduplicated. They only widen the receipt search and are never a failure.
- [ ] A payer that maps to several accounts is never auto-assigned.
- [ ] An ambiguous `$` currency is resolved from the customer's account currency.

### Constraints and out of scope

None stated.

### Touches a screen a person looks at?

No


## #12 [story] Spike: receipt-signal study on a Fusion pod with real cash activity

### Goal

We know, from real data, which fields actually link a remittance to its receipt, so the scorer in #13 uses evidence instead of amount-only matching.

### Acceptance criteria

- [ ] Read-only analysis of real receipts: remittance references on receipts, bank statement lines (references, addenda, payer name), payer bank accounts, receipt comments.
- [ ] For each signal: how often it is present and how often it identifies the right receipt.
- [ ] A written proposal of the scorer's signals and starting weights for #13.

### Constraints and out of scope

Read-only. Blocked until Jonathan names the pod. No client or customer identifiers in the write-up.

### Touches a screen a person looks at?

No


## #13 [story] Receipt matching scorer: multi-signal candidates, reservation, ambiguity is an error

### Goal

Receipts are found by scoring every candidate on all available signals, not by taking the first receipt with the right amount.

### Acceptance criteria

- [ ] Candidates are scored on the signals from #12: amount within per-currency tolerance, date window, currency, customer, remittance and statement-line references, payer bank account, customer history.
- [ ] An exact reference or invoice-set match wins outright. More than one qualifying candidate is `RECEIPT_AMBIGUOUS`, never 'first wins'.
- [ ] The chosen receipt is reserved (`SELECT … FOR UPDATE SKIP LOCKED`) before apply, and matching uses the receipt's remaining unapplied amount so retries resume.
- [ ] Every candidate's signal scores are logged so human decisions can tune the weights later.

### Constraints and out of scope

Tolerances and the date window come from the runtime configuration.

### Touches a screen a person looks at?

No


## #14 [story] Fusion receipt watcher and re-matching of items awaiting a receipt

### Goal

Remittances that arrive before their bank receipt wait and are re-matched the moment the receipt appears, instead of a fixed hold.

### Acceptance criteria

- [ ] The second allowed poller: interval from configuration; queries `standardReceipts` created since a high-water mark stored in the database.
- [ ] One event per new receipt wakes the `AWAITING_RECEIPT` items it could match by customer, currency, amount and date window.
- [ ] Filters on receipt creation time, not receipt date.
- [ ] Items past the configured aging limit are escalated to a person.

### Constraints and out of scope

Restarts neither miss nor replay receipts.

### Touches a screen a person looks at?

No


## #15 [story] Line matching and apply in Fusion

### Goal

Each remittance line is applied to its invoice or credit memo safely: never over-applied, never applied twice, never lost mid-remittance.

### Acceptance criteria

- [ ] Credit memos are applied first, in a stable order; duplicate invoice lines are deduplicated; invoice currency and status are checked.
- [ ] Each amount is capped at `min(line amount, invoice balance, receipt remaining)`.
- [ ] Fusion's existing applications are checked before every apply.
- [ ] Each line's result is persisted as it happens, and the payment roll-up is derived strictly from line and header results.
- [ ] Respects item locks (#40) and the per-receipt Fusion concurrency cap (#30).

### Constraints and out of scope

Applies go through `FusionClient` (#5) only.

### Touches a screen a person looks at?

No


## #16 [story] Already-applied fast path: attach the remittance and close the item

### Goal

Remittances for invoices that are already fully paid are closed in seconds, without matching. About 60% of remittances in the previous build were this case.

### Acceptance criteria

- [ ] After invoice lookup, if every invoice is already closed, find the receipt(s) that closed them.
- [ ] Attach the remittance to that receipt and close the item with its own status.
- [ ] If the closing receipt can't be determined, fall through to the normal path.

### Constraints and out of scope

None stated.

### Touches a screen a person looks at?

No


## #17 [story] Write-back: receipt note and remittance attachment in Fusion

### Goal

People working in Fusion can see what the automation did and why, on the receipt itself.

### Acceptance criteria

- [ ] A receipt note summarises applied lines and failed lines with reasons, within the note field's size limit. *(inferred)*
- [ ] The original remittance is attached to the receipt.
- [ ] The attachment call is confirmed on a non-production pod before it's built.
- [ ] A write-back failure never undoes applications; it gets its own error code.

### Constraints and out of scope

None stated.

### Touches a screen a person looks at?

No


## #18 [story] Auto-fix engine: typed error codes, handlers, bounded attempts, escalation

### Goal

Stuck items are repaired automatically wherever possible, and only reach a person when the fixes run out.

### Acceptance criteria

- [ ] The error codes in CLAUDE.md's self-healing table exist, each with a registered handler.
- [ ] Every handler is bounded by a configurable attempt limit, and each attempt is recorded on the item's history with its reasoning (Haiku where reasoning is needed).
- [ ] Only transient failures are retried without new information.
- [ ] Escalation to a person follows configurable thresholds, and a human requeue goes back through the same runner.

### Constraints and out of scope

Always a person: prepayments, PO/SO/ERS-only references, dual-currency payers, anything ungrounded in the remittance.

### Touches a screen a person looks at?

No


## #19 [story] UI shell and flow monitor

### Goal

People can watch the assembly line live and drill from a stage down to a single item and its evidence.

### Acceptance criteria

- [ ] App shell with sign-in and navigation that respects roles.
- [ ] Live per-stage counts and throughput over an SSE endpoint provided by the API.
- [ ] Drill-down: stage → items → item history → the original artifact with each extracted field highlighted at its source → per-line Fusion outcome.
- [ ] Item lock state and backlog batch progress (#35) are visible.

### Constraints and out of scope

All data comes through the typed API client (#31).

### Touches a screen a person looks at?

Yes


## #20 [story] UI exception workbench: dequeue, fix, requeue

### Goal

A person can find, understand and fix a stuck item quickly, with automation kept out of the way while they do.

### Acceptance criteria

- [ ] Shows exceptions only by default; searchable by amount, payer, invoice, reference and date range.
- [ ] Dequeue locks the item (#40) and shows why it's stuck and which auto-fixes were tried.
- [ ] Edit the data and requeue it through the same stage runner; reverse an automated application (#38) for permitted roles.
- [ ] Shows the Fusion context Fusion's own screens make hard: invoice-to-customer link, customer location, original and remaining amounts, credit memo history.

### Constraints and out of scope

None stated.

### Touches a screen a person looks at?

Yes


## #21 [story] UI configuration screen

### Goal

Admins tune the line without a deploy, and every change is visible in history.

### Acceptance criteria

- [ ] Edit group-to-role mapping, poll intervals, date window, tolerances per currency, retry limits, aging, model IDs and effort, fan-in timeout, and retention periods (#45).
- [ ] Backed by the runtime configuration service (#28), with each setting's change history visible.
- [ ] Review and retire learned payer aliases (#37).

### Constraints and out of scope

Admin role only for writes.

### Touches a screen a person looks at?

Yes


## #22 [story] UI shared LLM chat component

### Goal

Every place a person talks to the LLM uses one component, configured by props.

### Acceptance criteria

- [ ] One component configured by props: context, system prompt key, available actions.
- [ ] Responses stream over SSE from the API; the model is Haiku 5.5.
- [ ] Used on the item view and the flow monitor. *(inferred)*
- [ ] No second chat implementation exists anywhere in `web/`.

### Constraints and out of scope

DRY rule in CLAUDE.md.

### Touches a screen a person looks at?

Yes


## #23 [story] Fusion test-data generator with realistic scenarios

### Goal

Repeatable Fusion test data exists for every hard case, so matching and apply can be tested without production data.

### Acceptance criteria

- [ ] Creates invoices (`POST receivablesInvoices` + `completeTransaction`), credit memos and unapplied receipts (`POST standardReceipts` with no application) on a non-production pod.
- [ ] Scenario presets: split payments, short pays, INR rounding, duplicate amounts, ambiguous receipts, credit memos.
- [ ] Generated data is tagged so it can be found and cleaned up. *(inferred)*
- [ ] Refuses to run against a production pod.

### Constraints and out of scope

The previous build's 1:1 generator couldn't exercise any of these cases.

### Touches a screen a person looks at?

No


## #24 [story] Eval set and harness for extraction, matching and auto-fix

### Goal

Model and rule changes are judged by measurement against real (anonymised) cases.

### Acceptance criteria

- [ ] Uses the anonymised fixtures from #43.
- [ ] Measures field accuracy per reader and after adjudication.
- [ ] Also evaluates the matcher and the auto-fix engine against the AR-labelled failure set.
- [ ] One command produces a report, including the run's cost.

### Constraints and out of scope

Every run that calls a model spends money; runs are deliberate, not automatic.

### Touches a screen a person looks at?

No


## #25 [story] OCI infrastructure in Ashburn

### Goal

All runtime infrastructure is defined as code in `us-ashburn-1`.

### Acceptance criteria

- [ ] Terraform for ATP with separate DEV and PROD schemas, OCI Streaming, Object Storage, Vault, and compute for api, workers and web.
- [ ] The Generative AI dedicated AI cluster and endpoint for Cohere Command A Vision.
- [ ] Private endpoints, and Object Storage encryption with customer-managed keys. *(inferred)*
- [ ] Plans only during runs; applying infrastructure happens only through the release (#44).

### Constraints and out of scope

Ashburn only; no other region or cloud.

### Touches a screen a person looks at?

No


## #26 [story] CI gates on GitHub Actions for api and web

### Goal

Every push and PR to `dev` runs the same lint and type-check gates BMN uses, so broken code can't merge.

### Acceptance criteria

- [ ] A workflow runs `ruff check`, `ruff format --check` and `pyright` in `api/` on PRs and pushes to `dev`.
- [ ] A workflow runs `next typegen && tsc --noEmit` and `eslint .` in `web/`.
- [ ] Each job runs only when its folder changes, and caches dependencies. *(inferred)*
- [ ] No workflow deploys anything or touches any database.

### Constraints and out of scope

Never deploys; BMN's stack-scout must see `dev_push_deploys: false`.

### Touches a screen a person looks at?

No


## #27 [story] Application settings and secrets wiring

### Goal

One typed settings object for `api/` and one for `web/`; values come from the environment locally and OCI Vault when deployed, so no secret is in code or `NEXT_PUBLIC_*`.

### Acceptance criteria

- [ ] `api/` has a `pydantic-settings` class covering ATP, Streaming, Object Storage, Anthropic, OCI GenAI, Identity Domain and Fusion, and fails fast on a missing value.
- [ ] A Vault-backed loader resolves secret OCIDs at startup when deployed.
- [ ] `web/` validates its env with Zod at boot; only public values use `NEXT_PUBLIC_*`.
- [ ] `.env.example` files list every setting with no real values.

### Constraints and out of scope

Follows `python-web-app:wiring-application-config`.

### Touches a screen a person looks at?

No


## #28 [story] Runtime configuration service (database-backed, versioned, audited)

### Goal

Every value CLAUDE.md calls configuration lives in ATP behind one typed service that every station reads, with a full change history.

### Acceptance criteria

- [ ] One config table and repository with typed accessors per setting group (intervals, date window, tolerances, retries, aging, models, fan-in timeout, group-to-role mapping, retention).
- [ ] Every change records who, when, and the old and new values.
- [ ] Stations and pollers pick up a change without a restart, within one poll or event. *(inferred)*
- [ ] An API (read for operators, write for admins) backs the configuration screen (#21).

### Constraints and out of scope

Distinct from #27: that is deploy-time settings and secrets; this is business-tunable values.

### Touches a screen a person looks at?

No


## #29 [story] Observability: structured logs, traces and metrics per work item

### Goal

Any work item can be followed end to end across stations, and stage health is measurable, without logging remittance content.

### Acceptance criteria

- [ ] Structured JSON logs carry `work_item_id`, stage, attempt and trace ID on every line.
- [ ] OpenTelemetry spans cover every station, Fusion call and LLM call, with token usage and latency.
- [ ] Metrics per stage (throughput, latency, failures by error code, queue depth and age) are exported to OCI Monitoring. *(inferred)*
- [ ] PII and artifact content never appear in logs or spans; a test asserts this.

### Constraints and out of scope

OCI Logging and Monitoring only. *(inferred)*

### Touches a screen a person looks at?

No


## #30 [story] Worker host: long-running processes for stations, pollers and the outbox relay

### Goal

One entry point starts any mix of station consumers, the two pollers and the outbox relay as long-running async processes that stop cleanly and report health.

### Acceptance criteria

- [ ] One CLI or entry point selects which roles a process runs.
- [ ] Graceful shutdown on SIGTERM: in-flight items finish or are released, never half-written.
- [ ] Liveness and readiness endpoints report each role's state.
- [ ] Concurrency per stage is configuration (#28), including a cap on concurrent Fusion applies per receipt. *(inferred)*

### Constraints and out of scope

No scheduler; only the two pollers are time-driven.

### Touches a screen a person looks at?

No


## #31 [story] Typed web API client and BFF proxy

### Goal

`web/` talks to the Python API only through one client typed from the API's OpenAPI schema, so contract drift is a type error.

### Acceptance criteria

- [ ] TypeScript types are generated from the OpenAPI schema, with a regenerate script.
- [ ] One server-side fetch wrapper attaches the user's access token, maps API errors to a `Result`, and is used by every route handler and server action.
- [ ] An SSE helper consumes the API's streaming endpoints for the flow monitor and chat.
- [ ] Nothing in `web/` calls the API around this client. *(inferred)*

### Constraints and out of scope

Next.js stays a thin client; no business rules.

### Touches a screen a person looks at?

No


## #32 [story] Fusion tenant setup kit and preflight check

### Goal

Everything a Fusion pod needs before this system runs against it is scripted or documented, and can be checked automatically.

### Acceptance criteria

- [ ] Documents the integration user and the exact roles it needs for REST reads, SOAP apply, BIP and attachments.
- [ ] The pay-on-behalf relationships BIP report (and any receipt-lookup report) is kept in the repo as catalog exports, with deploy steps.
- [ ] A preflight command checks a configured pod (auth, each endpoint, report present, header behaviour) and prints pass/fail.

### Constraints and out of scope

Read-only checks; never writes to a production pod.

### Touches a screen a person looks at?

No


## #33 [story] Spike: mailbox access method for the intake poller

### Goal

Decide how the intake poller reads the remittance mailbox(es) and marks processed mail; options include IMAP and Microsoft Graph, depending on the client's mail platform.

### Acceptance criteria

- [ ] Decision written up: protocol, auth (app registration or service account), folders, and the processed-mail convention.
- [ ] Confirms whether intake must accept internal senders (the previous build ignored them, which blocked backlog reprocessing).
- [ ] The `MailboxSource` plan in #6 is updated.

### Constraints and out of scope

Decision only; no production mailbox changes. Needs the mail platform from Jonathan.

### Touches a screen a person looks at?

No


## #34 [story] Artifact normalisation: every format, and one email with several remittances

### Goal

Each intake item becomes clean, reader-ready inputs whatever the format, and an email holding several remittances becomes several work items.

### Acceptance criteria

- [ ] Handles HTML and plain-text bodies, PDF, images, XLSX, CSV, DOCX, nested `.eml`/`.msg`, and zip archives.
- [ ] Signatures, disclaimers and quoted reply chains are stripped from bodies. *(inferred)*
- [ ] One email can produce several work items, one per remittance, linked to the parent.
- [ ] Unsupported formats become a typed `UNSUPPORTED_ARTIFACT` error, never a silent drop.

### Constraints and out of scope

Originals are always kept untouched in Object Storage.

### Touches a screen a person looks at?

No


## #35 [story] Backlog reprocessing: push historical remittances through the line safely

### Goal

Tens of thousands of historical remittances can go through the same pipeline, throttled, without flooding Fusion.

### Acceptance criteria

- [ ] Bulk import from a folder or mailbox folder, tagged as a backlog batch.
- [ ] A dry-run mode extracts and matches but never applies.
- [ ] A configurable rate limit, at a priority below live intake.
- [ ] Batch progress and results are visible (in the flow monitor, #19).

### Constraints and out of scope

Same stations and rules as live traffic; no separate code path.

### Touches a screen a person looks at?

No


## #36 [story] LLM usage and cost ledger

### Goal

Every LLM call records model, tokens, latency and cost against its work item and station, so cost per remittance and per station is known.

### Acceptance criteria

- [ ] Each Anthropic and OCI GenAI call writes a usage row: item, station, model, input/output tokens, latency, computed cost.
- [ ] Prompt and schema versions are recorded on every extraction and adjudication.
- [ ] Daily totals per station and model are queryable, and a configurable budget threshold raises an alert (#42). *(inferred)*
- [ ] Cohere dedicated-cluster utilisation is tracked alongside.

### Constraints and out of scope

None stated.

### Touches a screen a person looks at?

No


## #37 [story] Payer alias learning from human decisions

### Goal

Each human-confirmed payer-to-customer link and receipt match is used immediately, instead of the next-day mapping load the business lives with today.

### Acceptance criteria

- [ ] Confirmed aliases are stored with who and when: payer name, payer bank account, reference pattern → customer account.
- [ ] Customer resolution (#11) and the receipt scorer (#13) consult them, and the decision trail shows when one was used.
- [ ] A payer that maps to several accounts is never auto-assigned from an alias.
- [ ] Aliases can be reviewed and retired (on the configuration screen, #21). *(inferred)*

### Constraints and out of scope

None stated.

### Touches a screen a person looks at?

No


## #38 [story] Reverse an automated application in Fusion

### Goal

A wrong automated application can be undone from the workbench with a full audit trail; the previous build had no way to do this.

### Acceptance criteria

- [ ] The unapply call is confirmed on a non-production pod and wrapped in `FusionClient` (#5).
- [ ] A reversal requires a reason, is recorded on the item's history, and leaves the item re-matchable.
- [ ] Only permitted roles can reverse. *(inferred)*

### Constraints and out of scope

Never reverses an application this system didn't make.

### Touches a screen a person looks at?

No


## #39 [story] Earned-discount application

### Goal

Apply a discount only when the remittance references it, the payment terms earned it, and amounts agree within tolerance; otherwise treat it as a short pay. Never invent one.

### Acceptance criteria

- [ ] The payment-terms resource and the `createApplyReceipt` discount element are confirmed on a non-production pod.
- [ ] The earned discount is computed from terms and payment date and sent on the same apply call as the cash.
- [ ] New status `allocation-applied-with-discount`, plus a flag when Fusion rejects the discount.

### Constraints and out of scope

Blocked until the tenant confirmation succeeds. EU VAT discounts are a Fusion payment-terms fix, not this story.

### Touches a screen a person looks at?

No


## #40 [story] Item locking for human work

### Goal

When a person dequeues an item, automation can't touch it until they requeue or release it, and abandoned locks expire.

### Acceptance criteria

- [ ] Lease-based locks with owner, expiry and renewal; every station and auto-fix handler respects them.
- [ ] Locks can be released or force-taken, with audit. *(inferred)*
- [ ] Lock state is visible on the item and in the flow monitor.

### Constraints and out of scope

None stated.

### Touches a screen a person looks at?

No


## #41 [story] Operations reports and the daily summary

### Goal

AR and management can see how the line is doing without opening the app.

### Acceptance criteria

- [ ] Daily summary: items in, auto-applied rate, amount applied, failures by error code, items aging, escalations.
- [ ] A partially-paid-invoices report (short pays left open), which the business asked for.
- [ ] Reports export as CSV/XLSX; the daily summary is emailed, generated on request or by the first event after a configured cutover time. *(inferred)*

### Constraints and out of scope

No scheduler: generation is on demand or event-triggered.

### Touches a screen a person looks at?

Yes *(inferred)*


## #42 [story] Notifications for escalations and system problems

### Goal

The right people hear about escalations and outages as they happen.

### Acceptance criteria

- [ ] Configurable recipients and channels (email; Teams if the client uses it *(inferred)*) for escalated items, DLQ growth, Fusion or LLM outages, and budget alerts (#36).
- [ ] Notifications are batched and rate-limited so a flood becomes one message. *(inferred)*
- [ ] Every notification sent is logged.

### Constraints and out of scope

None stated.

### Touches a screen a person looks at?

No


## #43 [story] Anonymise prior production data into test fixtures

### Goal

The previous build's production day and the AR-labelled failure set become anonymised fixtures for the matcher, auto-fix engine and eval (#24).

### Acceptance criteria

- [ ] Customer names, account numbers, references and amounts are pseudonymised consistently, so relationships survive.
- [ ] AR's labels (receipt in Fusion / not yet / not in Fusion / future) are kept as expected outcomes.
- [ ] No real client or customer identifier remains; a scan test enforces it.

### Constraints and out of scope

The source data never enters the repo; only the anonymised output does.

### Touches a screen a person looks at?

No


## #44 [story] Release deploy pipeline to OCI

### Goal

BMN's release step has one reliable, repeatable way to ship to OCI; nothing deploys outside it.

### Acceptance criteria

- [ ] Builds images for api, workers and web and pushes them to OCIR (Ashburn) with version tags.
- [ ] Runs Alembic migrations on the target ATP (prod gets only what DEV already has), rolls out, then runs a smoke check.
- [ ] Manual trigger only; never triggered by a push to `dev`.
- [ ] A rollback path to the previous image version exists. *(inferred)*

### Constraints and out of scope

The BMN release step is the only caller.

### Touches a screen a person looks at?

No


## #45 [story] Data retention and purge

### Goal

Raw artifacts and model outputs containing client data are kept only as long as policy allows, while the decision audit trail survives.

### Acceptance criteria

- [ ] Retention periods are configuration (#28), separately for raw artifacts, extraction payloads and history.
- [ ] The purge deletes expired content from Object Storage and ATP and leaves a tombstone that preserves the decision trail.
- [ ] Triggered on demand or by the intake poller's cycle, never a scheduler. *(inferred)*

### Constraints and out of scope

The retention periods themselves are an open business decision.

### Touches a screen a person looks at?

No


