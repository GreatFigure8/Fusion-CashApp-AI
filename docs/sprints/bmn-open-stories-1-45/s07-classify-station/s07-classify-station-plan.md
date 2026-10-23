# s07-classify-station: plan

Issue #7. Wave 3. Python only (no web files, no UI; s20 calls the endpoint). Paths: `cashapp/` = `api/src/cashapp/`.

## Standards followed

- CLAUDE.md *Models: who does what*: classification is a **Workhorse** job, `claude-haiku-5-5`, model id/effort/timeout from `config.models().workhorse` (s28 `ModelsConfig`), never hard-coded. Structured output only (`LlmClient.parse(..., ClassificationDecision)`, which s08's `AnthropicLlmClient` sends as `messages.parse` with `output_format`). Zero data retention: the s02 `ModelRole` validator and s08's constructor guard both refuse `fable` ids; this story adds no third guard.
- `claude-api` skill (Haiku 5.5): thinking is never sent as `disabled` and `budget_tokens` is never sent; effort is always set explicitly from config (Haiku 5.5's API default is `medium`; the registry default for the workhorse is `low`); no `tool_choice`/`tools`; no `temperature`; refusal is checked by the client before the parsed output is read (s08 returns `LlmResult(refused=True)`); `max_tokens` leaves room for adaptive thinking (2048, not the 256 "classification" floor, because thinking tokens count against it). No server-side `fallbacks` (s08 assumption: a fallback could leave the fixed role table / ZDR set; Haiku has no server-side fallback anyway).
- `python-llm-features:building-llm-backed-features`: the `ClassificationDecision` field descriptions are prompt surface, so the load-bearing wording (what counts as remittance advice, the 300-char reason, what confidence means) lives in **one** set of constants in `cashapp/domain/classification.py` that both `Field(description=...)` and `prompts.py` import. One shared content limiter (s08 `fit_parts`) — no per-station `[:N]`. Config read through the typed `ModelsConfig`; live calls marked `@pytest.mark.live` (deselected by s01 `addopts`). `confidence` is the model's per-decision value, never a derived number. Model output (the reason) is never logged; it is stored only in the DB (`CLASSIFICATION.REASON`, history reasoning).
- `python-web-app:building-python-web-apps`: router → service → repository. The router validates, authorizes (`require_permission`), opens the UoW, calls the service, commits, maps errors to s01's single `ApiError` shape. The service takes `Principal` as a plain argument and never touches `Request`. Only `data/` imports SQLAlchemy. Mutation is a POST.
- s03: `ClassifyRunner` subclasses the one `StageRunner` and implements only `process`; it returns `Advance`/`Archive` or raises `StageError`; the runner writes the transition, history and next event in one transaction. s02: `record_history` is the only history writer; `emit` is the only event writer. s40: `actor_fields`, `is_lock_live`, `LockConflict`/`ItemBusy`/`ItemNotFound` and `lock_error_to_api` are reused, not redefined (non-negotiable 7).
- research.md a3: exactly the two real `LlmClient` implementations plus s08's replay fake; this story adds no client.
- Coder gates: `uv run ruff check . && uv run ruff format --check .`, `uv run pyright`. Tests written and run only in step 5.

## Files to touch

All new, file-disjoint from other stories (owned: `cashapp/stations/classify/`, `cashapp/api/routers/classification.py`, `cashapp/data/repositories/classification.py`, plus the model, domain, service and schema modules and the one migration below).

| Path | Content |
|---|---|
| `cashapp/domain/classification.py` | `ClassificationOrigin`, `DESC_IS_REMITTANCE`/`DESC_REASON`/`DESC_CONFIDENCE`, `REMITTANCE_DEFINITION`, `REASON_MAX_CHARS = 300`, `CLASSIFICATION_SCHEMA_VERSION = "1"`, `ClassificationDecision` |
| `cashapp/stations/__init__.py` | empty, only if absent (s08 may create it first) |
| `cashapp/stations/classify/__init__.py` | `from .runner import ROLE, ClassifyRunner, build` |
| `cashapp/stations/classify/prompts.py` | `PROMPT_VERSION = "1"`, `CLASSIFY_MAX_TOKENS = 2048`, `CLASSIFY_SYSTEM_PROMPT`, `CLASSIFY_INSTRUCTION`, `build_classify_request(...)` |
| `cashapp/stations/classify/runner.py` | `ClassifyRunner(StageRunner)`, `build(container)`, `ROLE` |
| `cashapp/data/models/classification.py` | ORM `Classification` (table `classification`) — picked up by s02 `load_all_models()` |
| `cashapp/data/repositories/classification.py` | `ClassificationRepository` |
| `cashapp/services/classification.py` | `ClassificationOverrideService`, `OverrideResult`, `InvalidClassificationState`, `ClassificationForbidden` |
| `cashapp/api/schemas/__init__.py` | empty, only if absent (s40 may create it first) |
| `cashapp/api/schemas/classification.py` | `ClassificationOverrideIn`, `ClassificationOut`, `ClassificationOverrideOut`, `classification_error_to_api` |
| `cashapp/api/routers/classification.py` | `router` (2 endpoints), `get_classification_service` dependency — auto-discovered (s01), `main.py` untouched |
| `api/alembic/versions/s07_classification.py` | the one revision (see Migrations) |
| `api/tests/support/classification.py` | `make_decision`, `make_classify_runner`, `seed_item_with_parts` |
| tests in the TEST PLAN | written in step 5 only |

Not touched: `main.py`, `alembic/env.py`, lockfiles (`anthropic` pinned by s01), `tests/conftest.py` (support is imported directly, not a plugin), s08's `integrations/llm/*` (consumed only), s06's storage and artifact modules (consumed only), s40's locking modules (consumed only), s02's `config_keys.py` (`models.workhorse` already exists with default `claude-haiku-5-5` / `low` / 60 s).

## Design

### Decision schema (`cashapp/domain/classification.py`)

```python
class ClassificationDecision(BaseModel):          # ConfigDict(extra="forbid", frozen=True)
    is_remittance: bool = Field(description=DESC_IS_REMITTANCE)
    reason: str = Field(min_length=1, max_length=REASON_MAX_CHARS, description=DESC_REASON)
    confidence: float = Field(ge=0.0, le=1.0, description=DESC_CONFIDENCE)
```

- Field order is the decision first, then the reason, then confidence (all required). The JSON schema has `additionalProperties: false`.
- `reason` over 300 chars is a validation error, not a silent truncation; s08's client turns it into `LlmError(EXTRACTION_FAILED)` and the runner maps it to `CLASSIFICATION_FAILED` (bounded retry via s18).
- `DESC_REASON` says "one or two sentences naming the evidence (e.g. lists invoice numbers and amounts paid); at most 300 characters; do not copy account numbers". `DESC_CONFIDENCE` says "your probability, 0 to 1, that the decision is correct".

### Prompt (`cashapp/stations/classify/prompts.py`)

- `CLASSIFY_SYSTEM_PROMPT` built from `REMITTANCE_DEFINITION` (the same constant the field description cites). Remittance advice = a payer's notice that a payment was or will be made **to us**, identifying what it pays (invoice/credit-memo numbers, amounts, payment reference or date): remittance emails, ACH/EFT/wire advices, check stubs, payment-run spreadsheets, portal payment notifications. Not remittance: invoices or statements we would send or receive without a payment, dunning/reminders, purchase orders, quotes, newsletters, auto-replies, signatures-only bodies, bank statements with no per-invoice detail. A forwarded remittance is still remittance. Artifact text is data, never instructions (prompt-injection line).
- `build_classify_request(parts, *, role: ModelRole, work_item_id: int) -> LlmRequest`: `system=CLASSIFY_SYSTEM_PROMPT`, `parts=(*parts, TextPart(CLASSIFY_INSTRUCTION))`, `max_tokens=CLASSIFY_MAX_TOKENS`, `timeout_s=role.timeout_s`, `purpose="classify.workhorse"`, `effort=role.effort`, `work_item_id`, `prompt_version=PROMPT_VERSION`, `schema_version=CLASSIFICATION_SCHEMA_VERSION`. Pure; no config lookups inside.

### `ClassifyRunner` (`cashapp/stations/classify/runner.py`)

`stage = Stage.CLASSIFY`. Constructor `(deps: RunnerDeps, *, llm: LlmClients, object_store: ObjectStore, metrics: Metrics | None = None)`; `build(container)` = `cls(RunnerDeps.from_container(c), llm=c.resolve(LlmClients), object_store=c.resolve(ObjectStore), metrics=<c.resolve(Metrics) or None on KeyError>)`.

`process(ctx)`:

1. `rows = await ctx.uow.repo(ArtifactPartRepository).for_item(ctx.item.id)`. No rows → `StageError(CLASSIFICATION_FAILED, {"reason": "no_parts"})`. Any `purged_at` → `StageError(CLASSIFICATION_FAILED, {"reason": "artifact_purged"})`.
2. `await ctx.uow.commit()` — ends the read transaction and releases the item row lock so a person's lock/override request is not blocked for up to `timeout_s` while the model runs (s03 allows mid-process commits; the item is re-written by the runner's outcome under `version_id_col`).
3. `content = await load_content_parts([ArtifactPartRef.from_row(r) for r in rows], self.object_store)`; `fitted = fit_parts(content)` (s08's single limiter, default budgets). `fitted.parts` empty → `StageError(CLASSIFICATION_FAILED, {"reason": "nothing_fits", "dropped_part_nos": [...]})`.
4. `models = ctx.config.models()` (per event — AC5); `client = self.llm.with_models(models).workhorse`; `request = build_classify_request(fitted.parts, role=models.workhorse, work_item_id=ctx.item.id)`.
5. Inside `span(llm_span("workhorse"), work_item_id=..., model=client.model_id)`: `result = await asyncio.wait_for(client.parse(request, ClassificationDecision), timeout=models.workhorse.timeout_s)`; set `input_tokens`/`output_tokens`/`latency_ms`; `metrics.llm_call("workhorse", ...)` when present.
6. Error mapping (detail never holds prompt, artifact or output text — only provider, model id, stop reason, `LlmError.detail`):

   | Condition | Raised |
   |---|---|
   | `LlmError(LLM_TRANSIENT)` or `asyncio.TimeoutError` | `StageError(ErrorCode.LLM_TRANSIENT, ...)` |
   | `LlmError(LLM_REFUSAL)` or `result.refused` | `StageError(ErrorCode.LLM_REFUSAL, {"stop_reason": ..., "model_id": ...})` |
   | `LlmError(EXTRACTION_FAILED)` (bad JSON, schema violation, `max_tokens` stop, 4xx) or `result.output is None` | `StageError(ErrorCode.CLASSIFICATION_FAILED, ...)` |
   | `load_content_parts` raises `LlmError` (purged) / `ObjectNotFound` | `StageError(ErrorCode.CLASSIFICATION_FAILED, {"reason": ...})` |

7. Persist in `ctx.uow` (same transaction as the runner's outcome, so the decision and the transition are atomic): `Classification(work_item_id, is_remittance, reason, confidence, model_id=result.usage.model_id or client.model_id, prompt_version=PROMPT_VERSION, origin=MODEL, decided_by=SYSTEM_PRINCIPAL.subject, created_at=ctx.clock.now())`.
8. Outcome:
   - remittance → `Advance(Stage.EXTRACT, note=f"Classified as remittance advice (confidence {c:.2f})", payload={"classification_id", "confidence", "model_id", "prompt_version", "dropped_part_nos"})`.
   - not remittance → `Archive(reason=f"Not remittance advice: {decision.reason}")` (STATE=ARCHIVED, history `reasoning` holds the reason; the item is kept, never dropped). Low-confidence "no" is still archived (story assumption).
9. Logs: `is_remittance`, `confidence`, model id, token counts only.

On any `StageError` the runner rolls back the outcome UoW, so no `CLASSIFICATION` row exists for a failed attempt; s18 handles retry/escalation (`LLM_TRANSIENT` retryable; `LLM_REFUSAL`/`CLASSIFICATION_FAILED` per s18 rules).

`ROLE = RoleSpec("classify", "consumer", build)` where module-level `def build(container: Container) -> Runnable: return StageConsumer(ClassifyRunner.build(container), container.bus, container.settings.streaming.consumer_group)` (identical to `consumer_role(ClassifyRunner, "classify")`, written out so AC6 reads literally). Discovered by s30 under `cashapp.stations`.

### Override service (`cashapp/services/classification.py`)

`ClassificationOverrideService(clock: Clock | None = None).override(uow, item_id, principal, *, is_remittance: bool, reason: str) -> OverrideResult`. Flushes only; the router commits.

1. `principal.can(Permission.CLASSIFICATION_OVERRIDE)` else `ClassificationForbidden` (defence in depth behind the router guard; `SYSTEM_PRINCIPAL` has it but the API never passes it). `reason.strip()` empty → `ValueError` (the router's Pydantic model already rejects it).
2. `item = await uow.work_items.get_for_update(item_id, skip_locked=False)`; `None` → s40 `ItemNotFound(item_id)`.
3. `now = clock.now()`. Live lock (`is_lock_live(item, now)`) owned by someone other than `principal.subject` → s40 `LockConflict(item_id, owner_name, acquired_at)`. The holder of the lock may override (that is the dequeue → fix flow).
4. Live claim (`state == IN_PROGRESS` and `claim_expires_at > now`) → s40 `ItemBusy` (409 `item_busy`; the model is mid-classification).
5. `PIPELINE_ORDER.index(item.stage) > PIPELINE_ORDER.index(Stage.EXTRACT)` → `InvalidClassificationState(item_id, stage, state)` (409 `invalid_state`).
6. Add the HUMAN row: `Classification(origin=HUMAN, is_remittance, reason=reason.strip(), confidence=None, model_id=None, prompt_version=None, decided_by=principal.subject, created_at=now)`.
7. Transition (written with `uow.work_items.update(...)`, `updated_at=now`):

   | Request | Item before | Effect | Event |
   |---|---|---|---|
   | `true` | stage CLASSIFY (any state) or state ARCHIVED (stage ≤ EXTRACT) | `stage=EXTRACT, state=PENDING, attempts=0, last_error_code=None, last_error_detail=None, claim_expires_at=None` | `emit(uow, StageEvent.new(item.id, Stage.EXTRACT, clock=clock), priority=item.priority)` |
   | `true` | stage EXTRACT, not ARCHIVED | none (already on the remittance path) | none |
   | `false` | not ARCHIVED, stage ≤ EXTRACT | `state=ARCHIVED, claim_expires_at=None` (stage kept) | none |
   | `false` | ARCHIVED | none | none |

8. One history row: `HistoryEntry(action=HUMAN_ACTION, **actor_fields(principal), from_stage/to_stage, from_state/to_state, reasoning=reason, payload={"event": "classification_override", "is_remittance": ..., "classification_id": row.id})` via `record_history`. Row, history and outbox event are one transaction (the router's commit).
9. Return `OverrideResult(classification=row, stage=item.stage, state=item.state, emitted=bool)`.

### Router (`cashapp/api/routers/classification.py`)

| Method and path | Permission | Success | Errors |
|---|---|---|---|
| `POST /items/{item_id}/classification/override` body `ClassificationOverrideIn` | `classification:override` | 200 `ClassificationOverrideOut` | 404 `item_not_found`; 409 `lock_conflict` (details `[{owner_name, acquired_at}]`, s40 shape); 409 `item_busy`; 409 `invalid_state` (details `[{"stage", "state"}]`); 403 `forbidden`; 422 `validation_error` (blank/over-long reason) |
| `GET /items/{item_id}/classifications` | `items:read` | 200 `list[ClassificationOut]`, newest first | 404 `item_not_found` |

The router opens `async with uow_factory() as uow` (s04 `UowFactoryDep`), calls the service, commits, maps `LockError` with s40's `lock_error_to_api` and the rest with `classification_error_to_api`. Both operations declare `responses=ERROR_RESPONSES`. The GET is additive (s19/s20 show the archive reason and override trail); recorded under Assumptions.

## Interfaces provided (pinned)

```python
# cashapp/domain/classification.py
CLASSIFICATION_SCHEMA_VERSION: Final = "1"
REASON_MAX_CHARS: Final = 300
REMITTANCE_DEFINITION: Final[str]
DESC_IS_REMITTANCE: Final[str]; DESC_REASON: Final[str]; DESC_CONFIDENCE: Final[str]
class ClassificationOrigin(StrEnum): MODEL = "MODEL"; HUMAN = "HUMAN"
class ClassificationDecision(BaseModel):          # extra="forbid", frozen
    is_remittance: bool
    reason: str                                   # 1..300 chars
    confidence: float                             # 0..1

# cashapp/stations/classify/prompts.py
PROMPT_VERSION: Final = "1"
CLASSIFY_MAX_TOKENS: Final = 2048
CLASSIFY_SYSTEM_PROMPT: Final[str]
CLASSIFY_INSTRUCTION: Final[str]
def build_classify_request(parts: Sequence[ContentPart], *, role: ModelRole, work_item_id: int) -> LlmRequest
    # purpose "classify.workhorse"; effort/timeout from role; prompt_version/schema_version set

# cashapp/stations/classify/runner.py
class ClassifyRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.CLASSIFY
    def __init__(self, deps: RunnerDeps, *, llm: LlmClients, object_store: ObjectStore,
                 metrics: Metrics | None = None) -> None
    @classmethod
    def build(cls, container: Container) -> Self
    async def process(self, ctx: StageContext) -> StageOutcome
def build(container: Container) -> Runnable       # StageConsumer(ClassifyRunner.build(c), c.bus, c.settings.streaming.consumer_group)
ROLE: RoleSpec                                     # RoleSpec("classify", "consumer", build)
```

```python
# cashapp/data/models/classification.py   (table classification → CLASSIFICATION)
class Classification(Base):
    id: Mapped[int]                     # identity PK  PK_CLASSIFICATION
    work_item_id: Mapped[int]           # FK work_item.id  FK_CLASSIFICATION_WI, not null
    is_remittance: Mapped[bool]         # Boolean (create_constraint=False), not null
    reason: Mapped[str]                 # String(1000), not null (model ≤300; human ≤1000)
    confidence: Mapped[float | None]    # Numeric(4, 3, asdecimal=False); None for HUMAN
    model_id: Mapped[str | None]        # String(100); None for HUMAN
    prompt_version: Mapped[str | None]  # String(20); None for HUMAN
    origin: Mapped[ClassificationOrigin]  # StrEnumType, VARCHAR2(40), not null
    decided_by: Mapped[str]             # String(256): Principal.subject ("system:pipeline" for MODEL)
    created_at: Mapped[datetime]        # UtcDateTime, not null

# cashapp/data/repositories/classification.py
class ClassificationRepository(BaseRepository[Classification]):
    model = Classification
    async def latest_for(self, item_id: int) -> Classification | None                     # max created_at, then id
    async def for_item(self, item_id: int) -> list[Classification]                        # newest first (created_at desc, id desc)
    async def latest_for_items(self, item_ids: Sequence[int]) -> dict[int, Classification]  # s19/s20 lists; empty input → no query
```

```python
# cashapp/services/classification.py
class InvalidClassificationState(Exception):
    item_id: int; stage: Stage; state: ItemState
class ClassificationForbidden(Exception):
    item_id: int
@dataclass(frozen=True, slots=True)
class OverrideResult:
    classification: Classification; stage: Stage; state: ItemState; emitted: bool
class ClassificationOverrideService:
    def __init__(self, clock: Clock | None = None) -> None            # None → SystemClock()
    async def override(self, uow: UnitOfWork, item_id: int, principal: Principal, *,
                       is_remittance: bool, reason: str) -> OverrideResult
        # raises s40 ItemNotFound / LockConflict / ItemBusy, InvalidClassificationState, ClassificationForbidden; flush only

# cashapp/api/schemas/classification.py
class ClassificationOverrideIn(BaseModel):
    is_remittance: bool
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
class ClassificationOut(BaseModel):
    id: int; work_item_id: int; is_remittance: bool; reason: str; confidence: float | None
    model_id: str | None; prompt_version: str | None; origin: ClassificationOrigin
    decided_by: str; created_at: datetime
    @classmethod
    def from_row(cls, row: Classification) -> "ClassificationOut"
class ClassificationOverrideOut(BaseModel):
    classification: ClassificationOut; stage: Stage; state: ItemState
def classification_error_to_api(exc: InvalidClassificationState | ClassificationForbidden) -> ApiError
    # InvalidClassificationState → 409 invalid_state, details [{"stage", "state"}]
    # ClassificationForbidden → 403 forbidden, details [{"permission": "classification:override"}]

# cashapp/api/routers/classification.py
router: APIRouter
def get_classification_service() -> ClassificationOverrideService   # tests override (FrozenClock)
```

HTTP contract for s20/s31: the two operations in the Router table above. s31 regenerates its OpenAPI types; no hand-written client here.

```python
# api/tests/support/classification.py
def make_decision(**overrides: Any) -> ClassificationDecision     # default: True, "Lists invoices INV-10001 and INV-10002 with amounts paid.", 0.97
async def seed_item_with_parts(uow: UnitOfWork, store: ObjectStore,
                               parts: Sequence[tuple[PartKind, bytes, str]] = ((PartKind.TEXT, b"<synthetic remittance>", "text/plain"),),
                               **item_overrides: Any) -> WorkItem   # item at CLASSIFY/PENDING + ARTIFACT_PART rows + stored objects; flush
def make_classify_runner(uow_factory: UowFactory, *, workhorse: LlmClient | None = None,
                         object_store: ObjectStore | None = None, config: RuntimeConfig | None = None,
                         clock: Clock | None = None) -> ClassifyRunner
    # s03 make_runner_deps + s08 make_llm_clients(workhorse=...) + LocalFolderObjectStore(tmp) default
```

## Migrations

- One revision `api/alembic/versions/s07_classification.py`, `revision = "s07_classification"`, hand-written. **Expected parent: the head when it merges** — written against s08's `<rev>_s08_extraction_reading` (wave 2's last LLM-table revision; otherwise s06's `s06_artifact_part`). The merger re-points `down_revision` and checks `alembic heads` returns exactly one head.
- Creates `CLASSIFICATION`: `ID NUMBER` identity PK (`PK_CLASSIFICATION`); `WORK_ITEM_ID NUMBER NOT NULL` FK → `WORK_ITEM.ID` (`FK_CLASSIFICATION_WI`); `IS_REMITTANCE` Boolean (SQLAlchemy `Boolean(create_constraint=False)`, `NUMBER(1)`/`SMALLINT` on Oracle) `NOT NULL`; `REASON VARCHAR2(1000) NOT NULL`; `CONFIDENCE NUMBER(4,3) NULL`; `MODEL_ID VARCHAR2(100) NULL`; `PROMPT_VERSION VARCHAR2(20) NULL`; `ORIGIN VARCHAR2(40) NOT NULL` (no CHECK, s02 enum rule); `DECIDED_BY VARCHAR2(256) NOT NULL`; `CREATED_AT TIMESTAMP WITH TIME ZONE NOT NULL`. Index `IX_CLASSIFICATION_ITEM_AT (WORK_ITEM_ID, CREATED_AT)` (also serves the FK).
- Downgrade drops the index and the table. DEV ATP only; no seed rows.

## TEST PLAN (written and run in step 5 only)

SQLite via s02 fixtures (`uow`, `uow_factory`), `FrozenClock`, s03 `run_stage_once`/`drain_outbox`/`FakeContainer`, s08 `scripted_llm`/`ReplayLlmClient`, s06 `LocalFolderObjectStore`, s28 `make_runtime_config`/`InMemoryConfigStore`, s04 `make_principal`/`override_principal`, s40 `lock_item`, s29 `capture_logs`/`capture_spans`.

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `api/tests/unit/domain/test_classification_schema.py::test_decision_fields_and_bounds` | Three required fields; `confidence` -0.01/1.01 rejected; `reason` of 300 chars accepted, 301 and "" rejected; extra key rejected; frozen. |
| 1 | `…::test_json_schema_is_structured_output_shape` | `model_json_schema()` has `additionalProperties: false`, `required == ["is_remittance","reason","confidence"]`, `confidence` is `number`. |
| 1 | `…::test_field_descriptions_come_from_shared_constants` | Each `Field.description` equals its `DESC_*` constant; `CLASSIFY_SYSTEM_PROMPT` contains `REMITTANCE_DEFINITION`. |
| 1 | `api/tests/unit/stations/classify/test_prompts.py::test_prompt_version_pinned` | `PROMPT_VERSION` is a non-empty `str`; `CLASSIFY_MAX_TOKENS >= 1024`. |
| 1 | `…::test_build_classify_request` | `purpose == "classify.workhorse"`, effort/timeout from the given `ModelRole`, `prompt_version`/`schema_version` set, artifact parts in order followed by the instruction `TextPart`, system prompt set. |
| 2 | `api/tests/integration/test_classification_migration_atp.py::test_upgrade_downgrade_atp` (`-m atp`) | `CLASSIFICATION` columns/types/nullability exactly as listed, identity PK, FK, index; downgrade drops; `alembic heads` returns one head. |
| 2 | `api/tests/unit/data/test_classification_model.py::test_orm_columns_match_ac` | ORM table name and the 10 physical columns (upper-cased) match AC2; `ORIGIN` loads as `ClassificationOrigin`. |
| 2 | `api/tests/unit/data/test_classification_repository.py::test_latest_for_for_item_and_latest_for_items` | Newest-first ordering, ties by id; `latest_for` None when empty; `latest_for_items([])` issues no query; repository never commits (second UoW sees nothing). |
| 3 | `api/tests/integration/stations/classify/test_classify_runner.py::test_remittance_advances_to_extract_and_stores_row` | `run_stage_once` → `Advance(EXTRACT)`; item `STAGE=EXTRACT, STATE=PENDING`; one MODEL row with model id, prompt version, confidence, `decided_by="system:pipeline"`; one EXTRACT outbox event; history `STAGE_TRANSITION` with payload `classification_id`. |
| 3 | `…::test_non_remittance_archives_with_reason_in_history` | `Archive`; `STATE=ARCHIVED`; history reasoning contains the model's reason; MODEL row with `is_remittance=False`; no outbox event; item row still present. |
| 3 | `…::test_sends_item_parts_from_object_store_in_part_order` | `ReplayLlmClient.calls[0].parts` = parts loaded from `LocalFolderObjectStore` in `PART_NO` order (TEXT → `TextPart`, PDF → `PdfPart`, IMAGE → `ImagePart`) then the instruction; schema passed is `ClassificationDecision`. |
| 3 | `…::test_refusal_raises_llm_refusal` | `ReplayLlmClient.refusal()` → decision path with `StageError` code `LLM_REFUSAL` recorded as `LAST_ERROR_CODE`; an `LlmError(LLM_REFUSAL)` maps the same. |
| 3 | `…::test_transient_and_timeout_raise_llm_transient` | `transient()` and `timeout()` (role `timeout_s` overridden to 1) → `LAST_ERROR_CODE=LLM_TRANSIENT`. |
| 3 | `…::test_malformed_output_raises_classification_failed` | Scripted output `{"is_remittance": "maybe"}` / over-long reason / `LlmError(EXTRACTION_FAILED)` → `CLASSIFICATION_FAILED`. |
| 3 | `…::test_missing_or_purged_parts_raise_classification_failed` | No `ARTIFACT_PART` rows; a part with `purged_at` set → `CLASSIFICATION_FAILED` with `detail.reason`. |
| 3 | `…::test_failure_leaves_no_classification_row` | After each failure above, `ClassificationRepository.for_item` is empty. |
| 3 | `…::test_redelivered_event_is_noop` | Second `run_stage_once` with the same event → `None` (skipped); one row, one outbox event. |
| 3 | `…::test_no_content_in_logs_or_spans` | Sentinel strings in the artifact and in the model's reason never appear in `capture_logs` or span attributes; span `llm.workhorse` carries model and token attributes. |
| 4 | `api/tests/api/test_classification_router.py::test_override_true_on_archived_item_moves_to_extract_and_emits` | 200; item `EXTRACT/PENDING`, attempts 0, last error cleared; one EXTRACT outbox row; response `stage/state`. |
| 4 | `…::test_override_true_on_classify_stage_item` | CLASSIFY/ESCALATED item → `EXTRACT/PENDING` + event. |
| 4 | `…::test_override_true_at_extract_records_only` | EXTRACT/PENDING item → HUMAN row + history, no stage change, no event. |
| 4 | `…::test_override_false_archives_item` | CLASSIFY/PENDING → `ARCHIVED`, no event; already ARCHIVED → row only. |
| 4 | `…::test_override_writes_human_row_and_history_with_principal` | Row `origin=HUMAN`, `decided_by=subject`, `confidence/model_id/prompt_version` null; one `HUMAN_ACTION` history row with actor USER/subject/display name, reasoning = reason, payload `event`, `classification_id`. |
| 4 | `…::test_override_requires_classification_override_permission` | VIEWER → 403 `forbidden` with details `[{"permission": "classification:override"}]`; nothing written. |
| 4 | `…::test_override_409_lock_conflict_when_another_person_holds_live_lock` | s40 `lock_item` by another subject → 409 `lock_conflict` (details `owner_name`, `acquired_at`); nothing written. |
| 4 | `…::test_override_allowed_for_lock_holder_and_after_lock_expiry` | Own live lock → 200; other's lock after `FrozenClock.advance(minutes=31)` → 200. |
| 4 | `…::test_override_409_invalid_state_past_extract` | Parametrized ADJUDICATE…DONE → 409 `invalid_state` with stage/state details. |
| 4 | `…::test_override_409_item_busy_with_live_claim` | `IN_PROGRESS` with `claim_expires_at > now` → 409 `item_busy`. |
| 4 | `…::test_override_404_unknown_item` | 404 `item_not_found`. |
| 4 | `…::test_override_422_blank_or_long_reason` | `"  "` and 1001 chars → 422. |
| 4 | `…::test_override_is_one_transaction` | Fault injected in `emit` → no HUMAN row, no history, item unchanged. |
| 4 | `…::test_get_classifications_newest_first_and_requires_items_read` | MODEL then HUMAN rows returned HUMAN first; no token → 401. |
| 4 | `…::test_routes_in_openapi` | Both operations and `ClassificationOverrideIn`/`ClassificationOverrideOut`/`ClassificationOut` schemas present. |
| 5 | `api/tests/integration/stations/classify/test_classify_runner.py::test_model_and_effort_read_from_config_per_event` | One runner instance; event 1 with `models.workhorse = haiku/low` → row `MODEL_ID` and request effort match; `InMemoryConfigStore.set("models.workhorse", {...model_id "claude-haiku-5-5-test", effort "medium"...})` (ttl 0); event 2 on a second item uses the new id/effort without rebuilding. |
| 6 | `api/tests/unit/stations/classify/test_role.py::test_role_spec` | `ROLE.name == "classify"`, `ROLE.kind == "consumer"`, `ROLE.build(FakeContainer(...))` returns a `StageConsumer` whose runner is a `ClassifyRunner` built from `container.resolve(LlmClients)` and `container.resolve(ObjectStore)`. |
| 6 | `…::test_role_discovered_by_worker_host` | s30 `discover_roles()` contains `"classify"` mapped to this `ROLE`. |
| live | `api/tests/live/test_classify_live.py::test_haiku_classifies_synthetic_remittance_and_newsletter` (`-m live`) | Skipped without `CASHAPP_ANTHROPIC__API_KEY`; s06 fixtures `remittance_body.eml` text → `is_remittance=True`, `newsletter.eml` → `False`; never run with a placeholder key. |

## Assumptions / deviations

- **Parts are loaded with s08's `load_content_parts` + `fit_parts`** (as s08's plan pins for s07), not s06's `load_item_parts`, so classify and extract send identical `ContentPart`s through one limiter. If the merger consolidates the two loaders, only the import changes.
- **The runner commits `ctx.uow` once before the model call** to release the item row lock during the (up to `timeout_s`) Haiku call, so a person's lock or override is not blocked. The outcome is still written by s03 in one later transaction, guarded by `version_id_col`.
- **Failures store no `CLASSIFICATION` row**; the attempt is recorded by the runner's history row (`LAST_ERROR_CODE`) and s18's `AUTOFIX_ATTEMPT`. Only decisions are rows.
- **`max_tokens = 2048`**, not a classification-sized 256, because Haiku 5.5 runs adaptive thinking (it cannot be turned off at our effort without `disabled`, which we never send) and thinking tokens count against `max_tokens`.
- **Override extras beyond AC4**: 409 `item_busy` while the model holds a live claim (prevents a race with the runner); 404 for an unknown item; `true` on an item already at EXTRACT (not archived) records the row and history but does not re-emit; `false` on an already-archived item records only. The lock holder may override (dequeue → fix → requeue flow).
- **Override transitions are written by the service** with `WorkItemRepository.update` + `record_history` + `emit`, because s03 does not export its outcome writer. If s03 or s18 exposes a shared transition helper, the coder uses it instead (one copy).
- **`GET /items/{id}/classifications`** is added (items:read) so s19/s20 can show the archive reason and override trail without a second classification query path.
- **Human reason up to 1000 chars** (column `VARCHAR2(1000)`); the model's reason stays ≤300 by schema. `CONFIDENCE`, `MODEL_ID`, `PROMPT_VERSION` are nullable because a human decision has none.
- **Schemas live in `cashapp/api/schemas/classification.py`** and the service in `cashapp/services/classification.py` (new files outside the story's three named paths, still file-disjoint), keeping the router thin.
- **No `fallbacks`** on the Haiku call (s08 assumption; Haiku has no server-side fallback).

## Risks

- **Low-confidence "no" archives a real remittance.** Mitigated by the override endpoint and the workbench's archived filter; confidence is stored so s24 can measure a threshold later (a confidence gate would be a config key and a Jonathan decision).
- **Structured-output constraints**: Anthropic structured outputs may not enforce `maxLength`/`minimum`; the SDK's `parse` validates client-side, so a 301-char reason becomes `CLASSIFICATION_FAILED` and costs a retry. The live probe shows how often.
- **Escalated unsupported artifacts** (s06 puts them at CLASSIFY/ESCALATED with no parts): an override to `true` sends them to EXTRACT, which then fails with `EXTRACTION_FAILED`. Acceptable (a person chose it); the workbench should hide the action for `UNSUPPORTED_ARTIFACT` items (s20).
- **Relay wake-up from the API process**: the override's event waits up to s03's `idle_seconds` (10 s) for a worker relay. Bounded crash-recovery wait, not a poller.
- **Parallel-wave contracts**: `RunnerDeps`/`StageConsumer` (s03), `LlmClients.with_models`/`ReplayLlmClient` (s08), `ArtifactPartRepository`/`PartKind` (s06), `lock_error_to_api`/`actor_fields` (s40), `UowFactoryDep` (s04) and `llm_span`/`Metrics.llm_call` (s29) are coded against their pinned plans; the merger reconciles names if code differs.
- **Prompt injection** in artifact text could try to force `is_remittance`. The system prompt treats artifact text as data; the worst case is a misclassification a person can override, and nothing downstream acts on the reason text.
