# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this system is

Fusion-CashApp-AI is an automated **cash application assembly line** for Oracle Fusion Receivables. It:

1. **Takes in** artifacts that may contain customer remittance advice: emails (body and attachments), images, PDFs, spreadsheets and other documents, pulled from a mailbox and from a drop folder.
2. **Classifies** each artifact: is this remittance advice at all?
3. **Extracts** the remittance data with an LLM and, where it helps, a focused vision/document-AI model: payer/customer, remittance reference, payment date, amount, currency, and the invoice lines being paid (invoice number, amount paid, discounts, deductions/short-pays), plus anything else useful for matching.
4. **Persists** the result to the database as a work item that the next station picks up.
5. **Resolves** the Fusion customer, **finds the matching receipt** in Fusion, **matches the invoices**, and **applies** the receipt to those invoices in Fusion, so no person has to.

The goal is the most automation we can get, **fixes included**. A stuck item should be repaired by the system itself whenever it can. A person only steps in when the automatic fixes run out, and the UI exists to make that quick.

The repository is greenfield. Everything below is the design that all code must follow. Where a section says *proposed*, it's a decision made at the start that a BMN run may refine. Record any refinement here.

## Non-negotiables

1. **BMN (`dev-bother-me-nope`) drives all work**: intake, planning, design, coding and release. Work arrives as a BMN story (create one with `/bmn-issue <summary>`) and goes through the pipeline. See *Working with BMN* below.
2. **UI:** Next.js (App Router) + TypeScript + Tailwind + shadcn/ui.
3. **API:** Python, async end to end. The UI and the pipeline workers call it.
4. **No scheduler.** No cron, no batch windows, no Fusion ESS jobs, no "run every night". Every station reacts to an event the moment it arrives.
5. **The single exception is the intake poller.** It checks the mailbox and the drop folder every *N* minutes, with *N* configurable at runtime. It's a long-running async loop inside a worker, not a scheduled job, and its only output is new work items.
6. **Layered architecture:** a data layer (models + generic repository over an ORM), a business layer (services/runners), and a transmission layer (JSON over HTTP, request/response or streaming). See *Architecture*.
7. **Don't repeat yourself.** Each piece of behaviour and each shared UI component exists exactly once and is configured through props or parameters. One chat-with-the-LLM component serves every place a user can talk to the LLM. One pipeline-stage runner base serves every station. A second copy is a defect.
8. **Hosted 100% in OCI.** No Vercel, no Supabase, no other cloud.
9. **Fusion is integrated directly.** Use the Fusion REST APIs (and BI Publisher for bulk reads where REST is too thin). **Never OIC.** This system contains all of the integration machinery itself.

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
- Layers depend only downward. Routers never import SQLAlchemy. Repositories never contain business rules. Services never touch `Request` or `Response` objects, so the same service can be called from a router, a stage runner or a test without changes.

### Data layer (`api/.../data/`)

- **ORM: SQLAlchemy 2.0 (async) on `python-oracledb`** (`oracle+oracledb` dialect, async engine). Use thin mode with the ATP wallet or TLS connect string. Migrations use **Alembic**.
  - Why: it's the only mature Python ORM with first-class Oracle support, including identity columns, native JSON and sequences. It also supports async, and Alembic gives versioned, reviewable schema changes.
- **ORM models** mirror the database tables, one module per domain area.
- **A generic `BaseRepository[ModelT]`** provides get, list (with filtering and paging), add, update and delete. Each entity's repository subclasses it and adds only the queries specific to that entity. No query is written outside a repository.
- **Transaction boundaries belong to services**, through a unit of work or session passed into the repositories. Repositories never commit.
- **ATP specifics:**
  - Use native `JSON` columns for raw LLM output and extraction payloads.
  - Use `VECTOR` (Autonomous AI Database) if we add embedding-based customer or invoice matching.
  - Use identity columns for primary keys.
  - Money is always `NUMBER` in the database and `Decimal` in Python, never `float`.
  - Keep identifiers within Oracle's limits, and use upper snake case for database objects.

### Business layer (`api/.../services/`, `api/.../pipeline/`)

- **Services** hold the domain rules. Examples: is this a remittance, which customer is this, which receipt matches, how the invoice lines reconcile to the receipt amount, what tolerance applies.
- **Stage runners** are the stations of the assembly line. Every station subclasses **one abstract `StageRunner`** that owns the shared machinery:
  1. consume the event
  2. load the work item
  3. take an idempotency guard
  4. call the stage's service
  5. persist the result and the state transition
  6. emit the next event through the outbox
  7. on failure, classify the error and hand it to the auto-fix engine

  A concrete runner implements only its stage-specific step.
- **Integrations sit behind interfaces**, so stages never know which provider is plugged in:
  - `MailboxSource`, `FolderSource`
  - `LlmClient`, `VisionExtractor`
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
intake → classify → extract → validate/normalize → resolve customer → match receipt → match invoices → apply in Fusion → done
```

- **The database is the system of record.** Every artifact becomes a `work_item` with a current stage, a status, an attempt count, its last error, and a full history of transitions and auto-fixes. The bus only carries "item X is ready for stage Y" events. That's what makes dequeue, fix and requeue possible on Kafka-style streams, which can't remove a message.
- **Transactional outbox:** a state change and its outgoing event are written in the same database transaction. A relay then publishes the event. Consumers are idempotent: every handler checks the item's stage and status before acting, so redelivery is harmless.
- **Dedupe at intake** on a content hash of the artifact. Raw artifacts are kept in OCI Object Storage, and the work item references them.
- **Bus:** OCI Streaming through its Kafka-compatible endpoint (SASL_SSL). It's accessed only through the `EventBus` interface, so the transport can change without touching stages. Each stage has a retry path and a dead-letter path.

### Self-healing (auto-fix engine)

- **Classify every failure into a typed error code**, for example:
  - `CUSTOMER_NOT_FOUND`
  - `RECEIPT_NOT_FOUND`
  - `AMOUNT_MISMATCH`
  - `LOW_EXTRACTION_CONFIDENCE`
  - `FUSION_TRANSIENT`
  - `INVOICE_CLOSED`
- **Register remediation handlers per error code.** Examples:
  - re-extract with the vision model or a stronger LLM
  - fuzzy or alias customer matching
  - retry a transient Fusion error with backoff
  - look for the receipt in a wider date or amount window
  - reconcile short-pays to deduction reasons
- **Every handler is bounded** by a maximum number of attempts, and every attempt is recorded on the item's history with its reasoning.
- **Escalate to a person** only when the handlers are exhausted or a confidence or tolerance threshold says a person must decide. Every threshold and limit lives in configuration, not in code.
- **Human requeue reuses the same machinery.** When a person dequeues an item in the UI, fixes the data and requeues it, the item goes back through the same stage runner. There's no separate "manual" code path.

### Fusion integration

- **Reads and writes go through one `FusionClient`.** It handles:
  - authentication, with credentials from OCI Vault
  - retries and backoff
  - pagination
  - a typed error mapping into the auto-fix error codes
- **Bulk reads** (open invoices, receipts awaiting application, customer accounts and sites) may use BI Publisher where REST is too thin.
- **Writes** are receipt-to-invoice applications through the Receivables REST resources. Every write is idempotent: check the current application state in Fusion before writing.
- **Confirm the exact endpoint, payload and behaviour against a live pod before coding against it.** In this environment, the `aix-greenlight` MCP provides `fusion_rest_describe` / `fusion_rest_get` for REST, and `run_query` for read-only SQL through BIP. Never guess resource paths or field names.

### UI (`web/`)

- **Flow monitor:** live counts and throughput per stage, plus drill-down from a stage to its items, from an item to its history, and from the history to the raw artifact and the extracted data.
- **Exception workbench:** dequeue a stuck item, see why it's stuck and what auto-fixes were tried, correct the data, and requeue it.
- **Configuration:** poll interval, thresholds and tolerances, retry limits.
- **LLM conversation**, wherever it appears (asking about an item, asking about the flow, and so on), uses the single shared chat component, configured by props: context, system prompt key and available actions.
- **Shared components** live in one place (`web/components/common/` or similar). shadcn primitives live in `components/ui/` and come from `npx shadcn@latest add`. Before you build a component, search for an existing one to configure or extend.

## Repository layout

*Proposed.* Create it in the first BMN run, then update this section to match what was built.

```
api/          Python service (uv project): data/, services/, pipeline/, api/ (routers), integrations/, workers
  alembic/    migrations against ATP
  tests/
web/          Next.js app
infra/        OCI infrastructure as code (Terraform / Resource Manager)
docs/         design notes; BMN writes runs to docs/sprints/bmn-<run-slug>/
```

## Commands

*Proposed defaults.* Nothing is scaffolded yet. Once the first run creates the projects, replace this section with the real commands.

**API (`api/`):** Python 3.12+, `uv`

```bash
uv sync                                   # install
uv run ruff check . && uv run ruff format --check .
uv run pyright                            # type-check (BMN code gate)
uv run pytest                             # full suite
uv run pytest tests/test_matching.py::test_exact_amount   # single test
uv run alembic upgrade head               # apply migrations (DEV schema only)
uv run alembic revision --autogenerate -m "<msg>"
uv run fastapi dev src/<pkg>/main.py      # run the API locally
```

**Web (`web/`):**

```bash
npm install
npx next typegen && npx tsc --noEmit      # type-check (BMN code gate)
npx eslint .                              # lint (BMN code gate)
npx vitest run path/to/file.test.ts -t "name"   # single test
npm run dev
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
- **Stack routing for this repo:** `kind: mixed`.
  - `api/` is `web-app`/`api` + `llm`: the `python-web-app` skills plus `python-llm-features`.
  - `web/` is TypeScript/Next.js: `nextjs-fullstack-standards` plus BMN's Next.js reference.

## Conventions specific to this domain

- **Money is `Decimal` end to end and carries its currency.** Rounding happens once, at a defined point.
- **Every extracted field records** its source (artifact, page and region where possible), the model used and a confidence score.
- **Customer PII and remittance content stay inside OCI.** Raw artifacts, prompts and model output are never logged in full outside the database or Object Storage.
- **Every automated decision is auditable from the item's history**: match, auto-fix and Fusion write. Someone must be able to answer "why did the system apply this receipt to these invoices?".
