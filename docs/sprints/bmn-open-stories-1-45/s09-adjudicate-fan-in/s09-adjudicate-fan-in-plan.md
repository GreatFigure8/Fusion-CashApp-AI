# s09-adjudicate-fan-in: plan

Issue #9. Wave 2 (waves.json). Python only, with no web files and no UI. Paths: `cashapp/` means `api/src/cashapp/`.

## Standards followed

- **CLAUDE.md, *Models: who does what*.** The adjudicator is `claude-opus-5-5`. It makes a separate call from Reader A, through `LlmClients.adjudicator`. It **only** compares the two readers' JSON outputs and never receives an artifact part. Its role, model ID, effort and timeout come from `ctx.config.models().adjudicator` on every event.
  - Effort is always sent explicitly, because Opus 5.5 defaults to `medium`.
  - Zero data retention: s02's `ModelRole` validator refuses any Fable ID, and so does s08's `AnthropicLlmClient`. This story adds no third guard.
- **claude-api skill, through s08's `LlmClient`.** Structured output uses `parse(request, AdjudicatorDecision)`, so no free-form text is parsed.
  - The request sends no `tool_choice`, no `tools`, no thinking config, no sampling parameters and no prefill.
  - `refused` is checked before `output` is read.
  - Nothing here touches the SDK directly; s08's client owns all of that.
  - `max_tokens = ADJUDICATE_MAX_TOKENS = 16000`, which stays within the non-streaming limit.
- **python-llm-features.**
  - Every structured-output field description is prompt surface. The load-bearing wording lives in `cashapp/domain/adjudication_text.py`, and both the schema and the prompt import it.
  - The request goes through s08's single limiter, `fit_parts`. If it drops a part, the request is never sent; the runner raises `StageError(EXTRACTION_FAILED)` instead, because a dropped reading must not be passed off as a one-reader decision.
  - `confidence` is the adjudicator's decision confidence, or a derived mean in the one-reader path. The name says what it measures.
  - Live calls carry `@pytest.mark.live`, which the default run deselects.
- **python-web-app.**
  - Layering: the station (business layer) uses repositories through the UoW, and only `data/` imports SQLAlchemy.
  - `save_human_correction` lives in `services/`, so s18 (a service) never imports a station.
  - Pydantic v2 schemas are separate from the ORM model.
- **CLAUDE.md, *Every automated decision is auditable*.** Every value in `final` is traced to A, B, `both` or `human`. Disagreements are stored with both values and a reason, and every row links both raw readings.
  - Nothing ungrounded passes: a final value that neither reader produced raises `UNGROUNDED`, which is always a person (see Design §4).
- **CLAUDE.md conventions.**
  - Money is `MoneyStr`/`Decimal`, compared with `money_eq`.
  - Invoice numbers stay strings.
  - Logs and spans never carry prompt text, reading JSON or output. They carry only IDs, token counts, confidence and counts. The s29 span is `llm.adjudicator`.
- **s03.** `AdjudicateRunner(StageRunner)` implements `process` only. The row is committed mid-process with `ctx.uow.commit()`, which s03 allows, before a `LOW_EXTRACTION_CONFIDENCE`/`UNGROUNDED` `StageError` is raised. The transition commit stays the runner's.

## Files to touch

Every file is new. The set is file-disjoint from other stories. Owned paths: `cashapp/stations/adjudicate/`, `cashapp/data/repositories/adjudication.py`, `cashapp/data/models/adjudication.py`, `cashapp/domain/adjudication.py`, `cashapp/domain/adjudication_text.py`, `cashapp/services/adjudication.py`, and the one migration.

| Path | Content |
|---|---|
| `cashapp/domain/adjudication.py` | `ADJUDICATION_SCHEMA_VERSION`, `Source`, `AdjudicationOrigin`, `FieldChoice`, `LineChoice`, `Disagreement`, `AdjudicatorDecision` (the model-facing schema), `AdjudicationResult` (the AC1 shape), `HEADER_FIELDS`, `single_reader_result(...)`, `check_grounding(...)`, `SINGLE_READER_CONFIDENCE_FACTOR` |
| `cashapp/domain/adjudication_text.py` | Field-description constants shared by the schema and the prompt |
| `cashapp/stations/adjudicate/__init__.py` | Exposes `ROLE` |
| `cashapp/stations/adjudicate/prompts.py` | `PROMPT_VERSION = "1"`, `ADJUDICATE_MAX_TOKENS`, `ADJUDICATOR_SYSTEM_PROMPT`, `build_adjudicator_request(...)` |
| `cashapp/stations/adjudicate/runner.py` | `AdjudicateRunner`, `build`, `ROLE` |
| `cashapp/data/models/adjudication.py` | ORM `Adjudication` (`load_all_models()` discovers it, so `models/__init__.py` is not edited) |
| `cashapp/data/repositories/adjudication.py` | `AdjudicationRepository` |
| `cashapp/services/adjudication.py` | `save_human_correction(...)` |
| `api/alembic/versions/<rev>_s09_adjudication.py` | The one revision (see Migrations) |
| `api/tests/support/adjudication.py` | `make_adjudicator_decision(a, b, **overrides)`, `seed_readings(uow, item_id, a=..., b=...)` |
| `api/tests/fixtures/llm/adjudicate_synthetic.json` | A recorded `AdjudicatorDecision` over s08's synthetic A/B readings, marked "unverified against live" |
| Tests in the TEST PLAN | Written in step 5 only |

Not touched: `main.py`, the lockfiles, `tests/conftest.py`, s08's `integrations/llm/*`, `extraction.py` and `readings.py` (consumed only), s02's `config_keys.py`, and `models/__init__.py`.

## Design

### 1. Schemas (`cashapp/domain/adjudication.py`)

- `Source = Literal["A", "B", "both", "human"]`. The model may emit only `A`, `B` or `both`. `human` is code-only and comes from `save_human_correction`. The design.md tag "A+B" renders `both`.
- **Model-facing `AdjudicatorDecision`** (`extra="forbid"`). Provenance uses lists, not dicts, because structured outputs require `additionalProperties: false` on every object and `dict[str, Literal]` cannot meet that.
  - `final: RemittanceExtraction`
  - `field_choices: list[FieldChoice{field_path: str, source: Literal["A","B","both"]}]`
  - `line_choices: list[LineChoice{line_no: int, source: Literal["A","B","both"]}]`
  - `disagreements: list[Disagreement{field_path, value_a: str|None, value_b: str|None, chosen: Literal["A","B","both"], reason: str (<= 300)}]`. Values are JSON-rendered strings, so they have one type across fields.
  - `confidence: float (0..1)`
- **`AdjudicationResult`** has the AC1 shape and is what gets stored:
  - `final: RemittanceExtraction`
  - `provenance: dict[str, Source]`
  - `line_provenance: list[LineProvenance{line_no, source}]`
  - `disagreements: list[Disagreement]`, with `chosen: Source`
  - `confidence: float 0..1`
  - It is built by `AdjudicationResult.from_decision(decision)`.
- **`HEADER_FIELDS`** is the tuple of `RemittanceExtraction` field names other than `lines`. It is derived from `model_fields`, so it never drifts. Field paths use the same keys as s08's `field_confidences()`: top-level names, plus `lines[i]` for lines, keyed by `line_no` in `line_provenance`.
- **`single_reader_result(reading: RemittanceExtraction, slot: ReaderSlot) -> AdjudicationResult`.** Every header field and every line comes from `slot`. There are no disagreements. Confidence is `round(mean(field_confidences().values()) * SINGLE_READER_CONFIDENCE_FACTOR, 4)`, where `SINGLE_READER_CONFIDENCE_FACTOR: Final = 0.8`. An empty confidence map gives 0.0.

### 2. Prompt (`stations/adjudicate/prompts.py`)

- **System prompt:** "You compare two independent readings of one remittance. You never see the document." For each header field and each line: take A, take B, or combine (for lines, the union of distinct lines; for a scalar field, the value both readers agree on). Never write a value that neither reader produced. Record every field where they differ, with a short reason. Give a confidence for the decision as a whole.
- **`build_adjudicator_request(a: RemittanceExtraction, b: RemittanceExtraction, *, role: ModelRole, work_item_id: int) -> LlmRequest`** builds:
  - `parts = (TextPart("READING A (schema RemittanceExtraction@1):\n" + a.model_dump_json()), TextPart("READING B ...:\n" + b.model_dump_json()))`
  - `purpose="adjudicate.adjudicator"`, `effort=role.effort`, `timeout_s=role.timeout_s`, `max_tokens=ADJUDICATE_MAX_TOKENS`
  - `prompt_version=PROMPT_VERSION`, `schema_version=ADJUDICATION_SCHEMA_VERSION`, `work_item_id`

  Only `TextPart`s are sent, never artifact bytes.

### 3. `AdjudicateRunner` (stage `ADJUDICATE`)

1. `__init__(deps: RunnerDeps, *, llm: LlmClients)`. `build(container)` returns `cls(RunnerDeps.from_container(c), llm=c.resolve(LlmClients))`, wrapped by s03's `consumer_role`. `ROLE = RoleSpec("adjudicate", "consumer", build)`.
2. `readings = await ctx.uow.repo(ExtractionReadingRepository).latest_for(item.id)`. For each slot, the reading counts as usable when its status is `OK` and `RemittanceExtraction.model_validate(row.output)` succeeds. A validation failure is treated as a missing reader, noted as `"invalid_output"`.
3. **Neither usable:** raise `StageError(EXTRACTION_FAILED, detail={"A": status|"absent", "B": ...})`.
4. **Exactly one usable:** no LLM call. The result is `single_reader_result(...)`, with `MISSING_READER` set to the other slot, `MODEL_ID = None`, and `PROMPT_VERSION = "single-reader"`.
5. **Both usable:**
   1. `role = ctx.config.models().adjudicator`.
   2. `client = self.llm.with_models(ctx.config.models()).adjudicator`.
   3. Build the request and pass it through `fit_parts`. If it dropped anything, raise `StageError(EXTRACTION_FAILED, {"reason": "adjudication_input_too_large"})`.
   4. Inside `span("llm.adjudicator", work_item_id=..., model=...)`, call `await client.parse(request, AdjudicatorDecision)`.
   5. Error mapping:
      - `result.refused` raises `StageError(LLM_REFUSAL)`.
      - `LlmError` raises `StageError(err.error_code)`, which is `LLM_TRANSIENT` or `EXTRACTION_FAILED`.
      - This mirrors s07.
   6. The decision becomes `AdjudicationResult.from_decision`.
6. **Grounding check (§4)** runs on the both-readers path.
7. **Store** one MODEL row through `AdjudicationRepository.add`:
   - `READING_A_ID` and `READING_B_ID` are the latest reading IDs, including a failed reader's row ID when one exists.
   - Also stored: model ID, prompt and schema versions, `MISSING_READER`, `FINAL`, `PROVENANCE` (`{"fields": {...}, "lines": [...]}`), `DISAGREEMENTS`, `CONFIDENCE`.
   - Then `await ctx.uow.commit()`.
8. **Gates, in order:**
   1. Grounding violations raise `StageError(UNGROUNDED, detail={"adjudication_id", "paths": [...]})`.
   2. `confidence < ctx.config.escalation().min_extraction_confidence` raises `StageError(LOW_EXTRACTION_CONFIDENCE, detail={"adjudication_id", "confidence", "threshold", "missing_reader"})`.
   3. Otherwise return `Advance(Stage.VALIDATE, note="adjudicated: A+B" | "single reader A", payload={"adjudication_id", "confidence", "missing_reader", "disagreements": n})`.

No transaction is held across the LLM call beyond s03's claim: the readings are read in `ctx.uow` before the call, and the row is written after it.

### 4. Grounding check (deterministic, code-only)

`check_grounding(result, a, b) -> list[str]` returns the violating field paths.

- **Header fields:**
  - `final.<f>.value` must equal A's value when the source is `A`, B's when it is `B`, and either reader's when it is `both`.
  - Money is compared with `money_eq`, and lists are compared as equal sets.
  - The confidence and source location of an `Extracted` are not compared.
- **Lines:** each final line must match a line from its claimed reader on (`kind`, `transaction_number`, `amount_paid` via `money_eq`, or both None). `both` means it matches a line in A or in B.
- **Completeness:** every header field has a provenance entry and every final `line_no` has a `line_choice`. A missing entry is a violation, so the auditability trail cannot have holes.

Violations raise `UNGROUNDED`, which is always a person under CLAUDE.md: anything ungrounded in the remittance. The row is still stored first, so the person sees what the adjudicator proposed.

### 5. `latest_for` and human corrections

- **`AdjudicationRepository.latest_for(item_id)`** returns the newest row by (`CREATED_AT` desc, `ID` desc), whatever its origin.
  - A HUMAN row written after the MODEL rows supersedes them.
  - A later MODEL row, after a requeue to EXTRACT, supersedes an older human edit. That is the person's explicit choice.
  - This is the single "current extraction" accessor for s10, s11, s13, s15, s16, s20 and s24.
- **`save_human_correction(uow, item_id, final, principal, *, clock=None) -> Adjudication`:**
  1. Insert an `ORIGIN=HUMAN` row: provenance `"human"` for every header field and line, `EDITED_BY = principal.subject`, confidence 1.0, `MODEL_ID/PROMPT_VERSION = None`, `SCHEMA_VERSION` set.
  2. `READING_A_ID/B_ID` are copied from the previous `latest_for` row when there is one.
  3. Write a `HUMAN_ACTION` history row through s02's `record_history`, with `ActorKind.USER`, `actor_id = principal.subject`, `actor_name = principal.display_name`, and `payload {"adjudication_id", "changed_fields": [...]}`. The changed fields are a diff against the previous final; paths only, no values.
  4. Flush only. It never commits; s18 owns the transaction.
  5. `principal.is_system` raises `ValueError`, because a human correction needs a human.

## Interfaces provided (pinned)

```python
# cashapp/domain/adjudication.py
ADJUDICATION_SCHEMA_VERSION: Final = "1"
SINGLE_READER_CONFIDENCE_FACTOR: Final = 0.8
Source = Literal["A", "B", "both", "human"]
ModelSource = Literal["A", "B", "both"]
class AdjudicationOrigin(StrEnum): MODEL = "MODEL"; HUMAN = "HUMAN"
HEADER_FIELDS: Final[tuple[str, ...]]            # RemittanceExtraction.model_fields minus "lines"
class FieldChoice(BaseModel): field_path: str; source: ModelSource
class LineChoice(BaseModel): line_no: int; source: ModelSource
class LineProvenance(BaseModel): line_no: int; source: Source
class Disagreement(BaseModel):
    field_path: str; value_a: str | None; value_b: str | None; chosen: Source; reason: str   # reason <= 300
class AdjudicatorDecision(BaseModel):            # sent as the structured-output schema; extra="forbid"
    final: RemittanceExtraction; field_choices: list[FieldChoice]; line_choices: list[LineChoice]
    disagreements: list[Disagreement]; confidence: float   # 0..1
class AdjudicationResult(BaseModel):             # AC1 shape
    final: RemittanceExtraction
    provenance: dict[str, Source]                # header field path -> source
    line_provenance: list[LineProvenance]
    disagreements: list[Disagreement]
    confidence: float                            # 0..1
    @classmethod
    def from_decision(cls, d: AdjudicatorDecision) -> "AdjudicationResult"
    def provenance_json(self) -> dict[str, Any]  # {"fields": {...}, "lines": [{line_no, source}]} (stored PROVENANCE)
def single_reader_result(reading: RemittanceExtraction, slot: ReaderSlot) -> AdjudicationResult
def human_result(final: RemittanceExtraction) -> AdjudicationResult        # all "human", confidence 1.0
def check_grounding(result: AdjudicationResult, a: RemittanceExtraction, b: RemittanceExtraction) -> list[str]
```

```python
# cashapp/data/models/adjudication.py   (table adjudication -> ADJUDICATION)
class Adjudication(Base):
    id: int (identity PK); work_item_id: int (FK work_item.id, FK_ADJUDICATION_WI)
    origin: AdjudicationOrigin; model_id: str | None (String(100)); prompt_version: str | None (String(20))
    schema_version: str (String(20)); reading_a_id: int | None (FK extraction_reading.id); reading_b_id: int | None (FK)
    missing_reader: ReaderSlot | None; final: dict | None (JsonDoc); provenance: dict (JsonDoc, not null)
    disagreements: list | None (JsonDoc); confidence: Decimal (Numeric(5,4)) ; edited_by: str | None (String(255))
    created_at: datetime (UtcDateTime, default utcnow); purged_at: datetime | None
    def result(self) -> AdjudicationResult        # raises AdjudicationPurged when final is None
class AdjudicationPurged(Exception): adjudication_id: int

# cashapp/data/repositories/adjudication.py
class AdjudicationRepository(BaseRepository[Adjudication]):
    async def latest_for(self, item_id: int) -> Adjudication | None       # newest by (created_at, id)
    async def for_item(self, item_id: int) -> list[Adjudication]          # oldest first; s19/s20 history views
    async def purge_payloads(self, item_ids: Sequence[int], *, at: datetime) -> int
        # s45: FINAL=NULL, DISAGREEMENTS=NULL, PURGED_AT=at; keeps PROVENANCE, CONFIDENCE, versions
```

```python
# cashapp/services/adjudication.py
async def save_human_correction(uow: UnitOfWork, item_id: int, final: RemittanceExtraction,
                                principal: Principal, *, clock: Clock | None = None) -> Adjudication
    # ORIGIN=HUMAN, provenance all "human", EDITED_BY=principal.subject, HUMAN_ACTION history row; flush, never commit

# cashapp/stations/adjudicate/prompts.py
PROMPT_VERSION: Final = "1"
SINGLE_READER_PROMPT_VERSION: Final = "single-reader"
ADJUDICATE_MAX_TOKENS: Final = 16000
ADJUDICATOR_SYSTEM_PROMPT: Final[str]
def build_adjudicator_request(a: RemittanceExtraction, b: RemittanceExtraction, *, role: ModelRole,
                              work_item_id: int) -> LlmRequest

# cashapp/stations/adjudicate/runner.py
class AdjudicateRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.ADJUDICATE
    def __init__(self, deps: RunnerDeps, *, llm: LlmClients) -> None
    async def process(self, ctx: StageContext) -> StageOutcome
def build(container: Container) -> Runnable
ROLE: RoleSpec   # RoleSpec("adjudicate", "consumer", build)

# api/tests/support/adjudication.py
def make_adjudicator_decision(a: RemittanceExtraction, b: RemittanceExtraction | None = None, **overrides: Any) -> AdjudicatorDecision
    # default: final=a, every field/line source "A" ("both" where A==B), no disagreements, confidence 0.95
async def seed_readings(uow: UnitOfWork, item_id: int, *, a: RemittanceExtraction | ReadingStatus | None,
                        b: RemittanceExtraction | ReadingStatus | None, attempt: int = 1) -> dict[ReaderSlot, ExtractionReading]
```

Consumers: s10 (`latest_for(...).result().final`), s18 (`save_human_correction`), s20 (via API views: `result()`, `missing_reader`, `READING_*_ID`), s24 (`AdjudicateRunner` with `ReplayLlmClient`), s45 (`purge_payloads`), and s36 (`purpose="adjudicate.adjudicator"`).

## Migrations

- There is one hand-written revision, `api/alembic/versions/<rev>_s09_adjudication.py`. Its expected parent is s08's `<rev>_s08_extraction_reading` revision, because `ADJUDICATION` has foreign keys into `EXTRACTION_READING`. The merger re-points `down_revision` onto the current head and checks that `alembic heads` returns exactly one head.
- It creates the table `ADJUDICATION`:

  | Column | Type |
  |---|---|
  | `ID` | Identity PK |
  | `WORK_ITEM_ID` | `NUMBER NOT NULL`, FK `FK_ADJUDICATION_WI` → `WORK_ITEM.ID` |
  | `ORIGIN` | `VARCHAR2(40) NOT NULL` |
  | `MODEL_ID` | `VARCHAR2(100) NULL` |
  | `PROMPT_VERSION` | `VARCHAR2(20) NULL` |
  | `SCHEMA_VERSION` | `VARCHAR2(20) NOT NULL` |
  | `READING_A_ID`, `READING_B_ID` | `NUMBER NULL`, FKs `FK_ADJUDICATION_RA`/`FK_ADJUDICATION_RB` → `EXTRACTION_READING.ID` |
  | `MISSING_READER` | `VARCHAR2(40) NULL` |
  | `FINAL` | `JSON NULL` |
  | `PROVENANCE` | `JSON NOT NULL` |
  | `DISAGREEMENTS` | `JSON NULL` |
  | `CONFIDENCE` | `NUMBER(5,4) NOT NULL` |
  | `EDITED_BY` | `VARCHAR2(255) NULL` |
  | `CREATED_AT` | `TIMESTAMP WITH TIME ZONE NOT NULL` |
  | `PURGED_AT` | `TIMESTAMP WITH TIME ZONE NULL` |

- It adds the index `IX_ADJUDICATION_ITEM` on (`WORK_ITEM_ID`, `CREATED_AT`). There are no CHECK constraints, per s02's enum rule. JSON uses s02's `JsonDoc`.
  - `FINAL` is nullable so s45 can purge it. Code always writes it.
- Downgrade drops the index and then the table. Applied to DEV ATP only.

## TEST PLAN (written and run in step 5 only)

All tests run on aiosqlite and `ReplayLlmClient` unless they are marked otherwise.

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `tests/domain/test_adjudication_schema.py::test_adjudication_result_shape` | Fields `final`, `provenance: dict[str, Source]`, `line_provenance[{line_no, source}]`, `disagreements[{field_path, value_a, value_b, chosen, reason}]`, `confidence`. `confidence` outside 0..1 is rejected. `reason` over 300 characters is rejected. |
| 1 | `…::test_from_decision_builds_dict_provenance` | List choices become a dict keyed by `HEADER_FIELDS`, and line choices become `line_provenance`. |
| 1 | `…::test_decision_schema_structured_output_shape` | Every object in `AdjudicatorDecision.model_json_schema()` has `additionalProperties: false`. No `human` value is in the model-facing enum. |
| 1 | `…::test_field_descriptions_from_shared_constants` | Every `Field(description=...)` equals a constant in `adjudication_text.py`. `PROMPT_VERSION` is non-empty. |
| 1 | `…::test_check_grounding` | A value from the claimed reader passes. A value from the other reader under source `A` is flagged. A value from neither reader is flagged. A `both` line in the union passes. A missing provenance entry is flagged. Money is compared with `money_eq`. |
| 1 | `…::test_single_reader_result_confidence` | Mean field confidence × 0.8, with every source equal to the slot. An empty map gives 0.0. |
| 2 | `tests/integration/test_adjudication_migration_atp.py::test_upgrade_downgrade_atp` (`-m atp`) | Columns exactly as listed, native JSON, identity PK, the three FKs and the index. Downgrade drops them. `alembic heads` is one head. |
| 2 | `tests/data/test_adjudication_repository.py::test_latest_for_newest_wins_human_supersedes` | No rows gives None. With MODEL(t1) then HUMAN(t2), `latest_for` returns HUMAN. A later MODEL(t3) wins over it. A tie on `created_at` resolves to the max ID. |
| 2 | `…::test_purge_payloads_keeps_provenance` | `FINAL` and `DISAGREEMENTS` are nulled and `PURGED_AT` is set. `PROVENANCE`, `CONFIDENCE` and versions are kept. `result()` raises `AdjudicationPurged`. |
| 3 | `tests/stations/adjudicate/test_adjudicate_runner.py::test_both_ok_one_adjudicator_call_text_only` | Exactly one `adjudicator` call and zero calls on `reader_a`/`reader_b`/`workhorse`. Every request part is a `TextPart` containing both readings' JSON, with no `ImagePart`/`PdfPart` and no artifact sentinel bytes. `purpose == "adjudicate.adjudicator"`. |
| 3 | `…::test_uses_latest_reading_per_reader_by_attempt` | A FAILED at attempt 1 and OK at attempt 2, with B OK: both are used. The request contains A's attempt-2 output, and `READING_A_ID` is the attempt-2 ID. |
| 3 | `…::test_one_reader_ok_no_llm_call` | B is TIMEOUT. No adjudicator call is made. `final == A`, every provenance entry is "A", `MISSING_READER == "B"`, and confidence equals A's mean × 0.8. Covered for both slots (parametrized). |
| 3 | `…::test_both_failed_raises_extraction_failed` | Both FAILED, or no readings at all, raises `StageError(EXTRACTION_FAILED)` with per-reader detail. No row is written. |
| 3 | `…::test_ok_reading_with_invalid_output_treated_missing` | A corrupt `OUTPUT` on an OK row falls to the single-reader path from B. |
| 4 | `…::test_row_links_readings_and_versions_then_advances` | The row has `READING_A_ID`/`READING_B_ID`, `MODEL_ID`, `PROMPT_VERSION == "1"`, `SCHEMA_VERSION`, `ORIGIN=MODEL`, and the stored provenance and disagreements. The outcome is `Advance(VALIDATE)` with `adjudication_id` in the payload. |
| 4 | `…::test_low_confidence_raises_after_row_committed` | With the threshold overridden to 0.9 and confidence 0.5, it raises `StageError(LOW_EXTRACTION_CONFIDENCE)`, and the row is visible from a separate UoW. |
| 4 | `…::test_ungrounded_value_raises_after_row_committed` | A decision whose final payer is in neither reading raises `StageError(UNGROUNDED)` with paths, and the row is stored. |
| 5 | `…::test_refusal_and_transient_mapping` | A refusal step raises `StageError(LLM_REFUSAL)`. A transient step raises `LLM_TRANSIENT`. An `EXTRACTION_FAILED` `LlmError` raises `EXTRACTION_FAILED`. No row is written in any of these cases. |
| 5 | `…::test_effort_and_model_from_config_per_event` | The default config sends `effort == "medium"` and model `claude-opus-5-5`. Overriding `models.adjudicator` to effort "high" with a different model ID changes the next request without rebuilding the runner. |
| 5 | `…::test_oversized_input_never_sent` | When `fit_parts` drops a part (via monkeypatched limits), it raises `StageError(EXTRACTION_FAILED)` and makes no LLM call. |
| 5 | `…::test_no_content_in_logs_or_spans` | Sentinel strings from the readings never appear in `caplog` or in span attributes. The `llm.adjudicator` span carries token counts. |
| 6 | `tests/services/test_adjudication_service.py::test_save_human_correction` | Creates an `ORIGIN=HUMAN` row with all provenance "human", `EDITED_BY = principal.subject` and the readings copied from the previous row. Writes a `HUMAN_ACTION` history row with `changed_fields` paths and no values. `latest_for` returns it. Nothing is committed: a rollback leaves no row. |
| 6 | `…::test_save_human_correction_refuses_system_principal` | `SYSTEM_PRINCIPAL` raises `ValueError`. |
| 7 | `tests/stations/adjudicate/test_role.py::test_role_spec` | `ROLE.name == "adjudicate"` and `kind == "consumer"`. `build(FakeContainer)` resolves `LlmClients` and returns a `Runnable`. |
| live | `tests/live/test_adjudicator_live.py::test_opus_adjudicator_live` (`-m live`) | Skipped without `CASHAPP_ANTHROPIC__API_KEY`. One call on s08's synthetic A/B fixtures returns a valid `AdjudicatorDecision` that passes `check_grounding`. |

## Assumptions / deviations

- **No LLM call when exactly one reader is usable.** This is the story's assumption. `MODEL_ID` is null and `PROMPT_VERSION` is `"single-reader"`.
- **The ×0.8 factor is a module constant (`SINGLE_READER_CONFIDENCE_FACTOR`), not a config key.** Adding a key would edit s02's registry file. A later story can promote it.
- **Provenance is emitted by the model as lists** (`field_choices`/`line_choices`) and converted to the AC1 dict in code, because structured outputs need `additionalProperties: false`. The stored `PROVENANCE` is `{"fields": {...}, "lines": [...]}`, so one JSON column holds both the AC1 `provenance` and `line_provenance`.
- **The grounding check plus `UNGROUNDED` is added beyond the AC.** CLAUDE.md requires every value to be traceable to a reader and sends anything ungrounded to a person. It is code-only, so it adds no model cost.
- **`latest_for` is newest by (`CREATED_AT`, `ID`) regardless of origin.** This is how "HUMAN supersedes MODEL by CREATED_AT" is read. A model row produced after a human requeue to EXTRACT supersedes the earlier human edit, which is intended.
- **`save_human_correction` lives in `cashapp/services/adjudication.py`, not the station.** That way s18 (a service) doesn't import from `stations/`. Its signature matches AC6, plus an optional `clock`. It writes `HUMAN_ACTION` history itself. s18 also writes its own requeue history row, so the merger should make sure the two are not duplicated in purpose: this row says "extraction corrected" and s18's says "requeued".
- **`CONFIDENCE` is `NUMBER(5,4)`**, which holds 0.0000–1.0000. Human rows store 1.0.
- **`READING_*_ID` point at the latest reading per slot, even a failed one,** so the audit shows what was missing and why. They are null only when there is no reading for that slot.
- **The adjudicator effort comes only from config (AC5).** `fix_hints["effort"]` is applied by s08 to the readers, not here. The `LOW_EXTRACTION_CONFIDENCE` fix re-runs the readers and then comes back through this station.
- **Runner constructor:** this plan follows s03's pinned `__init__(deps: RunnerDeps)` plus `build` override style, `llm=c.resolve(LlmClients)`. s08's kwargs differ, and the merger reconciles them.

## Risks

- **Structured-output schema size.** `AdjudicatorDecision` embeds the full `RemittanceExtraction` (the generic `Extracted[T]` `$defs`), which is the same risk s08 carries. The SDK strips unsupported constraints, and the live probe confirms the schema is accepted.
- **False `UNGROUNDED` on legitimate normalisation.** The adjudicator may, for example, trim whitespace or upper-case a currency. Mitigation: before comparing, strings are compared after `strip()`, and currency is upper-cased. Anything more is a prompt fix tracked in s24's eval, not a looser check.
- **Cost:** a second Opus call per two-reader item. The default effort is `medium` (config), and s36 meters it.
- **Same-wave dependencies:** s08's `latest_for` returns a `dict[ReaderSlot, ExtractionReading]`, and the names of `fit_parts`, `with_models` and `span` come from pinned plans. s18 consumes `save_human_correction` in the same wave. The merger reconciles imports, and no local stand-ins are created.
- **Stale `FIX_HINTS`** (s08's risk) don't affect this station, which ignores them.
