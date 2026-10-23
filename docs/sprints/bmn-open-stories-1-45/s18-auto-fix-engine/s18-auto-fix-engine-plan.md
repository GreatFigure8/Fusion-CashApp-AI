# Plan: s18-auto-fix-engine

Issue #18. Wave 3 (parallel with s07, s09, s10, s37, s11, s14, s36). Python only: no web files, no migration. Paths: `cashapp/` = `api/src/cashapp/`.

## Standards followed

- CLAUDE.md *Self-healing*:
  - every failure is a typed `ErrorCode`
  - each handler is bounded by configuration
  - every attempt is recorded with its reasoning
  - only transient failures are retried
  - always-person codes escalate
  - human requeue reuses the same `StageRunner`, with no manual path
  - a locked item is never acted on
- CLAUDE.md *Layering*:
  - The router (transmission) validates, authorizes, commits and maps errors.
  - Services (`services/autofix/`) hold the rules. They take `Principal` as a plain argument and never touch `Request`.
  - The only new query lives in a repository that subclasses `BaseRepository`. It flushes and never commits.
  - No `sqlalchemy` import outside `cashapp/data/` (s02 layering test).
- CLAUDE.md *Models*: the workhorse (`config.models().workhorse`, Haiku 5.5) writes escalation summaries through s08's `LlmClient.parse` with structured output.
  - Effort is set explicitly from the role, because Haiku 5.5 defaults to `medium`.
  - Refusal arrives as `LlmResult.refused`.
  - Zero data retention: the model ID comes from config, which s02/s28 already guard against `fable`.
- `python-llm-features:building-llm-backed-features`:
  - The prompt text and the summary field description sit in one constants module (`prompts.py`), because the field description is prompt surface too.
  - The input is a bounded facts block. It never contains artifact text.
  - Live-model tests are marked `live`. The default suite uses `ReplayLlmClient`.
  - On failure the reasoner falls back to a template and never returns a normal-looking result.
- `python-web-app:building-python-web-apps`:
  - logic in services
  - `Annotated` dependencies
  - mutations through POST only
  - one error shape (s01 `ApiError`)
  - router auto-discovery, so `main.py` isn't edited
- s03 rules:
  - Handlers may set `item.fix_hints`, `item.awaiting_since` and `item.escalation_summary`, and write history on the given UoW. They never commit.
  - The runner owns the state change and the `STAGE_TRANSITION` row.
  - Outbox writes go only through `emit` / `enqueue`.
- s40 rules:
  - The engine checks `is_locked_for_automation(item, now)`.
  - Requeue calls `LockService.assert_held_by` and then `release(..., redrive=False)` in the same transaction, and emits its own event.
- DRY (non-negotiable 7):
  - `NotifyEvent` is defined once (s14, s36, s38 and s42 import it).
  - `escalate()` is defined once (s14, s38).
  - `policy_check()` is defined once (s10, s13).
  - The attempt counting rule is defined once (`attempts.py`; s20 imports `attempt_summary`).

## Files to touch

New (owned by this story):

| Path | Content |
|---|---|
| `cashapp/domain/notifications.py` | `NotifyKind`, `NotifySeverity`, `NotifyEvent`, `NOTIFY_TOPIC_NAME` (pure: no pipeline imports) |
| `cashapp/services/notify.py` | `notify_topic`, `emit_notify` (the one outbox writer for `NotifyEvent`; s36/s42 use it) |
| `cashapp/services/autofix/__init__.py` | empty |
| `cashapp/services/autofix/engine.py` | `FixContext`, `FixHandler`, `AutoFixEngine`, `default_registry`, `build_failure_handler` |
| `cashapp/services/autofix/attempts.py` | `AttemptRecord`, `AttemptSummary`, `load_attempts`, `attempt_summary`, `NOOP_LOCKED` |
| `cashapp/services/autofix/hints.py` | `replace_fix_hints`, `bump_effort`, `failed_readers` |
| `cashapp/services/autofix/reasoner.py` | `Reasoner` Protocol, `EscalationSummary`, `LlmReasoner`, `TemplateReasoner`, `template_summary`, `limit_sentences` |
| `cashapp/services/autofix/prompts.py` | `PROMPT_VERSION`, `SUMMARY_SYSTEM_PROMPT`, `DESC_SUMMARY`, `SUMMARY_MAX_TOKENS`, `SUMMARY_TIMEOUT_CAP_S` |
| `cashapp/services/autofix/escalation.py` | `escalate`, `announce_escalation` |
| `cashapp/services/autofix/policy.py` | `PolicyFindings`, `policy_findings`, `policy_check`, `PREPAYMENT_MARKERS` |
| `cashapp/services/autofix/diff.py` | `FieldChange`, `extraction_diff` |
| `cashapp/services/autofix/requeue.py` | `RequeueCommand`, `RequeueResult`, `RequeueError` hierarchy, `RequeueService` |
| `cashapp/services/autofix/handlers/__init__.py` | empty |
| `cashapp/services/autofix/handlers/receipt_not_yet_available.py` | `ParkAwaitingReceiptHandler` |
| `cashapp/services/autofix/handlers/receipt_ambiguous.py` | `NarrowReceiptHandler` |
| `cashapp/services/autofix/handlers/reextract.py` | `ReExtractHandler` (CUSTOMER_NOT_FOUND, INVOICE_NOT_FOUND, INVALID_INVOICE_NUMBER) |
| `cashapp/services/autofix/handlers/low_confidence.py` | `LowConfidenceHandler` |
| `cashapp/services/autofix/handlers/extraction_failed.py` | `RerunFailedReadersHandler` (EXTRACTION_FAILED, LLM_REFUSAL) |
| `cashapp/services/autofix/handlers/fusion_replan.py` | `ReplanLinesHandler` (FUSION_OVERAPPLY, FUSION_ALREADY_APPLIED) |
| `cashapp/services/autofix/handlers/fusion_gl_date.py` | `GlDateFloorHandler` |
| `cashapp/services/autofix/handlers/transient.py` | `BackoffRetryHandler` (FUSION_LOCKED, FUSION_TRANSIENT, LLM_TRANSIENT) |
| `cashapp/services/autofix/handlers/escalate.py` | `EscalateHandler` (AMOUNT_VARIANCE, always-person codes, everything else) |
| `cashapp/data/repositories/autofix.py` | `AutoFixHistoryRepository(BaseRepository[WorkItemHistory])` |
| `cashapp/api/schemas/requeue.py` | `RequeueIn`, `RequeueOut`, `FieldChangeOut`, `requeue_error_to_api` |
| `cashapp/api/routers/requeue.py` | `router` (`POST /items/{item_id}/requeue`), `get_requeue_service` |
| `api/tests/support/autofix.py` | `make_engine`, `make_fix_context`, `StubReasoner`, `FailingRunner` (a test `StageRunner` raising a given `StageError`) |
| tests in the TEST PLAN | written and run in step 5 only |

Edited (append-only, one line each):

- `cashapp/domain/work_item.py` (s02): add `narrow: bool` to the `FixHints` TypedDict (`total=False`). s13 reads `FIX_HINTS.narrow`, and s02 pinned every other key. Because it's a TypedDict there's no DDL.
- `api/tests/conftest.py`: append `"tests.support.autofix"` to `pytest_plugins`.

Not touched:
- s02's models, `uow.py` and history repository
- s03's `failures.py` and `runner.py`
- s40's files and `main.py`
- lockfiles
- Alembic

## Design

### Engine flow (`AutoFixEngine.handle`, implements s03 `FailureHandler`)

1. `now = ctx.clock.now()`. **Lock guard:** if `is_locked_for_automation(item, now)`:
   - log `autofix.noop_locked` (item id and code only)
   - write an `AUTOFIX_ATTEMPT` row with `payload.decision = "noop_locked"`. It isn't counted as an attempt.
   - return `Escalate(None)`

   There are no hints, no reasoner call and no notification. The runner parks the item as ESCALATED (waiting for a person, which is true), and the person's requeue moves it on.
2. Count the prior attempts with `load_attempts(uow, item.id)`:
   - only `AUTOFIX_ATTEMPT` rows after the item's latest `HUMAN_ACTION` row (a requeue starts the count fresh)
   - excluding `noop_locked` rows
   - filtered to `error.code`

   Set `prior = len(...)` and `limit = ctx.config.retries().max_attempts_for(code)`.
3. Choose the escalation path when `code.spec.always_person`, or `prior >= limit`. Otherwise:
   - `fctx = FixContext(...)`
   - `decision = await registry[code].decide(fctx)`
4. **Retry guard:** a `Retry` for a code whose `spec.retryable` is False becomes `Escalate`, and an error is logged. A misconfigured or custom handler can never retry non-transient work.
5. **Escalate:**
   - `summary = await reasoner.summarise(item, error, attempts)`, falling back to `template_summary` on any exception, refusal or empty or invalid output
   - `item.escalation_summary = summary`
   - `await announce_escalation(uow, item, code, summary, clock=ctx.clock)` emits a `NotifyEvent` through the outbox
   - return `Escalate(summary)`
6. Write one `AUTOFIX_ATTEMPT` row through `record_history` with `actor_fields(SYSTEM_PRINCIPAL)`:
   - `error_code = code`
   - `reasoning` = the handler's explanation (`fctx.explain(...)`), or the summary on Escalate
   - `payload = {"attempt": prior + 1, "limit": limit, "decision": decision_kind(d), "stage": item.stage, "reroute_to": stage | None, "retry_after_seconds": int | None, "fix_hints": item.fix_hints, "prompt_version": PROMPT_VERSION | None}`
7. Return the decision. The runner then applies the state, `attempts += 1`, `LAST_ERROR_*`, its own `STAGE_TRANSITION` row and the event (s03).

**`FIX_HINTS` replacement rule.** Every Reroute or Park decision replaces `item.fix_hints` wholesale through `replace_fix_hints`. This clears stale `rerun_readers` (s08 risk). Retry and Escalate leave the hints unchanged.

### Handlers (`FixHandler.decide`)

`attempts_for_code` is the count of *prior* attempts. A handler that says "once" escalates when `attempts_for_code >= 1`. The engine has already enforced the configured limit before any handler runs.

| Code(s) | Decision | `FIX_HINTS` / side effect | Explanation (history `reasoning`) |
|---|---|---|---|
| RECEIPT_NOT_YET_AVAILABLE | `ParkAwaitingReceipt()` every time under the limit | `{match_on_creation_date: True}`; `awaiting_since` set if null | "No matching receipt in Fusion yet; waiting for it to arrive and will also match on receipt creation date." |
| RECEIPT_AMBIGUOUS | once `Reroute(MATCH_RECEIPT)`, then Escalate | `{narrow: True}` | "N receipts qualified; re-matching with references and dates to narrow." |
| AMOUNT_VARIANCE | Escalate | none | (summary) |
| CUSTOMER_NOT_FOUND, INVOICE_NOT_FOUND, INVALID_INVOICE_NUMBER | once `Reroute(EXTRACT)`, then Escalate; never Retry | `{rerun_readers: ["A","B"], effort: bump_effort(reader_a.effort)}` | "Re-reading the remittance at higher effort before trying again." |
| LOW_EXTRACTION_CONFIDENCE | once `Reroute(EXTRACT)`, then Escalate | `{rerun_readers: ["A","B"], effort: bump_effort(...)}` | |
| EXTRACTION_FAILED, LLM_REFUSAL (stage EXTRACT or ADJUDICATE) | `Reroute(EXTRACT)` up to the limit | `{rerun_readers: failed_readers(...), effort: bump_effort(...)}` | "Reader B timed out; re-running only Reader B." |
| LLM_REFUSAL at any other stage | Escalate | | |
| FUSION_OVERAPPLY, FUSION_ALREADY_APPLIED | `Reroute(MATCH_LINES)` | `{}` (s15 re-plans from fresh balances and existing applications) | |
| FUSION_GL_DATE | `Reroute(APPLY)`; Escalate if `error.detail["receipt_gl_date"]` is missing or not an ISO date | `{gl_date_floor: <ISO date>}` | |
| FUSION_LOCKED, FUSION_TRANSIENT, LLM_TRANSIENT | `Retry(after=timedelta(seconds=retries().backoff_for(prior + 1)))` | unchanged | "Fusion busy; retry 2/3 in 120 s." |
| All other codes, including PREPAYMENT, PO_SO_ERS_ONLY, DUAL_CURRENCY, UNGROUNDED, CUSTOMER_MULTIPLE_ACCOUNTS, AGED_OUT, UNSUPPORTED_ARTIFACT, WRITE_BACK_FAILED, REVERSAL_FAILED, SYSTEM_DEAD_LETTER, RECEIPT_RESERVED, INVOICE_CLOSED, FUSION_FAULT, FUSION_WRITE_DISABLED, CLASSIFICATION_FAILED | Escalate | | (summary) |

Notes on the helpers:

- `bump_effort(e)`: low→medium→high→max, with `None`→high and max→max. s02's `ModelRole.effort` has no `xhigh`.
- `failed_readers(uow, item, error)` resolves in order:
  1. `error.detail["failed_readers"]` when it's present
  2. otherwise, the readers whose latest `ExtractionReading` (s08 `ExtractionReadingRepository.latest_for`) isn't OK
  3. otherwise `["A", "B"]`

`default_registry()` maps **every** `ErrorCode` to a handler, with `EscalateHandler` as the fallback. `register()` replaces an entry.

### Reasoner

- `LlmReasoner(llm: LlmClient, role: ModelRole)`:
  - The client is `llm.workhorse.with_model(role.model_id)`.
  - It calls `parse(LlmRequest(system=SUMMARY_SYSTEM_PROMPT, parts=(TextPart(facts_json),), max_tokens=SUMMARY_MAX_TOKENS, timeout_s=min(role.timeout_s, SUMMARY_TIMEOUT_CAP_S), purpose="autofix.workhorse", effort=role.effort, work_item_id=item.id, prompt_version=PROMPT_VERSION), EscalationSummary)`.
- `facts_json` contains only the item's own fields:
  - stage
  - error code and description
  - `last_error_detail` keys and values (PII-free per s03)
  - payer name, amount, currency, payment date
  - the attempts list (code, decision, reasoning)

  It contains no artifact text and no extraction lines.
- The output is `EscalationSummary{summary: str}`, with the field description from `prompts.DESC_SUMMARY`. `limit_sentences(text, 3)` trims it to at most 3 sentences and 600 characters.
- Any of these falls back to `template_summary(item, error, attempts)`: `LlmError`, refusal, timeout, an empty result, or any other exception. Escalation is never blocked.
- `build_failure_handler(container)` builds a reasoner factory per `ConfigSnapshot`. It resolves `container.resolve(LlmClients)` lazily on the first escalation and caches it. A `KeyError` gives `TemplateReasoner` and a single warning.

### Escalation outside the runner (`escalate`, used by s14 and s38)

`escalate()` loads nothing; the caller passes the item it has already locked (`FOR UPDATE`). It sets:
- `state = ESCALATED`
- `last_error_code = code`
- `escalation_summary = summary or template_summary(...)`
- `claim_expires_at = None`

It writes one `STAGE_TRANSITION` row (from-state→ESCALATED, `error_code`, `reasoning = summary`, actor from `principal`), then calls `announce_escalation`. It never commits.

### Requeue (`RequeueService.requeue`)

Everything happens in the router's single transaction; the router commits.

1. `uow.work_items.get_for_update(item_id, skip_locked=False)`. None → `ItemNotFound` (s40's).
2. `LockService.assert_held_by(item, principal, now)` → `LockNotHeld`.
3. A DONE or ARCHIVED item → `ItemNotRequeueable`.
4. Choose the target:
   - `cmd.target_stage`, or VALIDATE when an extraction was corrected, or `item.stage` (the stage it failed in; the runner doesn't move the stage on failure)
   - It must be in `CONSUMED_STAGES` (s03), and must be at or after VALIDATE when a correction is given. Otherwise → `InvalidTargetStage`.
5. If `corrected_extraction` is given:
   - `before = AdjudicationRepository.latest_for(item_id)` (s09)
   - `save_human_correction(uow, item_id, final, principal)` (s09)
   - `changes = extraction_diff(before.final if before else None, final)`
6. Update the item:
   - `human_hints = {target_stage, customer_number?, receipt_id?}`
   - `fix_hints = None`
   - `attempts = 0`
   - `last_error_code / last_error_detail / escalation_summary / awaiting_since = None`
   - `stage = target`
   - `state = PENDING`
   - `claim_expires_at = None`
7. When `customer_number` is set and `learn_alias` is true, call `AliasService.learn(uow, item_id=…, payer_name=<final or latest payer_name.value>, bank_account=<payer_bank_account.value>, reference_pattern=None, customer_number=…, principal=principal)` (s37).
8. `LockService.release(uow, item_id, principal, redrive=False)` (s40 writes its own LOCK row).
9. Write the history row with `record_history(HUMAN_ACTION, **actor_fields(principal), from/to stage+state, reasoning=note, payload={"event": "requeue", "target_stage", "changes": [FieldChange…], "customer_number", "receipt_id", "learn_alias", "alias_id"})`.
10. `emit(uow, StageEvent.new(item.id, target, clock=clock), priority=item.priority)`.

The item then runs through the target stage's ordinary `StageRunner`.

`extraction_diff` compares by field path:
- the `.value` of each `Extracted` field
- the dates list
- the lines, keyed by `line_no`, by field (`lines[3].transaction_number`)
- added and removed lines (`lines[5]`, before or after `None`)

Decimal values are compared as 2-dp strings.

### Policy checks (`policy_check`, for s10 and s13)

`policy_findings(extraction, *, artifact_text: str | None = None) -> PolicyFindings`.

- A transaction-bearing line is a line of kind INVOICE, CREDIT_MEMO or UNKNOWN with a non-empty `transaction_number`.
- **PREPAYMENT:**
  - no transaction-bearing lines, *and*
  - a prepayment marker in `notes`, `remittance_reference.value` or any line or field `source.quote`
  - The marker regex is `PREPAYMENT_MARKERS`: prepay, pre-pay, advance payment, on account, on-account, deposit.
- **PO_SO_ERS_ONLY:** no transaction-bearing lines, but PO, sales-order or ERS references exist (header refs or per line).
- **UNGROUNDED:** a transaction-bearing line whose normalised number (alphanumerics only, upper case) is absent from its own `source.quote` when a quote exists, otherwise from the normalised `artifact_text` when that is given.
  - A line with no evidence at all is reported in `unchecked_lines`, not as ungrounded. Absence of evidence is surfaced, never treated as a pass and never treated as a failure.
- Precedence is PREPAYMENT > PO_SO_ERS_ONLY > UNGROUNDED. `policy_check` returns `findings.code`.

Callers raise `StageError(code, detail=findings.detail())`, where the detail holds line numbers only, no text. The engine escalates, because all three codes are `always_person`.

## Interfaces provided (pinned)

```python
# cashapp/domain/notifications.py
NOTIFY_TOPIC_NAME: Final = "notify"                       # topic = TopicNamer.named("notify") -> "{prefix}.{env}.notify"
class NotifyKind(StrEnum): ITEM_ESCALATED="item_escalated"; DLQ_GROWTH="dlq_growth"; OUTAGE="outage"; BUDGET_EXCEEDED="budget_exceeded"
class NotifySeverity(StrEnum): INFO="info"; WARNING="warning"; CRITICAL="critical"
class NotifyEvent(BaseModel):                             # frozen=True, extra="forbid"
    schema_version: Literal[1] = 1
    event_id: UUID                                        # default_factory=uuid4
    kind: NotifyKind
    severity: NotifySeverity
    work_item_id: int | None = None
    error_code: ErrorCode | None = None
    summary: str                                          # 1..2000 chars
    occurred_at: datetime                                 # tz-aware UTC (naive -> ValidationError)
    @classmethod
    def new(cls, kind: NotifyKind, severity: NotifySeverity, summary: str, *, clock: Clock,
            work_item_id: int | None = None, error_code: ErrorCode | None = None) -> "NotifyEvent"

# cashapp/services/notify.py
def notify_topic(namer: TopicNamer | None = None) -> str  # (namer or default_namer()).named(NOTIFY_TOPIC_NAME)
async def emit_notify(uow: UnitOfWork, event: NotifyEvent, *, clock: Clock | None = None) -> OutboxMessage
    # s03 enqueue(topic=notify_topic(), key=str(work_item_id) if set else kind.value, payload=event, priority=PRIORITY_LIVE); no commit
```

```python
# cashapp/services/autofix/engine.py
@dataclass(slots=True)
class FixContext:
    uow: UnitOfWork
    item: WorkItem                     # loaded FOR UPDATE by the runner
    error: StageError
    attempts_for_code: int             # prior attempts for error.code since the last HUMAN_ACTION (0 on first failure)
    limit: int                         # config.retries().max_attempts_for(error.code)
    config: ConfigSnapshot
    clock: Clock
    reasoner: Reasoner
    stage_ctx: StageContext            # additive: the runner's context (log, event, principal)
    def explain(self, text: str) -> None   # handler's plain-language reasoning for the history row
    @property
    def explanation(self) -> str | None

class FixHandler(Protocol):
    async def decide(self, ctx: FixContext) -> FailureDecision: ...

ReasonerFactory = Callable[[ConfigSnapshot], Reasoner]
class AutoFixEngine:                   # implements s03 FailureHandler
    def __init__(self, *, registry: Mapping[ErrorCode, FixHandler] | None = None,
                 reasoner_factory: ReasonerFactory | None = None) -> None   # None -> default_registry(), TemplateReasoner
    def register(self, code: ErrorCode, handler: FixHandler) -> None
    def handler_for(self, code: ErrorCode) -> FixHandler
    @property
    def registered_codes(self) -> frozenset[ErrorCode]
    async def handle(self, uow: UnitOfWork, item: WorkItem, error: StageError, ctx: StageContext) -> FailureDecision
def default_registry() -> dict[ErrorCode, FixHandler]     # total over ErrorCode
def build_failure_handler(container: Container) -> AutoFixEngine   # s30 loads "cashapp.services.autofix.engine:build_failure_handler"
```

```python
# cashapp/services/autofix/attempts.py
NOOP_LOCKED: Final = "noop_locked"
@dataclass(frozen=True, slots=True)
class AttemptRecord: at: datetime; error_code: ErrorCode | None; attempt: int; limit: int; decision: str; reasoning: str | None
@dataclass(frozen=True, slots=True)
class AttemptSummary:
    tried: int; limit: int; attempts: tuple[AttemptRecord, ...]   # tried/limit for the item's LAST_ERROR_CODE
async def load_attempts(uow: UnitOfWork, item_id: int) -> list[AttemptRecord]   # since latest HUMAN_ACTION; noop rows excluded
async def attempt_summary(uow: UnitOfWork, item: WorkItem, config: ConfigSnapshot) -> AttemptSummary
    # s20 "Auto-fixes tried 3 / 5" and the reasoner input; limit 0 when LAST_ERROR_CODE is null

# cashapp/data/repositories/autofix.py
class AutoFixHistoryRepository(BaseRepository[WorkItemHistory]):
    model = WorkItemHistory
    async def latest_human_action_at(self, item_id: int) -> datetime | None
    async def autofix_rows_since(self, item_id: int, since: datetime | None) -> list[WorkItemHistory]   # ordered at, id
```

```python
# cashapp/services/autofix/hints.py
def replace_fix_hints(item: WorkItem, hints: FixHints) -> None        # wholesale replace (never merge)
def bump_effort(effort: str | None) -> Literal["medium", "high", "max"]
async def failed_readers(uow: UnitOfWork, item: WorkItem, error: StageError) -> list[Literal["A", "B"]]

# cashapp/services/autofix/reasoner.py
class Reasoner(Protocol):
    async def summarise(self, item: WorkItem, error: StageError, attempts: Sequence[AttemptRecord]) -> str: ...
class EscalationSummary(BaseModel): summary: str      # Field(description=prompts.DESC_SUMMARY, max_length=1200)
class LlmReasoner:      # __init__(self, llm: LlmClient, role: ModelRole); never raises (falls back to template)
class TemplateReasoner: # deterministic; __init__(self) -> None
def template_summary(item: WorkItem, error: StageError, attempts: Sequence[AttemptRecord]) -> str
def limit_sentences(text: str, n: int = 3, *, max_chars: int = 600) -> str

# cashapp/services/autofix/escalation.py
async def escalate(uow: UnitOfWork, item: WorkItem, code: ErrorCode, summary: str | None,
                   principal: Principal = SYSTEM_PRINCIPAL, *, clock: Clock | None = None) -> None
    # STATE=ESCALATED, LAST_ERROR_CODE, ESCALATION_SUMMARY (template when None), STAGE_TRANSITION history, NotifyEvent; no commit
async def announce_escalation(uow: UnitOfWork, item: WorkItem, code: ErrorCode, summary: str,
                              *, clock: Clock | None = None) -> NotifyEvent
    # kind=ITEM_ESCALATED, severity=WARNING (CRITICAL never for single items); used by escalate() and the engine
```

```python
# cashapp/services/autofix/policy.py
PREPAYMENT_MARKERS: Final[re.Pattern[str]]
@dataclass(frozen=True, slots=True)
class PolicyFindings:
    code: ErrorCode | None                      # PREPAYMENT | PO_SO_ERS_ONLY | UNGROUNDED | None
    ungrounded_lines: tuple[int, ...]           # line_no
    unchecked_lines: tuple[int, ...]            # no quote and no artifact_text to check against
    def detail(self) -> dict[str, Any]          # {"ungrounded_lines": [...], "unchecked_lines": [...]} (no text)
def policy_findings(extraction: RemittanceExtraction, *, artifact_text: str | None = None) -> PolicyFindings
def policy_check(extraction: RemittanceExtraction, *, artifact_text: str | None = None) -> ErrorCode | None

# cashapp/services/autofix/diff.py
@dataclass(frozen=True, slots=True)
class FieldChange: path: str; before: JsonValue; after: JsonValue
def extraction_diff(before: RemittanceExtraction | None, after: RemittanceExtraction) -> list[FieldChange]
```

```python
# cashapp/services/autofix/requeue.py
@dataclass(frozen=True, slots=True)
class RequeueCommand:
    note: str
    target_stage: Stage | None = None
    corrected_extraction: RemittanceExtraction | None = None
    customer_number: str | None = None
    receipt_id: int | None = None
    learn_alias: bool = True
@dataclass(frozen=True, slots=True)
class RequeueResult:
    item_id: int; stage: Stage; state: ItemState; changes: tuple[FieldChange, ...]; alias_id: int | None
class RequeueError(Exception): item_id: int
class ItemNotRequeueable(RequeueError): state: ItemState            # DONE / ARCHIVED
class InvalidTargetStage(RequeueError): target_stage: str; reason: str
class RequeueService:
    def __init__(self, *, lock_service: LockService, alias_service: AliasService, clock: Clock | None = None) -> None
    async def requeue(self, uow: UnitOfWork, item_id: int, cmd: RequeueCommand, principal: Principal) -> RequeueResult
        # raises s40 ItemNotFound / LockNotHeld, ItemNotRequeueable, InvalidTargetStage; flushes, never commits
```

### HTTP contract (s20, s22, s31)

`POST /items/{item_id}/requeue`. Permission `items:work`. Every error uses s01's shape.

- **Body `RequeueIn`:**
  - `target_stage?: Stage`
  - `corrected_extraction?: RemittanceExtraction`
  - `customer_number?: str (1..100, stripped)`
  - `receipt_id?: int (>0)`
  - `learn_alias: bool = true`
  - `note: str (1..2000, stripped)`
- **200 `RequeueOut`:** `{item_id, stage, state: "PENDING", changes: [{path, before, after}], alias_learned: bool}`
- **Errors:**
  - 404 `item_not_found`
  - 409 `lock_not_held` (s40 `lock_error_to_api`)
  - 409 `item_not_requeueable` (details `[{"state": …}]`)
  - 422 `invalid_target_stage` (details `[{"target_stage": …, "reason": …}]`)
  - 403 `forbidden`
  - 422 `validation_error` (blank note)
- **Dependencies:** `require_permission(Permission.ITEMS_WORK)`, s04 `UowFactoryDep`, s28 `RuntimeConfigDep`, and `get_requeue_service(runtime) -> RequeueService`, which builds `LockService(runtime)` and `AliasService()` (overridable in tests).
- The router opens the UoW, calls the service, commits, and maps `LockError` / `RequeueError` with `lock_error_to_api` / `requeue_error_to_api`.

## Migrations

None. Every column used already exists in s02's `0001_base`: `WORK_ITEM.ESCALATION_SUMMARY`, `FIX_HINTS`, `HUMAN_HINTS`, `AWAITING_SINCE`, `LAST_ERROR_*`, `ATTEMPTS`, plus `WORK_ITEM_HISTORY.*` and `OUTBOX.*`. The `FixHints.narrow` key is a TypedDict change with no DDL. Expected Alembic head: unchanged, whatever head the merger has when this lands.

## TEST PLAN (written and run in step 5 only)

Unit and integration tests run on aiosqlite (s02 fixtures), with `FrozenClock`, s28 `make_config_snapshot` / `make_runtime_config`, s03 `make_runner_deps` / `FakeContainer` / `run_stage_once` / `drain_outbox` / `memory_bus`, s04 `make_principal` / `mint_token`, s08 `scripted_llm` / `make_llm_clients` / `make_extraction`, and s40 `lock_item`. The model is never called live in the default suite.

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/unit/services/autofix/test_engine.py::test_every_error_code_has_registered_handler` (`default_registry().keys() == set(ErrorCode)`; `AutoFixEngine().registered_codes` total) |
| 1 | `…::test_register_replaces_handler` |
| 1 | `…::test_fix_context_carries_uow_item_error_attempts_config_clock_reasoner` |
| 1 | `…::test_engine_satisfies_failure_handler_protocol` |
| 1 | `…::test_build_failure_handler_uses_llm_reasoner_when_llm_clients_registered_else_template` (`FakeContainer`) |
| 2 | `api/tests/unit/services/autofix/test_handlers.py::test_receipt_not_yet_available_parks_sets_awaiting_since_and_creation_date_hint` |
| 2 | `…::test_receipt_ambiguous_reroutes_match_receipt_once_with_narrow_then_escalates` |
| 2 | `…::test_amount_variance_escalates` |
| 2 | `…::test_not_found_codes_reextract_once_then_escalate_never_retry` (parametrized CUSTOMER_NOT_FOUND, INVOICE_NOT_FOUND, INVALID_INVOICE_NUMBER; `rerun_readers=["A","B"]`, effort bumped) |
| 2 | `…::test_low_confidence_reextracts_once_with_higher_effort_then_escalates` |
| 2 | `…::test_extraction_failed_reruns_only_failed_readers_until_limit` (detail first, then readings fallback, then both) |
| 2 | `…::test_llm_refusal_at_extract_reroutes_elsewhere_escalates` |
| 2 | `…::test_fusion_overapply_and_already_applied_reroute_match_lines` |
| 2 | `…::test_fusion_gl_date_reroutes_apply_with_floor_from_detail_and_escalates_without_it` |
| 2 | `…::test_transient_codes_retry_with_backoff_for_attempt` (FUSION_LOCKED, FUSION_TRANSIENT, LLM_TRANSIENT; `after` = `backoff_for(1..n)`) |
| 2 | `…::test_escalate_only_codes` (parametrized over the AC2 escalate list plus unlisted codes) |
| 2 | `…::test_reroute_and_park_replace_fix_hints_wholesale` |
| 2 | `api/tests/unit/services/autofix/test_hints.py::test_bump_effort_ladder` |
| 3 | `api/tests/unit/services/autofix/test_engine.py::test_only_retryable_codes_ever_retry` (every `ErrorCode` × prior 0..limit, with stub detail; `Retry` only when `spec.retryable`) |
| 3 | `…::test_limit_reached_escalates_for_every_code` (`retries.max_attempts` override per code and `"*"`) |
| 3 | `…::test_retry_from_custom_handler_for_non_retryable_code_becomes_escalate` |
| 3 | `…::test_always_person_codes_escalate_on_first_failure` |
| 3 | `…::test_locked_item_is_noop` (live lock via `lock_item`; `is_locked_for_automation` true; handler not called; no hints, no reasoner call, no notify row; history `decision="noop_locked"`) |
| 3 | `api/tests/unit/services/autofix/test_attempts.py::test_attempts_counted_per_code_since_last_human_action_excluding_noop` |
| 3 | `…::test_attempt_summary_tried_and_limit` |
| 4 | `api/tests/integration/autofix/test_engine_history.py::test_every_decision_writes_one_autofix_attempt_row` (action, error_code, `attempt` n / `limit`, decision, reasoning non-empty; parametrized over decision kinds) |
| 4 | `…::test_escalate_summary_from_workhorse_stored_on_item` (scripted `ReplayLlmClient`; request `purpose="autofix.workhorse"`, model = `models.workhorse.model_id`, effort = the role's, one `TextPart`; stored ≤ 3 sentences) |
| 4 | `…::test_summary_request_contains_no_artifact_or_line_text` |
| 4 | `…::test_reasoner_failure_falls_back_to_template` (parametrized transient, refusal, timeout, empty output, generic exception; escalation still happens) |
| 4 | `…::test_runner_failure_path_end_to_end` (`FailingRunner` raising RECEIPT_AMBIGUOUS with `build_failure_handler(FakeContainer)`; first `run_stage_once` → Reroute(MATCH_RECEIPT) event in outbox, `FIX_HINTS.narrow`; second failure → ESCALATED, summary set, notify row) |
| 4 | `api/tests/unit/services/autofix/test_reasoner.py::test_limit_sentences_and_template_summary` |
| 5 | `api/tests/unit/services/autofix/test_escalation.py::test_escalate_sets_state_code_summary_and_history` |
| 5 | `…::test_escalate_emits_notify_event_via_outbox_on_notify_topic` (topic `cashapp.test.notify`, key = item id, payload validates as `NotifyEvent`) |
| 5 | `…::test_escalate_without_summary_uses_template` |
| 5 | `…::test_escalate_does_not_commit` (rollback → no state change, no outbox row) |
| 5 | `…::test_escalate_records_principal_actor` |
| 5 | `api/tests/unit/domain/test_notifications.py::test_notify_event_fields_kinds_severities` |
| 5 | `…::test_notify_event_rejects_naive_datetime_and_extra_fields` |
| 5 | `api/tests/unit/services/test_notify.py::test_emit_notify_writes_one_outbox_row` |
| 6 | `api/tests/api/test_requeue_api.py::test_requeue_requires_items_work_403` |
| 6 | `…::test_requeue_without_live_lock_409_lock_not_held` (no lock, another owner, expired) |
| 6 | `…::test_requeue_with_correction_saves_human_adjudication_and_defaults_to_validate` |
| 6 | `…::test_requeue_without_correction_defaults_to_failed_stage` |
| 6 | `…::test_requeue_writes_human_hints_clears_fix_hints_resets_attempts_and_releases_lock` |
| 6 | `…::test_requeue_learns_alias_only_when_customer_chosen_and_learn_alias` |
| 6 | `…::test_requeue_history_row_has_field_level_diff_and_actor` |
| 6 | `…::test_requeue_is_one_transaction` (`AliasService.learn` raising → no correction, hints, lock change or outbox row persisted) |
| 6 | `…::test_requeue_emits_stage_event_for_target` |
| 6 | `…::test_requeue_done_item_409_and_invalid_target_422` |
| 6 | `…::test_requeue_route_in_openapi` (`RequeueIn`, `RequeueOut` schemas) |
| 6 | `api/tests/integration/autofix/test_requeue_pipeline.py::test_requeued_item_reaches_next_stage_via_run_stage_once` (ESCALATED item → lock → requeue → `run_stage_once(StubRunner at target)` → `Advance` committed, stage moved) |
| 6 | `api/tests/unit/services/autofix/test_diff.py::test_extraction_diff_header_fields_lines_added_removed` |
| 7 | `api/tests/unit/services/autofix/test_policy.py::test_prepayment_marker_without_transaction_numbers` |
| 7 | `…::test_po_so_ers_only_references` |
| 7 | `…::test_ungrounded_transaction_number_not_in_quote` |
| 7 | `…::test_grounded_by_quote_or_artifact_text_after_normalisation` |
| 7 | `…::test_no_evidence_reported_unchecked_not_ungrounded` |
| 7 | `…::test_normal_remittance_passes` (`make_extraction()` with quotes) |
| 7 | `…::test_precedence_prepayment_over_po_over_ungrounded` |
| 7 | `…::test_policy_codes_escalate_via_engine` |
| — | `api/tests/live/test_autofix_reasoner_live.py::test_haiku_summary_shape` (`@pytest.mark.live`; deselected by default) |

Gates for the coder: `uv run ruff check . && uv run ruff format --check .` and `uv run pyright` only.

## Assumptions and deviations

- **Lock no-op = `Escalate(None)`.** s03 has no "do nothing" decision.
  - For a locked item, the engine returns `Escalate(None)` with no hints, no summary change, no notification and no counted attempt.
  - The runner marks the item ESCALATED, which means "waiting for a person", and that is accurate.
  - This path is rare, because s40 refuses to lock an item under a live claim.
- **Attempts are counted from history, not from `WORK_ITEM.ATTEMPTS`.** The runner resets `ATTEMPTS` on every `Advance`, and a code can recur across stages. "Attempts for a code" means the `AUTOFIX_ATTEMPT` rows with that code since the item's latest `HUMAN_ACTION`.
- **Effort is bumped one level instead of fixed at `"high"`.** s02's reader A default is already `high`, so "high" would change nothing. Re-extraction uses `bump_effort` (high→max).
- **WRITE_BACK_FAILED is not retried.** It isn't `retryable` (s02), and AC3 forbids retrying it. s17 should raise `FUSION_TRANSIENT` / `FUSION_LOCKED` for its transient causes, which are retried, and keep `WRITE_BACK_FAILED` for the rest, which escalates. This is flagged to s17.
- **LLM_REFUSAL** is re-extracted only when it comes from EXTRACT or ADJUDICATE. A classify refusal escalates, because re-extracting would skip classification.
- **FUSION_GL_DATE** needs `error.detail["receipt_gl_date"]` (ISO date) from s05/s15. Without it, the handler escalates.
- `policy_check` adds `PO_SO_ERS_ONLY` to the AC's two checks, because it is an always-person code on the same input. DUAL_CURRENCY needs Fusion data, so it stays with s11.
- `FixHints.narrow` is appended to s02's TypedDict as a one-line edit; s13 depends on it.
- Import paths for same-wave dependencies that are not yet planned are coded against their stories, and the merger reconciles them:
  - `cashapp.stations.adjudicate.corrections:save_human_correction`
  - `cashapp.data.repositories.adjudication:AdjudicationRepository`
  - `cashapp.services.aliases:AliasService` (no-argument constructor)
  - No local stand-ins.
- `emit_notify` lives in `cashapp/services/notify.py`, not in the domain module, so `domain/` stays free of pipeline imports. s36 and s42 import it from there.
- Requeue clears `ESCALATION_SUMMARY`, `LAST_ERROR_*` and `AWAITING_SINCE`, because the item is no longer stuck. The history keeps the record.

## Risks

- **RECEIPT_NOT_YET_AVAILABLE versus the default limit.** `retries.max_attempts` defaults to `{"*": 3}`.
  - Every s14 wake-up that fails to match counts as an attempt, so a busy customer could escalate after 3 non-matching receipts, long before the 30-day aging.
  - **Flagged for Jonathan:** set `retries.max_attempts["RECEIPT_NOT_YET_AVAILABLE"]` high (for example 50) in config, and let aging be the real bound.
  - No code default is changed here.
- **An LLM call inside a row-locked transaction.** The summary call happens while the runner holds the item `FOR UPDATE`. It is bounded by `SUMMARY_TIMEOUT_CAP_S` (20 s) and only runs on escalation. The fallback template keeps it from blocking.
- **Untested heuristics.** `policy_check` heuristics (markers, quote grounding) are a starting point. Readers that omit `source.quote` leave lines unchecked rather than ungrounded, so s10/s13 should pass `artifact_text` when they have it.
- **Requeue lands before the relay wakes.** Requeue commits in the API process. The worker's relay picks the event up within `idle_seconds` (10 s), as noted in s03's risk.
- **Coding ahead of merges.** s09 and s37 are coded against their story interfaces before their plans exist, so the merger may need import fixes. aiosqlite doesn't exercise `FOR UPDATE`, so concurrent requeue/lock races rely on s40's `version_id_col` safety net.
