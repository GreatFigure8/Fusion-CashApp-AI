# Backlog review

**Filed 2026-10-23 as GitHub issues #1–#45**, each labelled `bmn`, with the "Changes to existing stories" folded in. Story *k* is issue #*k*, and N*k* is issue #(25 + *k*). The issues are the live record; this file is the history of how the backlog was reviewed.

The 25 proposed stories are reviewed two at a time for gaps. Each gap is drafted in `/bmn-issue` shape and numbered `N1`, `N2`, and so on. Lines marked *(inferred)* go beyond what CLAUDE.md states.

## Progress

All 25 stories have been reviewed. Stories 1–4 were reviewed in pairs, and 5–25 in one pass. The review found **20 new stories (N1–N20)**, additions to 13 existing stories, and 5 open business questions.

## The 25 proposed stories

1. Scaffold monorepo: `api/` (uv, FastAPI, SQLAlchemy async on ATP, Alembic, ruff, pyright), `web/` (Next.js, Tailwind, shadcn), `infra/` skeleton
2. Data layer foundation: `BaseRepository`, unit of work, work_item / history / outbox tables, single shared status enum
3. Pipeline runtime: abstract `StageRunner`, `EventBus` with OCI Streaming, outbox relay, retry and DLQ, idempotent consumers
4. Auth: OCI Identity Domains confidential-app OAuth in Next.js, JWT validation in the API, group→role table, `Principal`
5. `FusionClient`: REST v4 / paging / escaping, SOAP `createApplyReceipt` fail-closed parsing, BIP `runReport`, error mapping, Vault credentials
6. Intake poller: mailbox and folder sources, content-hash dedupe, Object Storage, configurable interval
7. Classify station (Haiku)
8. Extraction fan-out: Opus 5.5 reader and Cohere Command A Vision reader, shared schema
9. Adjudicate fan-in (Opus 5.5): per-field choice, source tracking, handling of one or both readers failing
10. Validate station: header vs lines, formats, dates, currency
11. Customer resolution: anchor customer plus pay-on-behalf relationships from BIP
12. Spike: receipt-signal study on a real pod
13. Receipt matching scorer: multi-signal, reservation, ambiguity is an error
14. Fusion receipt watcher and `AWAITING_RECEIPT` re-match
15. Line matching and apply: credit memos first, amount cap, idempotency, per-line persistence
16. "Already applied" fast path: attach and close
17. Write-back: receipt note and remittance attachment
18. Auto-fix engine
19. UI shell and flow monitor
20. UI exception workbench
21. UI configuration screen
22. UI shared LLM chat component
23. Fusion test-data generator
24. Extraction eval set and harness
25. OCI infrastructure (Ashburn)

## Gaps found

### Pair 1 (stories 1–2)

**N1. [story] CI gates on GitHub Actions for api and web**
- **Goal:** every push and PR to `dev` runs the same lint and type-check gates BMN uses, so broken code can't merge.
- **Acceptance criteria:**
  - [ ] A workflow runs `ruff check`, `ruff format --check` and `pyright` in `api/` on PRs and pushes to `dev`.
  - [ ] A workflow runs `next typegen && tsc --noEmit` and `eslint .` in `web/`.
  - [ ] Each job runs only when its folder changes, and caches dependencies. *(inferred)*
  - [ ] No workflow deploys anything or touches any database.
- **Constraints:** never deploys; BMN's stack-scout must see `dev_push_deploys: false`.
- **Screen:** No

**N2. [story] Application settings and secrets wiring**
- **Goal:** one typed settings object for `api/` and one for `web/`. Values come from the environment locally and from OCI Vault when deployed, so no secret is ever in code or `NEXT_PUBLIC_*`.
- **Acceptance criteria:**
  - [ ] `api/` has a `pydantic-settings` class covering ATP connection/wallet, Streaming, Object Storage, Anthropic, OCI GenAI endpoint, Identity Domain and Fusion. It fails fast on startup if a required value is missing.
  - [ ] A Vault-backed secret loader resolves secret OCIDs at startup when deployed.
  - [ ] `web/` validates its env with Zod at boot, and only public values use `NEXT_PUBLIC_*`.
  - [ ] `.env.example` files list every setting with no real values.
- **Constraints:** follows `python-web-app:wiring-application-config`.
- **Screen:** No

**N3. [story] Runtime configuration service (database-backed, versioned, audited)**
- **Goal:** every value CLAUDE.md calls "configuration" lives in ATP behind one typed service that every station reads, with a full change history. Examples: poll intervals, date window, tolerances per currency, retry limits, aging, model IDs and effort, fan-in timeout, group→role mapping.
- **Acceptance criteria:**
  - [ ] One config table plus repository, with typed accessors for each setting group.
  - [ ] Every change records who made it, when, and the old and new values.
  - [ ] Stations and pollers pick up a change without a restart, within one poll or event. *(inferred)*
  - [ ] An API (read for operators, write for admin) backs the UI configuration screen (story 21).
- **Constraints:** distinct from N2: N2 is deploy-time settings and secrets, N3 is business-tunable values.
- **Screen:** No

### Pair 2 (stories 3–4)

**N4. [story] Observability: structured logs, traces and metrics per work item**
- **Goal:** any work item can be followed end to end across stations, and stage health is measurable, without logging remittance content.
- **Acceptance criteria:**
  - [ ] Structured JSON logs carry `work_item_id`, stage, attempt and the trace ID on every line.
  - [ ] OpenTelemetry spans cover every station, every Fusion call and every LLM call, with token usage and latency recorded.
  - [ ] Metrics cover throughput, latency, failure rate by error code, queue depth and age per stage. They're exported to OCI Monitoring. *(inferred)*
  - [ ] PII and artifact content never appear in logs or spans. A test asserts this.
- **Constraints:** OCI Logging and Monitoring only. *(inferred)*
- **Screen:** No

**N5. [story] Worker host: long-running processes for stations, pollers and the outbox relay**
- **Goal:** one entry point starts any mix of station consumers, the two pollers and the outbox relay as long-running async processes that shut down cleanly and report health.
- **Acceptance criteria:**
  - [ ] One CLI or entry point selects which roles a process runs.
  - [ ] Shutdown on SIGTERM is graceful: in-flight items finish or are released, never half-written.
  - [ ] Liveness and readiness endpoints report each role's state.
  - [ ] Concurrency per stage is configuration (N3), including a cap on concurrent Fusion applies. *(inferred)*
- **Constraints:** no scheduler. Only the two pollers are time-driven.
- **Screen:** No

**N6. [story] Typed web API client and BFF proxy**
- **Goal:** `web/` talks to the Python API only through one client typed from the API's OpenAPI schema, so contract drift is a type error.
- **Acceptance criteria:**
  - [ ] TypeScript types are generated from the API's OpenAPI schema, with a script to regenerate them.
  - [ ] One server-side fetch wrapper attaches the user's access token, maps API errors to a `Result`, and is used by every route handler and server action.
  - [ ] An SSE helper consumes the API's streaming endpoints, for the flow monitor and chat.
  - [ ] Nothing in `web/` calls the API around this client. *(inferred)*
- **Constraints:** Next.js stays a thin client; no business rules.
- **Screen:** No

### Stories 5–25

**N7. [story] Fusion tenant setup kit**
- **Goal:** everything a Fusion pod needs before this system can run against it is scripted or documented, and it can be checked automatically.
- **Acceptance criteria:**
  - [ ] Documents the integration user and the exact roles it needs for REST reads, SOAP apply, BIP and attachments.
  - [ ] The pay-on-behalf relationships BIP report (and any receipt-lookup report) is kept in the repo as catalog exports, with deploy steps.
  - [ ] A "preflight" command checks a configured pod: auth, each endpoint reachable, report present, required header behaviour. It produces a pass/fail list.
- **Constraints:** read-only checks. Never writes to a production pod.
- **Screen:** No

**N8. [story] Spike: mailbox access method**
- **Goal:** decide how the intake poller reads the remittance mailbox(es) and how it marks processed mail. Options include IMAP and Microsoft Graph; the client's mail platform decides.
- **Acceptance criteria:**
  - [ ] The decision is written up: protocol, auth (app registration or service account), folders, and the processed-mail convention (move or flag).
  - [ ] It confirms whether intake must accept internal senders too. The previous build ignored internal senders, which blocked backlog reprocessing.
  - [ ] The `MailboxSource` implementation plan is updated.
- **Constraints:** decision only; no production mailbox changes.
- **Screen:** No

**N9. [story] Artifact normalisation**
- **Goal:** each intake item becomes clean, reader-ready inputs, whatever the format, and an email holding several remittances is split into several work items.
- **Acceptance criteria:**
  - [ ] Handles HTML and plain-text bodies, PDF, images, XLSX, CSV, DOCX, nested `.eml`/`.msg` and zip archives.
  - [ ] Signatures, disclaimers and quoted reply chains are stripped from bodies. *(inferred)*
  - [ ] One email can produce several work items, one per remittance, and they stay linked to the parent email.
  - [ ] Unsupported formats become a typed `UNSUPPORTED_ARTIFACT` error, never a silent drop.
- **Constraints:** originals are always kept untouched in Object Storage.
- **Screen:** No

**N10. [story] Backlog reprocessing**
- **Goal:** historical remittances (tens of thousands) can be pushed through the same pipeline, with throttling, so the backlog clears without flooding Fusion.
- **Acceptance criteria:**
  - [ ] Bulk import from a folder or mailbox folder, tagged as a backlog batch.
  - [ ] A dry-run mode extracts and matches but never applies.
  - [ ] A configurable rate limit, plus a priority below live intake.
  - [ ] Progress and results for each batch are visible.
- **Constraints:** same stations and rules as live traffic; no separate code path.
- **Screen:** No *(the progress view rides on story 19)*

**N11. [story] LLM usage and cost ledger**
- **Goal:** every LLM call records its model, tokens, latency and cost against the work item and station, so the cost of each remittance and each station is known.
- **Acceptance criteria:**
  - [ ] Each Anthropic and OCI GenAI call writes a usage row: item, station, model, input and output tokens, latency, computed cost.
  - [ ] Prompt and schema versions are recorded on every extraction and adjudication.
  - [ ] Daily totals per station and model are queryable, and a configurable budget threshold raises an alert. *(inferred)*
  - [ ] The utilisation of the Cohere dedicated cluster is tracked alongside.
- **Constraints:** none stated.
- **Screen:** No

**N12. [story] Payer alias learning**
- **Goal:** each human-confirmed payer→customer link and receipt match is stored and used by resolution and the scorer immediately. The old 6 am mapping load meant a fix only helped the next day.
- **Acceptance criteria:**
  - [ ] Confirmed aliases are stored with who confirmed them and when: payer name, payer bank account, reference pattern → customer account.
  - [ ] Customer resolution and the receipt scorer consult the aliases, and the decision trail shows when an alias was used.
  - [ ] A payer that maps to several accounts is never auto-assigned from an alias.
  - [ ] Aliases can be reviewed and retired in the UI. *(inferred)*
- **Constraints:** none stated.
- **Screen:** No *(the review list rides on story 21)*

**N13. [story] Reverse an automated application**
- **Goal:** a wrong automated application can be undone in Fusion from the workbench, with a full audit trail. Nothing like this existed in the previous build.
- **Acceptance criteria:**
  - [ ] The unapply call is confirmed on a non-production pod and wrapped in `FusionClient`.
  - [ ] A reversal needs a reason. It's recorded on the item's history and restores the item to a re-matchable state.
  - [ ] Only roles with permission can reverse. *(inferred)*
- **Constraints:** never reverse an application this system didn't make.
- **Screen:** No *(the action rides on story 20)*

**N14. [story] Earned-discount application**
- **Goal:** apply a discount only when the remittance references it, the payment terms earned it, and the amounts agree within tolerance. Otherwise treat it as a short pay. Never invent one.
- **Acceptance criteria:**
  - [ ] The payment-terms resource and the `createApplyReceipt` discount element are confirmed on a non-production pod.
  - [ ] The earned discount is computed from the terms and the payment date, and sent on the same apply call as the cash.
  - [ ] New status `allocation-applied-with-discount`, and flags for a rejected discount.
- **Constraints:** blocked until the tenant confirmation succeeds; EU VAT discounts are a Fusion payment-terms fix, not this story.
- **Screen:** No

**N15. [story] Item locking for human work**
- **Goal:** when a person dequeues an item, automation can't touch it until they requeue or release it, and abandoned locks expire.
- **Acceptance criteria:**
  - [ ] Lease-based locks with an owner, an expiry and renewal. Every station and auto-fix handler respects the lock.
  - [ ] Locks can be released or force-taken, with audit. *(inferred)*
  - [ ] The lock state is visible on the item and in the flow monitor.
- **Constraints:** none stated.
- **Screen:** No *(the UI rides on story 20)*

**N16. [story] Operations reports and the daily summary**
- **Goal:** AR and management see how the line is doing without opening the app.
- **Acceptance criteria:**
  - [ ] A daily summary covers: items in, auto-applied rate, amount applied, failures by error code, items aging, and escalations.
  - [ ] A partially-paid-invoices report (short pays left open), which the business explicitly asked for.
  - [ ] Reports are exportable as CSV/XLSX, and the daily summary is delivered by email. Generating it is triggered by the first event after the cutover time, or on request; never by a scheduler. *(inferred)*
- **Constraints:** no scheduler. Report generation is on demand or event-triggered.
- **Screen:** Yes *(inferred)*

**N17. [story] Notifications**
- **Goal:** the right people hear about escalations and system problems as they happen.
- **Acceptance criteria:**
  - [ ] Configurable recipients and channels (email; Teams if the client uses it *(inferred)*) for: items escalated to a person, DLQ growth, Fusion or LLM outages, budget alerts (N11).
  - [ ] Notifications are batched and rate-limited, so a flood becomes one message. *(inferred)*
  - [ ] Every notification sent is logged.
- **Constraints:** none stated.
- **Screen:** No

**N18. [story] Anonymise prior production data into fixtures**
- **Goal:** the previous build's production day and the AR-labelled failure set become anonymised fixtures for the matcher, the auto-fix engine and the extraction eval.
- **Acceptance criteria:**
  - [ ] Customer names, account numbers, references and amounts are consistently pseudonymised, so relationships survive.
  - [ ] AR's labels (receipt in Fusion / not yet / not in Fusion / future) are kept as expected outcomes.
  - [ ] No real client or customer identifier remains. A scan test enforces this.
- **Constraints:** the source data never enters the repo; only the anonymised output does.
- **Screen:** No

**N19. [story] Release deploy pipeline to OCI**
- **Goal:** BMN's release step has a reliable, repeatable way to ship to OCI. Nothing deploys outside it.
- **Acceptance criteria:**
  - [ ] Builds images for the API, workers and web, and pushes them to OCIR (Ashburn) with version tags.
  - [ ] Runs Alembic migrations on the target ATP (prod gets only what DEV already has), then rolls out, then runs a smoke check.
  - [ ] Manual trigger only; never triggered by a push to `dev`.
  - [ ] There's a rollback path to the previous image version. *(inferred)*
- **Constraints:** the BMN release step is the only caller.
- **Screen:** No

**N20. [story] Data retention and purge**
- **Goal:** raw artifacts and model outputs containing client data are kept only as long as policy allows, while the audit trail of decisions survives.
- **Acceptance criteria:**
  - [ ] Retention periods are configuration (N3), separately for raw artifacts, extraction payloads and history.
  - [ ] The purge deletes expired content from Object Storage and ATP, and keeps a tombstone that preserves the decision trail.
  - [ ] It's triggered by the intake poller's cycle or on demand, never a scheduler. *(inferred)*
- **Constraints:** the retention periods themselves are a business decision (open question).
- **Screen:** No

## Changes to existing stories

Acceptance-criteria additions found while reviewing. Fold them into the story when it's filed.

- **Story 4 (auth):** seed a bootstrap admin group→role mapping, so the first admin can sign in and configure the rest.
- **Story 3 (pipeline runtime):** consumer lag and DLQ depth are exposed for N4 metrics.
- **Story 5 (FusionClient):** register several pods (dev, test, prod) and select them by configuration. Also wrap the attachments and unapply calls (for N13 and story 17).
- **Story 7 (classify):** non-remittance items get a reason and are archived, not dropped. A person can override the decision and push an item back in.
- **Stories 8–9 (readers, adjudicator):** record prompt and schema versions on every output, and record which reader supplied each field.
- **Story 10 (validate):** when the currency is ambiguous (`$`), resolve it from the customer's account currency after story 11 runs. It isn't a failure at validate.
- **Story 11 (customer resolution):** consult payer aliases (N12) before falling back to the anchor-invoice rule.
- **Story 13 (scorer):** log every candidate's signal scores, so human decisions can tune the weights later.
- **Story 15 (apply):** respect locks (N15) and the per-receipt Fusion concurrency cap (N5).
- **Story 17 (write-back):** confirm the receipt attachment call on a non-production pod first; it's unconfirmed.
- **Story 19 (flow monitor):** the API needs an SSE endpoint for live stage counts. The item view shows the original artifact with each extracted field highlighted at its source.
- **Story 20 (workbench):** search by amount, payer, invoice, reference and date range. This fixes the old "can't search Gemstone by amount" pain.
- **Story 24 (eval):** also evaluates the matcher and the auto-fix engine against N18's labelled failure set, not just extraction.
- **Story 25 (infra):** separate DEV and PROD ATP schemas (BMN needs a DEV database); private endpoints; Object Storage encryption with customer-managed keys. *(inferred)*

## Open business questions (no story until answered)

1. Retention periods for raw remittances and model outputs (needed by N20).
2. The under-$1 write-off: automate it, or leave it to the "standard process"?
3. Overpayments: leave them unapplied on the receipt, or put them on account?
4. A bank-fee tolerance band: enabled, and how wide?
5. Which mail platform the mailbox is on (needed by N8).
