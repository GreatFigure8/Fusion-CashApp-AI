# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this system is

Fusion-CashApp-AI is an automated **cash application assembly line** for Oracle Fusion Receivables. It:

1. **Takes in** artifacts that may contain customer remittance advice: emails (body and attachments), images, PDFs, spreadsheets and other documents, pulled from a mailbox and from a drop folder.
2. **Classifies** each artifact: is this remittance advice at all?
3. **Extracts** the remittance data with an LLM: payer/customer, remittance reference, payment date, amount, currency, and the lines being paid (invoice or credit memo number, amount paid, discounts, deductions/short-pays), plus anything else useful for matching.
4. **Persists** the result to the database as a work item that the next station picks up.
5. **Resolves** the Fusion customer, **finds the matching receipt** in Fusion, **matches the invoices**, and **applies** the receipt to those invoices in Fusion, so no person has to.

The goal is the most automation we can get, **fixes included**. A stuck item should be repaired by the system itself whenever it can. A person only steps in when the automatic fixes run out, and the UI exists to make that quick.

The repository is greenfield. Everything below is the design that all code must follow. Where a section says *proposed*, it's a decision made at the start that a BMN run may refine. Record any refinement here.

**Read [docs/reference/prior-implementation-lessons.md](docs/reference/prior-implementation-lessons.md) before working on extraction, matching, Fusion calls, statuses or auto-fix.** It covers a previous production build of this same process (OIC-based):
- the Fusion calls that worked
- the matching rules and their known defects
- the status vocabulary
- real failure statistics

## Non-negotiables

1. **BMN (`dev-bother-me-nope`) drives all work**: intake, planning, design, coding and release. Work arrives as a BMN story (create one with `/bmn-issue <summary>`) and goes through the pipeline. See *Working with BMN* below.
2. **UI:** Next.js (App Router) + TypeScript + Tailwind + shadcn/ui.
3. **API:** Python, async end to end. The UI and the pipeline workers call it.
4. **No scheduler.** No cron, no batch windows, no Fusion ESS jobs, no "run every night". Every station reacts to an event the moment it arrives.
5. **There are exactly two pollers, and they are the only exceptions:**
   - the **intake poller**, which checks the mailbox and the drop folder;
   - the **Fusion receipt watcher**, which checks Fusion for newly created receipts.
   
   Each runs every *N* minutes, with its own *N* configurable at runtime. Each is a long-running async loop inside a worker, not a scheduled job, and its only output is new events. Don't add a third without Jonathan.
6. **Layered architecture:** a data layer (models + generic repository over an ORM), a business layer (services/runners), and a transmission layer (JSON over HTTP, request/response or streaming). See *Architecture*.
7. **Don't repeat yourself.** Each piece of behaviour and each shared UI component exists exactly once and is configured through props or parameters. One chat-with-the-LLM component serves every place a user can talk to the LLM. One pipeline-stage runner base serves every station. One status enum serves the matcher, the API, the UI and reporting. A second copy is a defect.
8. **Hosted 100% in OCI, in Ashburn (`us-ashburn-1`).** That covers compute, ATP, Streaming, Object Storage, Vault and Generative AI. No Vercel, no Supabase, no other cloud or region for hosting. Calls out to the Claude API are fine.
9. **Fusion reads and REST writes go through the fusion-sql-mcp (Greenlight) server, behind `FusionClient`.** The one direct call is the SOAP `createApplyReceipt` (and the unapply), made from the API with credentials from Vault. The server is an OAuth `client_credentials` client of the identity domain, and the app holds no Fusion REST credentials. Report-style reads (pay-on-behalf relationships, receipt signals) are ad-hoc SQL data models run through `run_query`, so no catalog report is created per tenant. **Never OIC.** Refined 2026-10-23 (bmn-ui-techy-redesign, fusion-mcp-transport); it was "integrated directly through Fusion REST, SOAP and BI Publisher".

## Architecture

### Ownership: the Python API owns all data and business logic

The house Next.js standard (`nextjs-fullstack-standards`) normally puts repositories and services inside Next.js. **This repo deliberately doesn't.** The pipeline workers and the UI need the same data and the same rules, so both live once, in Python:

```
web/ (Next.js)                         thin client: pages, shared components, typed API client
   │  HTTP JSON / SSE
   ▼
api/  transmission layer               FastAPI routers: validate, authorize, shape JSON, stream
   ▼
api/  business layer                   services + stage runners: all rules, orchestration, auto-fix
   ▼
api/  data layer                       generic repository over SQLAlchemy; the ONLY code touching the ORM
   ▼
Oracle Autonomous AI Database (ATP)
```

- Next.js never connects to the database. Its route handlers and server actions are thin proxies to the Python API, typed from the API's OpenAPI schema. They hold no business rules.
- The `nextjs-fullstack-standards` rules still apply to everything else in `web/`: strict TypeScript, Zod at boundaries, Server Components by default, shadcn primitives from the CLI, `Result`-style errors. Its `lib/db` and `lib/repositories` sections don't apply here.
- All settings except the database connection (and the few bootstrap values listed in docs/reference/settings.md) are DB config keys, edited in Settings, versioned and audited.
- Layers depend only downward. Routers never import SQLAlchemy. Repositories never contain business rules. Services never touch `Request` or `Response` objects, so the same service can be called from a router, a stage runner or a test without changes.

### Data layer (`api/.../data/`)

- **ORM: SQLAlchemy 2.0 (async) on `python-oracledb`** (`oracle+oracledb` dialect, async engine). Use thin mode with the ATP wallet or TLS connect string. Migrations use **Alembic**.
  - Why: it's the only mature Python ORM with first-class Oracle support, including identity columns, native JSON and sequences. It also supports async, and Alembic gives versioned, reviewable schema changes.
- **ORM models** mirror the database tables, one module per domain area.
- **A generic `BaseRepository[ModelT]`** provides get, list (with filtering and paging), add, update and delete. Each entity's repository subclasses it and adds only the queries specific to that entity. No query is written outside a repository.
- **Transaction boundaries belong to services**, through a unit of work or session passed into the repositories. Repositories never commit. A state change, its history row and its outbox event are written in one transaction.
- **ATP specifics:**
  - Use native `JSON` columns for raw LLM output and extraction payloads.
  - Use `VECTOR` (Autonomous AI Database) if we add embedding-based customer or invoice matching.
  - Use identity columns for primary keys.
  - Use `SELECT … FOR UPDATE SKIP LOCKED` to claim work and to reserve receipts.
  - Keep identifiers within Oracle's limits, and use upper snake case for database objects.

### Business layer (`api/.../services/`, `api/.../pipeline/`)

- **Services** hold the domain rules. Examples: is this a remittance, which customer is this, which receipt matches, how the lines reconcile to the receipt, what tolerance applies.
- **Stage runners** are the stations of the assembly line. Every station subclasses **one abstract `StageRunner`** that owns the shared machinery:
  1. consume the event
  2. claim the work item
  3. take an idempotency guard
  4. call the stage's service
  5. persist the result and the state transition
  6. emit the next event through the outbox
  7. on failure, classify the error and hand it to the auto-fix engine

  A concrete runner implements only its stage-specific step.
- **Integrations sit behind interfaces**, so stages never know which provider is plugged in:
  - `MailboxSource`, `FolderSource`
  - `LlmClient` (Anthropic and OCI implementations)
  - `FusionClient`
  - `EventBus`

### Transmission layer (`api/.../api/`)

- **FastAPI routers** return JSON only.
- **Request/response** for commands and queries.
- **SSE streaming** for live pipeline flow in the UI and for LLM chat responses.
- **Pydantic v2 schemas** define the API contracts. They're kept separate from the ORM models, and nothing returns an ORM model directly.
- **One error shape** across the whole API.
- The OpenAPI schema is the contract the `web/` client is generated or typed from.

### The assembly line

*Proposed* stations, each with its own topic:

```
intake → classify (Haiku) → extract (Opus ∥ Cohere) → adjudicate (Opus) → validate → resolve customer → match receipt ⇄ (await receipt) → match lines → apply in Fusion → write-back → done
```

- **The database is the system of record.** Every artifact becomes a `work_item` with a current stage, a status, an attempt count, its last error, and a full history of transitions and auto-fixes. The bus only carries "item X is ready for stage Y" events.
  - Why: the previous build lost selective re-drive when it moved its queue to Kafka. Keeping state in the database is what makes dequeue, fix and requeue possible.
- **Transactional outbox:** a state change and its outgoing event are written in the same database transaction. A relay then publishes the event. Consumers are idempotent: every handler checks the item's stage and status before acting, so redelivery is harmless.
- **Dedupe at intake** on a content hash of the artifact. The same remittance often arrives twice. Raw artifacts are kept in OCI Object Storage, and the work item references them.
- **Validate is code, not the LLM.** It checks:
  - lines against the header (a mismatch is a flag, not a failure)
  - invoice-number formats
  - dates and currency
- **Await receipt is the biggest lever on the automation rate.** In the previous build, about 70% of failed payments were "receipt not found". Most of those were timing: the remittance arrived before the bank receipt was in Fusion.
  - **Don't use a fixed hold.** Items wait in `AWAITING_RECEIPT` and are re-matched when the receipt arrives, with aging and escalation. The aging limit (for example 30 days) is configuration.
  - **The Fusion receipt watcher** (non-negotiable 5) produces the "receipt arrived" events.
    - It queries `standardReceipts` for receipts created since its last high-water mark, which is stored in the database so a restart neither misses nor replays receipts.
    - It emits one event per new receipt, and that event wakes the `AWAITING_RECEIPT` items it could match by customer, currency, amount and date window.
    - It filters on creation time, not receipt date: receipts are often created a day after their receipt date.
- **Write-back** posts the outcome to Fusion and closes the loop:
  - a receipt note saying what was applied and why lines failed (the receipt note field is small, so this needs design)
  - the remittance attached to the receipt
- **Bus:** OCI Streaming through its Kafka-compatible endpoint (SASL_SSL), accessed only through the `EventBus` interface.
  - Each stage has a retry path and a dead-letter path.
  - Use one consumer group per environment, and never rename or reset it.
  - Commit offsets only after persisting.

### Models: who does what

The model roles are a **decision, not a default**. Don't change them without Jonathan.

| Role | Model | Does |
|---|---|---|
| **Reader A** | Claude Opus 5.5 (`claude-opus-5-5`), Anthropic SDK | Reads the artifact and extracts the remittance. |
| **Reader B** | Cohere Command A Vision (`cohere.command-a-vision`), OCI Generative AI | Reads the same artifact independently and extracts the same remittance. |
| **Adjudicator** | Claude Opus 5.5 (`claude-opus-5-5`), as a separate call from Reader A | **Only** compares the two readers' outputs and decides, per field and per line, whether to take A, take B, or combine them. It never reads the artifact, never extracts and never does anything else. |
| **Workhorse** | Claude Haiku 5.5 (`claude-haiku-5-5`) | **Everything else** that needs an LLM: triage ("is this a remittance?"), the shared chat component, auto-fix reasoning, summaries, notes written back to Fusion. |

**Extraction is a fan-out/fan-in**

```
extract (fan-out) ──► Reader A: Opus 5.5        ──┐
                  └─► Reader B: Cohere Vision   ──┴─► adjudicate (fan-in): Opus 5.5 ──► validate
```

- **Both readers get the same input and the same Pydantic extraction schema.** Each result is persisted separately on the work item before the fan-in.
- **The fan-in waits for both readers,** with a configurable timeout. If one reader fails or times out, the adjudicator decides on the one result it has; the decision records which reader was missing. If both fail, the item goes to auto-fix as `EXTRACTION_FAILED`.
- **The adjudicator's output** is the final extraction plus a per-field record of where each value came from (A, B or both), the disagreements and a confidence score. Store it with the two raw outputs, so every value is traceable to a reader.

**API rules for each model.** Use structured outputs everywhere (`client.messages.parse` / `output_config.format`), so no station parses free-form text.

- **Zero data retention is required for every Claude call,** because client remittance data must not be retained. **Never use Claude Fable models:** they require 30-day retention. Any model change must keep zero-retention eligibility.
- **Opus 5.5 (reader and adjudicator):**
  - Thinking can't be disabled.
  - Effort defaults to `medium`, so set it explicitly for each role.
  - Forced `tool_choice` returns a 400.
  - Check `stop_reason` for `refusal` before reading the content.
- **Cohere** goes through the OCI SDK behind its own `LlmClient` implementation. It runs on a **dedicated AI cluster in Ashburn**.
  - On-demand `cohere.command-a-vision` was retired in Ashburn on 2025-12-10 (verified 2026-10-23 with a live test call). So inference uses `servingType: DEDICATED` against the cluster's endpoint OCID, which is configuration.
  - The cluster and endpoint are infrastructure in `infra/`.
  - The cluster costs money by the hour whether used or not. Size it for peak extraction throughput, and expose its utilisation in the flow monitor.

Model IDs, effort levels, timeouts and the fan-in policy are all configuration, editable in the UI's configuration screen.

**The extraction schema must handle what broke last time:**
  - invoice numbers as **strings**, with suffixes like `-1` for credit memos
  - lines with no amounts
  - multiple dates per remittance (keep all of them and choose one)
  - ambiguous `$` currency
  - PO, sales-order and ERS references
  - bank fees and tariff lines
  - discounts claimed
- **Every extracted field records** its source (artifact, page and region where possible), the model used and a confidence score.

### Matching and apply rules

The full rule set, with its sources, is in the reference doc §4. In short:

- **Customer**
  - The anchor customer is the `BillToCustomerNumber` of the first invoice found.
  - Pay-on-behalf relationships (one hop, both directions) **only widen** the receipt search. They're never a failure.
  - Never auto-assign a payer that maps to multiple accounts.
- **Receipt match**
  - One receipt per payment: same currency, amount within tolerance, and receipt date within the configured window of the payment date. The window was ±5 days in production; it's one setting shared by the Fusion query and the matcher.
  - Anchor-owned receipts first, then related customers' receipts.
  - **If more than one receipt qualifies, it's an ambiguity error, not "first wins".**
  - **Reserve the matched receipt** in the database before applying.
  - Match on the receipt's *remaining* unapplied amount, so a retry resumes after a partial apply.
- **Lines**
  - Credit memos are applied first.
  - Reject zero-amount lines.
  - Apply the customer's stated amount, **capped at `min(line amount, invoice balance, receipt remaining)`**. A short pay leaves the invoice open.
  - Check invoice currency and status (the previous build fetched them and never checked them).
  - Dedupe repeated invoices.
- **Idempotency:** check Fusion's existing applications before every apply.
- **Persist each line's result as it happens,** so a crash mid-remittance never loses what was already applied.
- **Tolerances are configuration per currency.** Agreed starting values: ±0.10, and ±0.49 for INR. Bank-fee bands and discounts are configurable rules.
  - A tolerance widens the *match* only. Apply the real amounts and record the residual.
  - **Never invent a discount.** Take one only when the remittance references it and the payment terms earned it.
- **One shared status enum** (reference doc §5). Payment and line statuses, failure precedence and info flags are defined once and imported everywhere. The roll-up is derived strictly from line and header results.

### Self-healing (auto-fix engine)

- **Classify every failure into a typed error code.** Seed the list from the real failure data in the reference doc §6:

  | Error code | Fix |
  |---|---|
  | `RECEIPT_NOT_YET_AVAILABLE` | Await receipt and re-match. Also try matching on the receipt *creation* date. |
  | `RECEIPT_AMBIGUOUS` | Narrow with remittance references and dates, otherwise a person. |
  | `AMOUNT_VARIANCE` | Configured tolerance or bank-fee band, otherwise a person. |
  | `CUSTOMER_NOT_FOUND` / `INVOICE_NOT_FOUND` | Re-extract, fuzzy or alias matching, invoice-number normalisation. |
  | `LOW_EXTRACTION_CONFIDENCE` | Re-run the readers at higher effort and adjudicate again. |
  | `EXTRACTION_FAILED` | Retry the failed reader(s), otherwise a person. |
  | `FUSION_OVERAPPLY` (AR-855287) | Clamp to the invoice balance. |
  | `FUSION_ALREADY_APPLIED` (AR-856102) | Reconcile against existing applications, then succeed. |
  | `FUSION_LOCKED` (ORA-00054, AR-856792) and `FUSION_TRANSIENT` (401/5xx/timeouts) | Retry with backoff. |
  | `FUSION_GL_DATE` (AR-856089) | Re-date to on or after the receipt's GL date. |

- **Every handler is bounded** by a maximum number of attempts, and every attempt is recorded on the item's history with its reasoning.
- **Retry only transient failures.** Never retry an invoice that is not found or closed without new information.
- **Escalate to a person** only when the handlers are exhausted or a confidence or tolerance threshold says a person must decide. Every threshold and limit lives in configuration, not in code.
- **Always a person:** prepayments; PO, sales-order and ERS-only references; dual-currency payers; anything ungrounded in the remittance.
- **Human requeue reuses the same machinery.** When a person dequeues an item in the UI, it's **locked** so automation never acts behind them. They fix the data and requeue it, and it goes back through the same stage runner. There's no separate "manual" code path.

### Fusion integration

All Fusion traffic goes through one `FusionClient` interface. Its implementation, `McpFusionClient`, composes two transports and handles:
- reads and REST writes through the **fusion-sql-mcp (Greenlight) server**: one shared `McpClient` (official `mcp` SDK, streamable HTTP, OAuth `client_credentials` JWT, scope `greenlight/mcp`), configured by the `mcp.*` keys, with the client secret read from OCI Vault at use
- the **direct SOAP** apply and unapply (`createApplyReceipt`), the one call that does not go through the server, with the pod credentials from OCI Vault
- retries and backoff
- `hasMore` pagination (one server call is one page)
- escaping of `q=` values
- a typed error mapping into the auto-fix error codes
- the write rails: every write is refused unless `fusion.write_enabled` is true, the pod is not production outside `prod`, and the MCP source does not report itself as production outside `prod`

Facts from the previous build (reference doc §3):

- **REST** (through `fusion_rest_get` / `fusion_rest_write`)
  - `/fscmRestApi/resources/11.13.18.05/…`. The server sends `REST-Framework-Version: 4`; without it, `in (...)`, `AND` and `BETWEEN` return 400. The worker start-up probe fails loudly on a 400.
  - Use `onlyData=true` and explicit `fields=`.
  - Batch invoice lookups into one `TransactionNumber in (...)` call. Query **both** `receivablesInvoices` and `receivablesCreditMemos`; credit memo balances are negative.
  - `standardReceipts` couldn't be filtered by `UnappliedAmount` or `Currency` on that tenant, so filter those in memory.
- **Apply: SOAP `createApplyReceipt`** on `/fscmService/StandardReceiptService`. There is no REST apply and the MCP server has no SOAP tool, so this stays direct.
  - Key on **IDs** (`ReceiptId`, `CustomerTrxId`), because numbers are not unique.
  - Amounts are signed.
  - Accounting date = the later of payment date and today.
  - **Parse fail-closed.** Faults also arrive inside HTTP 200 envelopes, and some codes are noise to ignore.
- **Pay-on-behalf relationships and receipt signals** are SQL data models (`api/src/cashapp/integrations/fusion/datamodels/`) run through `run_query` and rendered back as `DATA_DS/G_1` rows. Nothing is created in the BI Publisher catalog.
- **Never guess an endpoint, payload or field name.** Confirm against a live non-production pod first. In this environment, the `aix-greenlight` MCP provides `fusion_rest_describe` / `fusion_rest_get` for REST, and `run_query` for read-only SQL.
- **Applies are about 6 seconds per line.** Limit concurrency per receipt and apply back-pressure, so the pipeline never floods Fusion.

### Authentication and authorization

- **Sign-in uses OCI IAM Identity Domains** through a **confidential application**, with the standard OAuth 2.0 / OIDC authorization code flow (with PKCE).
  - **Next.js is the confidential client.** Its server side does the code exchange and keeps the client secret, which comes from OCI Vault and is never in `NEXT_PUBLIC_*`.
  - It holds the session in an encrypted, httpOnly cookie, and the browser never sees tokens.
  - It calls the Python API with the user's access token.
- **The Python API validates every token itself**, using the identity domain's JWKS. It checks issuer, audience and expiry. The API never trusts Next.js to have checked.
- **OCI groups map to app roles.**
  - The token carries the user's identity-domain groups. Configure the confidential app so it does, and verify against the domain rather than assuming the claim name.
  - The mapping from groups to app roles is **configuration stored in the database**, editable by an admin in the UI, not hard-coded. Roles map to permissions.
  - **Authorization is enforced in the API** with one shared dependency that turns the token into a `Principal` (user, groups, roles).
  - The UI only hides what a user can't do. It is never the control.
- **Services receive the `Principal` as a plain argument,** not the request. Every human action is recorded on the item's history with who did it: dequeue, edit, requeue, configuration change.
- **Machine identities are separate:**
  - Pipeline workers run services in-process and act as a system principal. They never borrow a user's token.
  - Fusion calls use the integration's own credentials from OCI Vault.

### UI (`web/`)

- **Flow monitor:** live counts and throughput per stage, plus drill-down from a stage to its items, from an item to its history, and from the history to the raw artifact, the extracted data and the per-line Fusion outcome.
- **Exception workbench:** exceptions only, with automatically applied items hidden by default. From there a person can:
  - dequeue (lock) a stuck item
  - see why it's stuck and which auto-fixes were tried
  - correct the data
  - requeue it

  It must show what Fusion's own screens make hard: the invoice-to-customer link, the customer location, original and remaining amounts, and credit memo history.
- **Configuration** (admin role): group-to-role mapping, poll intervals, date window, tolerances, retry limits, aging, model IDs and effort, and the fan-in timeout.
- **LLM conversation**, wherever it appears (asking about an item, asking about the flow, and so on), uses the single shared chat component, configured by props: context, system prompt key and available actions.
- **Shared components** live in one place (`web/components/common/` or similar). shadcn primitives live in `components/ui/` and come from `npx shadcn@latest add`. Before you build a component, search for an existing one to configure or extend.

## Repository layout

```
api/                          Python service (uv project, package `cashapp`)
  src/cashapp/
    main.py                   create_app(): middleware, error handlers, router auto-discovery
    api/                      transmission layer: errors.py (single error shape), middleware.py, discovery.py
      routers/                one module per endpoint group, each exporting `router`
    data/                     data layer: engine.py, base.py, models/, repositories/
    domain/ services/ pipeline/ stations/ pollers/ integrations/ workers/ observability/ auth/ tools/
  alembic/                    async migrations against ATP (env.py auto-imports data/models/*)
  tests/                      pytest (conftest.py, support/)
web/                          Next.js App Router, no src/ directory
  app/ components/{ui,common}/ lib/ hooks/ tests/ e2e/
infra/                        Terraform: versions.tf, providers.tf, variables.tf, modules/, envs/{dev,prod}
docs/                         design notes and reference/; BMN writes runs to docs/sprints/bmn-<run-slug>/
```

- Router auto-discovery: a new endpoint group is a new module in `api/src/cashapp/api/routers/` exporting `router`. No story edits `main.py`.
- New ORM models are new modules in `api/src/cashapp/data/models/`; `alembic/env.py` imports them automatically.
- `components/ui/` is shadcn CLI output only (this shadcn version has `field` instead of `form`). Shared components go in `components/common/`.

## Commands

**API (`api/`):** Python 3.12+, `uv`

```bash
uv sync                                   # install
uv run ruff check . && uv run ruff format --check .
uv run pyright                            # type-check (BMN code gate)
uv run pytest                             # full suite (atp and live markers skipped by default)
uv run pytest -m atp                      # tests needing the DEV ATP schema
uv run pytest tests/test_matching.py::test_exact_amount   # single test
CASHAPP_DATABASE_URL=... uv run alembic upgrade head      # apply migrations (DEV schema only)
CASHAPP_DATABASE_URL=... uv run alembic revision --autogenerate -m "<msg>"
uv run alembic heads
uv run fastapi dev src/cashapp/main.py    # run the API locally
```

**Web (`web/`):**

```bash
npm install
npx next typegen && npx tsc --noEmit      # type-check (BMN code gate)
npx eslint .                              # lint (BMN code gate)
npx vitest run path/to/file.test.ts -t "name"   # single test
npx playwright test                       # e2e (builds and serves on PLAYWRIGHT_PORT, default 3100)
npm run dev
```

**Infra (`infra/`):**

```bash
terraform -chdir=infra init -backend=false && terraform -chdir=infra fmt -check -recursive && terraform -chdir=infra validate
```

## Working with BMN

BMN's defaults assume Vercel and Supabase. Neither is used here. The same rules carry over:

- **Branches:**
  - `dev` is the integration branch.
  - `main` changes only during a BMN release.
  - BMN works in `sprint/<run-slug>` and `wip/<run-slug>/<slug>` worktrees, merges into `dev` with `--no-ff`, and never switches branches in the main checkout.
- **Code gates during coding are lint and type-check only.** Python uses `ruff` + `pyright`. Web uses `tsc` + `eslint`. Tests are written and run only in BMN's test cycles.
- **Database:**
  - Alembic migrations go to the **DEV ATP schema** only during a run.
  - The production ATP gets only migrations already applied to DEV, and only at release.
  - No ad-hoc DDL against either database.
- **Deploys:** nothing deploys to OCI before Jonathan says "release". The OCI deploy (images to OCIR, rollout of API, workers and web) is the release step's job only.
- **Fusion:** during a run, tests and development use a non-production Fusion pod. Never apply receipts in a production pod outside a release-approved, configured environment.
- **Test data:** build a parameterized Fusion test-data generator. It creates invoices, credit memos and unapplied receipts through REST: `POST receivablesInvoices`, then `completeTransaction`, then `POST standardReceipts` with no application. It must cover splits, short pays, INR rounding, duplicate amounts and ambiguous receipts. The previous build's 1:1 generator couldn't exercise any of these.
- **Stack routing for this repo:** `kind: mixed`.
  - `api/` is `web-app`/`api` + `llm`: the `python-web-app` skills plus `python-llm-features` and `claude-api`.
  - `web/` is TypeScript/Next.js: `nextjs-fullstack-standards` plus BMN's Next.js reference.

## Conventions specific to this domain

- **Money is `Decimal` end to end** (2 dp, `ROUND_HALF_UP`; Python's `round` uses banker's rounding) **and carries its currency.** Exact equality means `|a − b| ≤ 0.005`.
- **Customer PII and remittance content stay inside OCI.** The exceptions are the Claude API calls (Opus, Haiku), which run under zero data retention; Cohere runs in OCI Generative AI. Raw artifacts, prompts and model output are never logged in full outside the database or Object Storage.
- **Every automated decision is auditable from the item's history**: match, auto-fix and Fusion write. Someone must be able to answer "why did the system apply this receipt to these invoices?".
- **No client or customer names** from the prior engagement go in code, tests, fixtures or docs.
