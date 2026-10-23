# Research synthesis: bmn-open-stories-1-45

Five researchers (reuse/haiku, prior-art/sonnet, primary-docs/sonnet, simplest/fable, risk/opus)
proposed 14 approaches, clustered into 10 canonical ids in `research/clusters.json` and scored by
`bmn-research-score.py` (0.5 merit + 0.3 consensus + 0.2 model agreement). The helper ran cleanly.

## Recommendation

**Winner: a3, the library-composed layered stack with a hand-rolled domain core (score 6.80). Not overridden.**
Three of five researchers reached it on their own. It breaks no hard line: it stays all-OCI,
uses no OIC, keeps one StageRunner, one status enum and one repository base, and puts every
integration behind the CLAUDE.md interfaces.

- **Commodity layers come from libraries:**
  - API and data: SQLAlchemy 2 async on `python-oracledb` (thin mode), Alembic, FastAPI, Pydantic v2, pydantic-settings, sse-starlette.
  - Integrations: aiokafka on the OCI Streaming Kafka endpoint (SASL_SSL/PLAIN); PyJWT `PyJWKClient` for token validation.
  - Models: the `anthropic` SDK (`messages.parse`); the OCI SDK `GenerativeAiInferenceClient` with `DedicatedServingMode`, wrapped in `asyncio.to_thread`.
  - Web: shadcn/ui, Zod and openapi-typescript.
- **Hand-rolled, once:** the generic repository and unit of work, the outbox table and relay (SKIP LOCKED on ATP), the StageRunner, the status, error-code and money modules, the matcher and the auto-fix handlers. No PyPI outbox library fits Oracle (a9). Fusion SOAP fault parsing stays custom and fail-closed.

a3 only chooses the stack, so the build order comes from the runner-up **a1** (6.23). a1 and a3
don't conflict, and the guard rails from **a6** go into the spine. The splitter should follow
this order.

### Build order for the splitter

**Wave 0. The serialized spine: one coder, in order, nothing in parallel.**

1. **#1 Scaffold.** `api/` (uv), `web/` (Next.js, strict + `noUncheckedIndexedAccess`) and the `infra/` skeleton.
   - Pin every known dependency up front in `pyproject.toml`/`uv.lock` and `package.json`/lock, so later waves never edit the lockfiles.
   - Update the Repository layout and Commands sections in CLAUDE.md.
2. **#27 Settings.** One pydantic-settings class. Secrets resolve through a `SecretSource` interface: a Vault implementation and an env/fake implementation.
3. **#2 Data layer and the shared registries.** Each is one module that later stories only append to:
   - `BaseRepository[ModelT]` and the unit of work. Repositories never commit.
   - `status.py`: payment and line statuses, failure precedence and info flags (reference doc §5).
   - `error_codes.py`: the auto-fix codes in CLAUDE.md.
   - `money.py`: Decimal at 2 dp with `ROUND_HALF_UP`, equality as `|a-b| <= 0.005`. Set oracledb `fetch_decimals=True` and `Numeric(asdecimal=True)`, and serialize money as strings in Pydantic and OpenAPI (a6).
   - `config_keys.py`: the registry of runtime-config keys.
   - Router auto-registration: routers are discovered from `api/<pkg>/api/routers/`, so no story edits `main.py`.
   - The Alembic chain: the base revision for work_item, history and outbox.
     - From here on, each story adds exactly one revision on the current head.
     - The merger re-points `down_revision` and checks that `alembic heads` returns exactly one head.
     - Migrations go to DEV ATP only.
4. **#28 Runtime configuration service.** It sits on the config_keys registry.
5. **#26 CI gates.** ruff, pyright, tsc and eslint. GitHub Actions only; nothing deploys.

**Wave 1. Runtime and adapters.** These run in parallel because each story owns a disjoint directory.

- #3 `pipeline/`: StageRunner, the outbox relay, and the EventBus with two implementations, OCI Streaming and in-memory (tests and local only).
- #5 `integrations/fusion/`: the real FusionClient plus a fake built from recorded responses. It also carries the a6 rails:
  - `FUSION_WRITE_ENABLED=false` by default
  - a prod-pod refusal
  - fail-closed SOAP parsing via defusedxml
- #4 `auth/`: JWKS validation, `Principal`, the group-to-role table.
- #40 locks.
- #29 observability. The redaction filter lands before any station logs.
- #30 the worker host.
- #31 `web/lib/api`: the typed client and BFF proxy.
- The `LlmClient` (Anthropic, OCI Cohere and a replay fake) and `ObjectStore` (OCI and a local-folder fake) interfaces land in their own `integrations/` subpackages.

**Wave 2. Stations and screens, one module each.**

- Stations: #6 with #34 (FolderSource real; MailboxSource behind its interface with a fake until #33), #7, #8, #9, #10, #11, #14, #18.
- Screens: #19, #20, #21, #22 (one shared chat component), plus #36 and #37.

**Wave 3. The money path, last and close to serial.**

- #13 Receipt matching: reservation via SKIP LOCKED, with an APPLICATION_LEDGER idempotency table.
- #16 Already-applied fast path.
- #15 Line matching and apply.
- #17 Write-back.
- #38 Reverse an automated application.
- #39 Earned discounts.
- #35 Backlog reprocessing.

Every Fusion write goes through the a6 rails. A story merges only when it passes against the fake. A live non-prod pod is used only when credentials exist.

**Wave 4. Ops and extras.** #23, #32, #24, #41, #42, #45, #43. #25 and #44 are written only as plans and IaC; nothing is applied or deployed.

**Spikes and stories blocked on credentials are planned against fakes.** That covers #12 and #33, the tenant checks in #32 and #39, the source data for #43, the identity-domain claims in #4, and the Cohere dedicated endpoint in #8.
- Every external system has exactly two implementations behind its interface, the real one and the fake. No third variant and no feature flags.
- A fake is never presented as a confirmed contract. Each fake records "unverified against live" until a probe confirms it.

## Scoreboard

| Rank | Id | Approach | Supporters | Models | Merit | Score |
|---|---|---|---|---|---|---|
| 1 | a3 | Library-composed stack, hand-rolled domain core | reuse, prior-art, primary-docs | haiku, sonnet | 8.00 | 6.80 |
| 2 | a1 | Serialized spine, then waves by owned dir, fakes, money last | risk, simplest | opus, fable | 8.07 | 6.23 |
| 3 | a5 | External-truth probes first | primary-docs, simplest | sonnet, fable | 6.11 | 5.26 |
| 4 | a2 | Ledger-first vertical slice | simplest | fable | 8.00 | 5.10 |
| 4 | a6 | Rails-first money and data guards | risk | opus | 8.00 | 5.10 |
| 6 | a4 | DB-authoritative queue, bus as wake-up only | primary-docs | sonnet | 7.00 | 4.60 |
| 7 | a7 | FastStream behind EventBus | prior-art | sonnet | 6.00 | 4.10 |
| 8 | a8 | Temporal instead of outbox and bus | prior-art | sonnet | 4.00 | 3.10 |
| 9 | a9 | PyPI outbox library | reuse | haiku | 3.00 | 2.60 |
| 9 | a10 | Maximum parallelism, one coder per story | risk | opus | 3.00 | 2.60 |

## Dissent

- **simplest (a2)** wants the apply path built early as a thin vertical slice, because the levers on the automation rate (#14, #13, #16) live there. It's kept in part: #16 and #14 come before the UI in waves 2 and 3. Apply itself still goes last, because the money path depends on every registry and every guard rail.
- **primary-docs (a5)** wants live probes first: the identity-domain groups claim and JWKS access, the Cohere dedicated endpoint, Streaming limits, and SKIP LOCKED on ATP. It's adopted as a parallel track that never blocks: each probe confirms or corrects a fake whenever credentials exist.
- **primary-docs (a4)** says Streaming keeps messages for only 24 to 168 hours, so the database must be the real queue. That's already the CLAUDE.md design. Any startup "sweep" counts as crash recovery inside the worker, not as a third poller. If it grows into a periodic loop, that needs Jonathan's ruling.

## Runner-up

**a1** is the build order adopted above. If the stack choice in a3 were rejected, a1 would still
stand, because it is independent of the library picks.

## Rejected

- **a10, maximum parallelism:** with an empty repo, every slice would invent its own status enum, lockfile, `main.py` and Alembic head. CLAUDE.md non-negotiable 7 calls that a defect.
- **a8, Temporal:** contradicts the OCI Streaming, outbox and EventBus mandates, and Temporal isn't an OCI managed service.
- **a9, PyPI outbox libraries:** they are Postgres-oriented or unmaintained, and they would own part of the system of record.
- **a7, FastStream:** an extra framework under a mandated thin EventBus, unverified on OCI Streaming. aiokafka is enough.

## Assumptions

- The researchers wrote from vendor knowledge without live doc fetches. Anything marked VERIFY in `research/primary-docs.json` must be confirmed before code depends on it.
- Where one researcher put the same stack idea in two clusters (reuse's hand-rolled outbox at merit 6), the vote counts once, at the highest merit (8), in a3.
- #25 and #44 are produced only as IaC and plans. Nothing is applied to OCI before Jonathan says "release".
