# Plan: s02-data-layer-foundation

Issue #2. Wave 1, serialized spine step 3 (after s01, s27; before s04, s28, s26). Paths: `cashapp/` = `api/src/cashapp/`.

## Standards followed

- CLAUDE.md *Data layer*: SQLAlchemy 2.0 async on `python-oracledb` thin mode, Alembic, generic `BaseRepository`, repositories never commit, services own transactions, identity PKs, native JSON on ATP, SKIP LOCKED for claiming, upper snake case DB objects, Money as `Decimal` (2 dp, `ROUND_HALF_UP`, equality `|a-b| <= 0.005`).
- research.md a3 (hand-rolled repository/UoW/registries) + a6 rails (`fetch_decimals=True`, `Numeric(asdecimal=True)`, money as strings in JSON/OpenAPI).
- `python-web-app:building-python-web-apps`: lazy engine (s01), `expire_on_commit=False`, `pool_pre_ping`, every schema change is an Alembic revision, aiosqlite for fast unit tests.
- Pyright strict on `src/`; ruff. No `sqlalchemy` import outside `cashapp/data/` and `alembic/` (enforced by a test).
- Reference doc §4 and §5 for statuses, precedence and the exception shape.

## Files to touch

New (owned by this story):

| Path | Content |
|---|---|
| `cashapp/domain/__init__.py` | empty |
| `cashapp/domain/stages.py` | `Stage`, `PIPELINE_ORDER`, `ItemState` |
| `cashapp/domain/status.py` | `PaymentStatus`, `PAYMENT_FAILURE_PRECEDENCE`, `LineStatus`, `InfoFlag`, `HeaderResult`, `roll_up`, `ExceptionSeverity`, `ExceptionInfo` |
| `cashapp/domain/error_codes.py` | `ErrorCategory`, `ErrorSpec`, `ErrorCode`, `ERROR_SPECS` |
| `cashapp/domain/money.py` | `to_money`, `money_eq`, `MoneyStr`, `CurrencyCode`, `Money`, `CurrencyMismatchError` |
| `cashapp/domain/config_keys.py` | `ConfigKey`, `ModelRole`, `BankFeeBand`, every key constant, `CONFIG_KEYS` |
| `cashapp/domain/clock.py` | `Clock`, `SystemClock`, `utcnow` |
| `cashapp/domain/paging.py` | `Page[T]` (pure, so routers/services need no SQLAlchemy) |
| `cashapp/domain/work_item.py` | `SourceKind`, `ActorKind`, `HistoryAction`, `HumanHints`, `FixHints` TypedDicts, `PRIORITY_LIVE = 100`, `PRIORITY_BACKLOG = 10` |
| `cashapp/data/types.py` | `JsonDoc`, `UtcDateTime`, `StrEnumType`, `MoneyNumeric`, `IdentityPk` |
| `cashapp/data/models/__init__.py` | re-exports `Base`; `load_all_models()` (pkgutil-imports every submodule, so later stories add a module and never edit this file) |
| `cashapp/data/models/base.py` | `Base(DeclarativeBase)` with upper-case naming convention |
| `cashapp/data/models/work_item.py` | `WorkItem`, `WorkItemHistory` |
| `cashapp/data/models/outbox.py` | `OutboxMessage` |
| `cashapp/data/repository.py` | `BaseRepository[ModelT]` (re-exports `Page`) |
| `cashapp/data/repositories/__init__.py` | empty (no registry; `uow.repo(cls)` instantiates any repository) |
| `cashapp/data/repositories/work_items.py` | `WorkItemRepository` |
| `cashapp/data/repositories/history.py` | `HistoryRepository` |
| `cashapp/data/repositories/outbox.py` | `OutboxRepository` |
| `cashapp/data/uow.py` | `UnitOfWork`, `UowFactory`, `make_uow_factory` |
| `cashapp/services/__init__.py` | empty (if s01 did not create it) |
| `cashapp/services/history.py` | `HistoryEntry`, `record_history` |
| `api/alembic/versions/0001_base_work_item_history_outbox.py` | revision `"0001_base"`, `down_revision = None` |
| `api/tests/__init__.py`, `api/tests/support/__init__.py` | empty (only if absent), so `tests.support.*` is importable |
| `api/tests/support/db.py` | fixtures `sqlite_engine`, `uow_factory`, `uow`, `atp_engine`, `atp_uow_factory` |
| `api/tests/support/factories.py` | `make_work_item(**overrides) -> WorkItem` |
| `api/tests/support/clock.py` | `FrozenClock` |
| tests listed in the TEST PLAN | written in step 5 only |

Edited (spine is serial, so these small edits don't conflict):

- `cashapp/data/engine.py` (s01): set `oracledb.defaults.fetch_decimals = True` once, inside `create_engine` before the engine is built. Nothing else changes.
- `api/alembic/env.py` (s01/s27): `from cashapp.data.models import Base, load_all_models`; call `load_all_models()`; `target_metadata = Base.metadata`.
- `api/tests/conftest.py` (s01, empty root): add `pytest_plugins = ("tests.support.db",)`. Later stories append to this tuple only.

Not touched: `main.py`, the lockfiles, `settings.py`.

## Design

### Naming (applies to every later story's tables)

- SQLAlchemy names are **lowercase** (`__tablename__ = "work_item"`, attribute `stage`). Oracle stores unquoted names in upper case, so the physical objects are `WORK_ITEM.STAGE`. Never write `Column("STAGE")`: SQLAlchemy would quote it.
- Don't use a column name from SQLAlchemy's Oracle reserved list (`comment`, `level`, `mode`, `size`, `uid`, `user`, `date`, `number`, `lock`, `start`, `desc`, `current`, `share`, `resource`), because SQLAlchemy quotes those in lowercase. `AT`, `VERSION`, `STATE` and `PRIORITY` are fine.
- `Base.metadata` naming convention (upper case, at most 30 characters): `PK_%(table_name)s`, `FK_%(table_name)s_%(column_0_name)s`, `UQ_%(table_name)s_%(column_0_name)s`, `IX_%(table_name)s_%(column_0_name)s`, `CK_%(table_name)s_%(constraint_name)s`. Explicit short names are used wherever the result would be longer than 30 characters.
- Enum-valued columns are `VARCHAR2(40)` with **no CHECK constraint**, so appending an enum value never needs DDL. `StrEnumType` validates on bind and load.

### `cashapp/data/types.py`

- `IdentityPk` = `mapped_column(BigInteger().with_variant(Integer, "sqlite"), Identity(), primary_key=True)` (helper function `identity_pk()`). The sqlite variant is needed because SQLite only autoincrements `INTEGER PRIMARY KEY`.
- `JsonDoc(TypeDecorator[Any])`: `impl = JSON`, `cache_ok = True`. On Oracle, `load_dialect_impl` returns `OracleJson`, a `UserDefinedType` compiled as `JSON` that binds `json.dumps(value, default=_json_default)` (Decimal is written as a string). The result processor accepts both a `dict`/`list` (what thin mode returns for native JSON) and a `str` (`json.loads`). On other dialects it uses the generic `JSON`.
- `UtcDateTime(TypeDecorator[datetime])`: `DateTime(timezone=True)`. Binding a naive datetime raises `ValueError`. Results are always tz-aware UTC (SQLite drops the tz, so it's re-attached).
- `StrEnumType(enum_cls, length=40)`: a `String` that loads into the StrEnum.
- `MoneyNumeric = Numeric(18, 2, asdecimal=True)`.

### Models (pinned attribute names; physical columns are the upper case of each)

`WorkItem` (`work_item`), `__mapper_args__ = {"version_id_col": version}` (optimistic concurrency: an UPDATE of a stale row raises `StaleDataError`):

| attr | type | null | notes |
|---|---|---|---|
| id | int identity PK | no | |
| parent_id | int FK `work_item.id` | yes | `FK_WORK_ITEM_PARENT` |
| source_kind | `SourceKind` (MAILBOX, FOLDER, BACKLOG, MANUAL) | no | |
| source_ref | String(1000) | yes | |
| content_hash | CHAR(64) | no | unique `UQ_WORK_ITEM_CONTENT_HASH` |
| artifact_key | String(1000) | yes | |
| stage | `Stage` | no | |
| state | `ItemState` | no | default PENDING |
| attempts | int | no | default 0 |
| last_error_code | `ErrorCode` | yes | |
| last_error_detail | JsonDoc dict | yes | |
| escalation_summary | Text (CLOB) | yes | |
| claim_expires_at | UtcDateTime | yes | s03 only |
| lock_owner, lock_owner_name | String(255) | yes | s40 only |
| lock_acquired_at, lock_expires_at | UtcDateTime | yes | s40 only |
| payer_name | String(500) | yes | |
| customer_account_number | String(100) | yes | |
| currency | CHAR(3) | yes | |
| payment_amount | MoneyNumeric `Decimal` | yes | NUMBER(18,2) |
| payment_date | Date | yes | |
| payment_status | `PaymentStatus` | yes | |
| info_flags | JsonDoc `list[str]` | no | default `[]` |
| human_hints | JsonDoc `HumanHints` | yes | s18 requeue only |
| fix_hints | JsonDoc `FixHints` | yes | s18 handlers only |
| batch_id | int | yes | no FK (s35 adds it) |
| priority | int | no | default `PRIORITY_LIVE` (100) |
| awaiting_since | UtcDateTime | yes | |
| version | int | no | version_id_col |
| created_at | UtcDateTime | no | `default=utcnow` |
| updated_at | UtcDateTime | no | `default=utcnow, onupdate=utcnow` (every ORM update bumps it; s19 and s40 rely on this) |

Indexes: `IX_WORK_ITEM_STAGE_STATE` (stage, state), `IX_WORK_ITEM_STATE_AWAITING` (state, awaiting_since), `IX_WORK_ITEM_LOCK_OWNER` (lock_owner), plus `IX_WORK_ITEM_PARENT_ID` (parent_id) for the FK.

`WorkItemHistory` (`work_item_history`): id, work_item_id (FK `FK_WIH_WORK_ITEM`, not null), at (UtcDateTime, not null), actor_kind (`ActorKind`), actor_id String(255), actor_name String(255), action (`HistoryAction`: STAGE_TRANSITION, AUTOFIX_ATTEMPT, HUMAN_ACTION, FUSION_WRITE, DECISION, LOCK), from_stage/to_stage (`Stage` null), from_state/to_state (`ItemState` null), error_code (`ErrorCode` null), reasoning (Text null), payload (JsonDoc null), purged_at (UtcDateTime null). Index `IX_WIH_ITEM_AT` (work_item_id, at).

`OutboxMessage` (`outbox`): id, topic String(255), msg_key String(255), payload JsonDoc not null, priority int not null default 100, not_before UtcDateTime **not null** (`emit` sets it to now when there's no delay; Oracle B-tree indexes skip all-null keys), created_at, published_at null, attempts int default 0, last_error Text null. Index `IX_OUTBOX_PENDING` (published_at, not_before, priority).

### Hints (`cashapp/domain/work_item.py`, `total=False` TypedDicts)

- `HumanHints{customer_number: str, receipt_id: int, target_stage: str}`
- `FixHints{rerun_readers: list[Literal["A","B"]], effort: str, gl_date_floor: str (ISO date), widen_window_days: int, match_on_creation_date: bool}`

## Interfaces provided (pinned)

```python
# cashapp/domain/stages.py
class Stage(StrEnum): INTAKE CLASSIFY EXTRACT ADJUDICATE VALIDATE RESOLVE_CUSTOMER FAST_PATH MATCH_RECEIPT MATCH_LINES APPLY WRITE_BACK DONE   # value == name
PIPELINE_ORDER: tuple[Stage, ...]  # the order above
def next_stage(stage: Stage) -> Stage | None
class ItemState(StrEnum): PENDING IN_PROGRESS AWAITING_RECEIPT ESCALATED DONE ARCHIVED
TERMINAL_STATES: frozenset[ItemState] = {DONE, ARCHIVED}

# cashapp/domain/status.py  (the ONLY place these strings exist)
class PaymentStatus(StrEnum): PAYMENT_SUCCESS="payment-success" ... PAYMENT_APPLY_FAILED_ZERO_BALANCE="payment-apply-failed-zero-balance"
  # member names = value upper-cased with "-" -> "_"; same for LineStatus and InfoFlag
SUCCESS_STATUSES: frozenset[PaymentStatus]  # the 3 success values + PAYMENT_PREVIOUSLY_APPLIED
PAYMENT_FAILURE_PRECEDENCE: tuple[PaymentStatus, ...] = (INVOICE_NOT_FOUND, CUSTOMER_NOT_FOUND, MISSING_PAYMENT_DATE,
    RECEIPT_NOT_FOUND, ZERO_AMOUNT, PAYMENT_APPLY_FAILED_RECEIPT_CLOSED, PAYMENT_APPLY_FAILED_ZERO_BALANCE, PAYMENT_APPLY_FAILED_SYSTEM)
class LineStatus(StrEnum): ALLOCATION_APPLIED="allocation-applied" ... ALLOCATION_DRY_RUN="allocation-dry-run"
APPLIED_LINE_STATUSES: frozenset[LineStatus]  # applied, -short-pay, -less-than-instruction, -with-discount
class InfoFlag(StrEnum): PAYMENT_HEADER_LINE_MISMATCH ... ALIAS_USED

@dataclass(frozen=True)
class HeaderResult:
    customer_found: bool
    payment_date_present: bool
    receipt_found: bool
    applied_total: Decimal          # sum actually applied (0 when nothing)
    total_due: Decimal              # sum the remittance said it was paying
    receipt_closed: bool = False
    dry_run: bool = False
def roll_up(header: HeaderResult, lines: Sequence[LineStatus]) -> PaymentStatus

class ExceptionSeverity(StrEnum): INFO="info" WARNING="warning" ERROR="error" CRITICAL="critical"
@dataclass(frozen=True)
class ExceptionInfo:
    type: str; error_code: str; reason: str; severity: ExceptionSeverity; title: str; detail: str
    error_details: tuple[str, ...] = ()
    def to_dict(self) -> dict[str, object]   # always all 7 keys; error_details as list
```

`roll_up` rules, in order:
1. `lines` is non-empty and every line is `ALLOCATION_PREVIOUSLY_APPLIED` → `PAYMENT_PREVIOUSLY_APPLIED`.
2. "Applied" means a line is in `APPLIED_LINE_STATUSES`, or is `ALLOCATION_DRY_RUN` while `header.dry_run` is set. If any line is applied and `receipt_found` and `customer_found` are both true, grade `applied_total` against `total_due`: `money_eq` → `PAYMENT_SUCCESS`; less → `..._LESS_THAN_TOTAL_DUE_SUCCESS`; more → `..._MORE_THAN_TOTAL_DUE_SUCCESS`.
3. Otherwise collect candidate failures:
   - from the header: not customer_found → CUSTOMER_NOT_FOUND; not payment_date_present → MISSING_PAYMENT_DATE; not receipt_found → RECEIPT_NOT_FOUND; receipt_closed → PAYMENT_APPLY_FAILED_RECEIPT_CLOSED.
   - from each line: invoice-not-found → INVOICE_NOT_FOUND; customer-not-found → CUSTOMER_NOT_FOUND; missing-payment-date → MISSING_PAYMENT_DATE; no-receipt-match → RECEIPT_NOT_FOUND; apply-failed or dry-run without dry_run → PAYMENT_APPLY_FAILED_SYSTEM.
   - ZERO_AMOUNT only when every line is zero-amount, or there are no lines and `total_due` is zero.
   - PAYMENT_APPLY_FAILED_ZERO_BALANCE only when every non-zero-amount line is no-remaining-balance.
   
   Return the first candidate in `PAYMENT_FAILURE_PRECEDENCE`. If there are no candidates (for example every line was reversed), return `PAYMENT_APPLY_FAILED_SYSTEM`. It never returns success when nothing was applied.

```python
# cashapp/domain/error_codes.py
class ErrorCategory(StrEnum): TRANSIENT DATA AMBIGUITY POLICY SYSTEM
@dataclass(frozen=True)
class ErrorSpec: category: ErrorCategory; retryable: bool; always_person: bool; description: str
class ErrorCode(StrEnum):  # 37 members exactly as story AC6, value == name
    @property
    def spec(self) -> ErrorSpec
ERROR_SPECS: Mapping[ErrorCode, ErrorSpec]   # MappingProxyType, total over ErrorCode
```

Category mapping:

| Category | Codes |
|---|---|
| TRANSIENT | FUSION_LOCKED, FUSION_TRANSIENT, LLM_TRANSIENT, RECEIPT_NOT_YET_AVAILABLE |
| AMBIGUITY | RECEIPT_AMBIGUOUS, RECEIPT_RESERVED, CUSTOMER_MULTIPLE_ACCOUNTS, LOW_EXTRACTION_CONFIDENCE |
| POLICY | AMOUNT_VARIANCE, PREPAYMENT, PO_SO_ERS_ONLY, DUAL_CURRENCY, UNGROUNDED, AGED_OUT, FUSION_WRITE_DISABLED |
| SYSTEM | EXTRACTION_FAILED, CLASSIFICATION_FAILED, LLM_REFUSAL, FUSION_FAULT, WRITE_BACK_FAILED, REVERSAL_FAILED, SYSTEM_DEAD_LETTER |
| DATA | everything else |

- `retryable` is True only for FUSION_LOCKED, FUSION_TRANSIENT and LLM_TRANSIENT. RECEIPT_NOT_YET_AVAILABLE is TRANSIENT in category but is *not* retryable: it is parked and woken by s14, never retried blind.
- `always_person` is True only for PREPAYMENT, PO_SO_ERS_ONLY, DUAL_CURRENCY and UNGROUNDED.

```python
# cashapp/domain/money.py
class CurrencyMismatchError(ValueError)
def to_money(value: Decimal | str | int) -> Decimal      # quantize(Decimal("0.01"), ROUND_HALF_UP); float -> TypeError
def money_eq(a: Decimal, b: Decimal) -> bool             # abs(a - b) <= Decimal("0.005")
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
MoneyStr = Annotated[Decimal, BeforeValidator(_coerce), PlainSerializer(lambda d: f"{d:.2f}", return_type=str, when_used="json"),
                     WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["12480.00"]})]
    # _coerce accepts str/int/Decimal and, from JSON input only, float via str(); always returns to_money(...)
@pydantic.dataclasses.dataclass(frozen=True)
class Money:
    amount: MoneyStr; currency: CurrencyCode
    def __add__(self, o: Money) -> Money; def __sub__(self, o: Money) -> Money; def __neg__(self) -> Money
    def eq(self, o: Money) -> bool          # same currency (else CurrencyMismatchError) and money_eq
    def is_zero(self) -> bool               # money_eq(amount, 0)
    @classmethod
    def zero(cls, currency: str) -> Money
```

```python
# cashapp/domain/config_keys.py
@dataclass(frozen=True)
class ConfigKey(Generic[T]):
    name: str; group: str; type: Any; default: T; description: str; admin_only_write: bool = True
    def validate(self, value: object) -> T        # TypeAdapter(self.type).validate_python
    def dump(self, value: T) -> Any               # TypeAdapter(...).dump_python(mode="json")
class ModelRole(BaseModel, frozen=True):          # s28 reuses this; don't redefine it
    model_id: str; effort: Literal["low","medium","high","max"] | None; timeout_s: int (>0)
    # validator: "fable" in model_id.lower() -> ValueError (zero retention, CLAUDE.md)
class BankFeeBand(BaseModel, frozen=True): currency: CurrencyCode | Literal["*"]; min_fee: MoneyStr; max_fee: MoneyStr
CONFIG_KEYS: Mapping[str, ConfigKey[Any]]          # keyed by name, MappingProxyType
def group_keys(group: str) -> tuple[ConfigKey[Any], ...]
```

Key constants: the name upper-cased, with `.` replaced by `_`.

| Constant | Type | Default |
|---|---|---|
| INTAKE_POLL_INTERVAL_SECONDS | int | 300 |
| RECEIPT_WATCHER_POLL_INTERVAL_SECONDS | int | 300 |
| MATCHING_DATE_WINDOW_DAYS | int | 5 |
| MATCHING_TOLERANCES | dict[str, MoneyStr] | {USD:0.10, EUR:0.10, INR:0.49, "*":0.10} |
| MATCHING_BANK_FEE_BANDS | list[BankFeeBand] | [] |
| MATCHING_SCORER_WEIGHTS | dict[str, float] | {} |
| MATCHING_MIN_SCORE | float | 0.0 |
| RETRIES_MAX_ATTEMPTS | dict[str, int] (ErrorCode or "*") | {"*":3} |
| RETRIES_BACKOFF_SECONDS | list[int] | [30,120,600] |
| AGING_AWAITING_RECEIPT_MAX_DAYS | int | 30 |
| ESCALATION_MIN_EXTRACTION_CONFIDENCE | float 0..1 | 0.8 |
| MODELS_READER_A | ModelRole | opus-5-5 / high / 120 |
| MODELS_READER_B | ModelRole | cohere.command-a-vision / None / 120 |
| MODELS_ADJUDICATOR | ModelRole | opus-5-5 / medium / 120 |
| MODELS_WORKHORSE | ModelRole | haiku-5-5 / low / 60 |
| EXTRACTION_FANIN_TIMEOUT_SECONDS | int | 180 |
| CONCURRENCY_PER_STAGE | dict[str,int] | {"*":4} |
| CONCURRENCY_APPLY_PER_RECEIPT | int | 1 |
| LOCKS_LEASE_MINUTES | int | 30 |
| BACKLOG_RATE_LIMIT_PER_MINUTE | int | 20 |
| RETENTION_RAW_ARTIFACT_DAYS | int \| None | None |
| RETENTION_EXTRACTION_DAYS | int \| None | None |
| RETENTION_HISTORY_PAYLOAD_DAYS | int \| None | None |
| BUDGET_DAILY_USD | MoneyStr \| None | None |
| NOTIFICATIONS_RECIPIENTS | dict[str, list[str]] | {} |
| NOTIFICATIONS_BATCH_WINDOW_SECONDS | int | 300 |
| REPORTS_DAILY_SUMMARY_CUTOVER | str matching `^\d{2}:\d{2}$` | "07:00" |
| DISCOUNT_ENABLED | bool | False |

The group is the prefix before the first `.`. At import time the module validates every default against its type, so a fable default can't ship.

```python
# cashapp/domain/clock.py
class Clock(Protocol):
    def now(self) -> datetime: ...     # tz-aware UTC
class SystemClock: def now(self) -> datetime  # datetime.now(UTC)
def utcnow() -> datetime                     # used for ORM defaults

# cashapp/domain/paging.py
@dataclass(frozen=True)
class Page(Generic[T]): items: list[T]; total: int; offset: int; limit: int

# cashapp/domain/work_item.py
class SourceKind(StrEnum): MAILBOX FOLDER BACKLOG MANUAL
class ActorKind(StrEnum): SYSTEM USER
class HistoryAction(StrEnum): STAGE_TRANSITION AUTOFIX_ATTEMPT HUMAN_ACTION FUSION_WRITE DECISION LOCK
SYSTEM_ACTOR_ID = "system"; SYSTEM_ACTOR_NAME = "CashApp automation"
PRIORITY_LIVE = 100; PRIORITY_BACKLOG = 10
```

```python
# cashapp/data/repository.py
ModelT = TypeVar("ModelT", bound=Base)
class BaseRepository(Generic[ModelT]):
    model: ClassVar[type[Base]]                      # set by each subclass
    def __init__(self, session: AsyncSession) -> None
    session: AsyncSession                            # read-only property
    async def get(self, id: int) -> ModelT | None
    async def list(self, *, where: Sequence[ColumnElement[bool]] = (), order_by: Sequence[Any] = (),
                   offset: int = 0, limit: int = 50) -> Page[ModelT]   # default order by PK; total via count over the same where
    async def add(self, entity: ModelT) -> ModelT                    # add + flush (id populated)
    async def update(self, entity: ModelT, **changes: Any) -> ModelT # unknown attr -> AttributeError; flush
    async def delete(self, entity: ModelT) -> None                   # delete + flush
    async def select_for_update_skip_locked(self, stmt: Select[tuple[ModelT]], limit: int | None = None) -> list[ModelT]
        # stmt.with_for_update(skip_locked=True) (+ .limit); the SQLite compiler drops FOR UPDATE, which is fine for unit tests
```

Repositories never call `commit`/`rollback`. Each repository takes the UoW's session.

```python
# cashapp/data/repositories/work_items.py
class WorkItemRepository(BaseRepository[WorkItem]):
    async def by_content_hash(self, content_hash: str) -> WorkItem | None
    async def claim(self, item_id: int, *, stage: Stage, now: datetime) -> WorkItem | None
        # SELECT ... WHERE id=:id AND stage=:stage AND state='PENDING' AND (lock_owner IS NULL OR lock_expires_at <= :now)
        # FOR UPDATE SKIP LOCKED; returns the row locked, or None (s03's claim; s03 sets state/claim_expires_at itself)
    async def get_for_update(self, item_id: int, *, skip_locked: bool = True) -> WorkItem | None
    async def children_of(self, parent_id: int) -> list[WorkItem]
# cashapp/data/repositories/history.py
class HistoryRepository(BaseRepository[WorkItemHistory]):
    async def for_item(self, item_id: int, *, offset: int = 0, limit: int = 200) -> Page[WorkItemHistory]   # ordered at, id
# cashapp/data/repositories/outbox.py
class OutboxRepository(BaseRepository[OutboxMessage]):
    async def claim_batch(self, *, now: datetime, limit: int) -> list[OutboxMessage]
        # published_at IS NULL AND not_before <= now ORDER BY priority DESC, id ; FOR UPDATE SKIP LOCKED
    async def mark_published(self, rows: Sequence[OutboxMessage], *, at: datetime) -> None
    async def mark_failed(self, row: OutboxMessage, *, error: str) -> None   # attempts += 1, last_error (truncated 4000)
    async def pending_count(self) -> int
```

```python
# cashapp/data/uow.py
R = TypeVar("R", bound=BaseRepository[Any])
class UnitOfWork:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None
    async def __aenter__(self) -> Self ; async def __aexit__(...) -> None   # always rollback() then close(); a no-op after commit
    session: AsyncSession            # property; RuntimeError outside the block
    work_items: WorkItemRepository   # property (same as repo(WorkItemRepository))
    history: HistoryRepository
    outbox: OutboxRepository
    def repo(self, cls: type[R]) -> R          # one instance per class per UoW, on this session
    async def commit(self) -> None             # may be called more than once (a new transaction starts lazily)
    async def rollback(self) -> None
UowFactory = Callable[[], UnitOfWork]
def make_uow_factory(engine: AsyncEngine) -> UowFactory   # async_sessionmaker(engine, expire_on_commit=False)
```

```python
# cashapp/services/history.py
@dataclass(frozen=True)
class HistoryEntry:
    action: HistoryAction
    actor_kind: ActorKind = ActorKind.SYSTEM
    actor_id: str = SYSTEM_ACTOR_ID
    actor_name: str = SYSTEM_ACTOR_NAME
    from_stage: Stage | None = None; to_stage: Stage | None = None
    from_state: ItemState | None = None; to_state: ItemState | None = None
    error_code: ErrorCode | None = None
    reasoning: str | None = None
    payload: Mapping[str, Any] | None = None     # JSON-serialisable; Decimal -> str
    at: datetime | None = None                  # None -> clock.now()
async def record_history(uow: UnitOfWork, item_id: int, entry: HistoryEntry, *, clock: Clock | None = None) -> WorkItemHistory
    # the ONLY writer of WORK_ITEM_HISTORY rows; adds via uow.history (flush, no commit)
```

s04 adds a helper that turns a `Principal` into actor fields. `HistoryEntry` stays principal-agnostic, so s02 doesn't depend on s04.

```python
# api/tests/support/clock.py
class FrozenClock:  # satisfies Clock
    def __init__(self, at: datetime = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)) -> None
    def now(self) -> datetime ; def advance(self, **delta: float) -> None ; def set(self, at: datetime) -> None
# api/tests/support/factories.py
def make_work_item(**overrides: Any) -> WorkItem   # unsaved; defaults: source_kind=FOLDER, content_hash=sha256(uuid4), stage=CLASSIFY,
                                                   # state=PENDING, priority=100, info_flags=[], attempts=0
# api/tests/support/db.py   (registered via pytest_plugins in tests/conftest.py)
@pytest.fixture async def sqlite_engine() -> AsyncIterator[AsyncEngine]   # "sqlite+aiosqlite://", StaticPool, load_all_models(); create_all
@pytest.fixture def uow_factory(sqlite_engine) -> UowFactory
@pytest.fixture async def uow(uow_factory) -> AsyncIterator[UnitOfWork]   # entered; rolled back at teardown
@pytest.fixture async def atp_engine() -> AsyncIterator[AsyncEngine]      # pytest.skip unless CASHAPP_TEST_ATP=1; built from get_settings().atp
                                                                          # with the same engine builder alembic/env.py uses (s01/s27)
@pytest.fixture def atp_uow_factory(atp_engine) -> UowFactory
```

## Migrations

- `api/alembic/versions/0001_base_work_item_history_outbox.py`, `revision = "0001_base"`, `down_revision = None`. It is hand-written, not autogenerated, so the Oracle types are exact.
- It creates `work_item` (with the self FK), `work_item_history` and `outbox`, plus the indexes and unique constraint above. It imports `cashapp.data.types.JsonDoc` so the Oracle DDL is `JSON`.
- `downgrade()` drops the indexes and tables in reverse order.
- The chain rule for later stories: each story adds exactly one revision whose `down_revision` is the current head; the merger re-points it and checks that `alembic heads` returns one head.
- Apply to **DEV ATP only**, through `-m atp` tests or the db-sync step. Never production.

## TEST PLAN (written and run in step 5 only)

| AC | Test (file::name) |
|---|---|
| 1 | `api/tests/unit/data/test_repository.py::test_get_add_update_delete_roundtrip` |
| 1 | `…::test_list_pages_with_where_order_total` |
| 1 | `…::test_update_unknown_attribute_raises` |
| 1 | `…::test_repository_flushes_but_never_commits` (a separate UoW can't see the row) |
| 1 | `…::test_select_for_update_skip_locked_returns_rows_with_limit` |
| 1 | `api/tests/unit/test_layering.py::test_no_commit_call_in_repositories` |
| 1 | `…::test_no_sqlalchemy_import_outside_data_and_alembic` (ast over `cashapp/`) |
| 2 | `api/tests/unit/data/test_uow.py::test_exit_without_commit_rolls_back` |
| 2 | `…::test_commit_persists` |
| 2 | `…::test_exception_in_block_rolls_back_and_reraises` |
| 2 | `…::test_repo_returns_same_instance_on_shared_session` |
| 2 | `…::test_named_repositories_exposed` |
| 2 | `…::test_session_outside_block_raises` |
| 3 | `api/tests/unit/data/test_schema.py::test_models_match_story_columns` (exact column sets for the 3 tables) |
| 3 | `…::test_indexes_and_unique_content_hash` |
| 3 | `…::test_alembic_single_head` (ScriptDirectory, no DB) |
| 3 | `…::test_migration_columns_equal_models` (ATP-free: compare the migration's op calls with the metadata, via `alembic.migration` offline SQL on the oracle dialect) |
| 3 | `api/tests/integration/test_migration_atp.py::test_upgrade_downgrade_upgrade_on_dev_atp` (`@pytest.mark.atp`) |
| 3 | `…::test_json_columns_native_and_roundtrip` (`atp`) |
| 3 | `…::test_skip_locked_claim_on_atp` (`atp`; two sessions, the second gets None) |
| 3 | `…::test_money_column_returns_decimal` (`atp`; fetch_decimals) |
| 4 | `api/tests/unit/domain/test_stages.py::test_stage_members_and_pipeline_order` |
| 4 | `…::test_item_state_members` |
| 4 | `…::test_next_stage` |
| 5 | `api/tests/unit/domain/test_status.py::test_payment_status_values` |
| 5 | `…::test_line_status_values` |
| 5 | `…::test_info_flag_values` |
| 5 | `…::test_failure_precedence_order` |
| 5 | `…::test_roll_up_success_grades` (eq, less, more within 0.005) |
| 5 | `…::test_roll_up_nothing_applied_receipt_missing_never_success` |
| 5 | `…::test_roll_up_precedence_picks_highest` (parametrized) |
| 5 | `…::test_roll_up_all_previously_applied` |
| 5 | `…::test_roll_up_zero_amount_and_zero_balance_rules` |
| 5 | `…::test_roll_up_dry_run` |
| 5 | `…::test_exception_info_to_dict_has_all_keys` |
| 5 | `api/tests/unit/test_layering.py::test_status_strings_defined_only_in_status_module` (ast string constants across `cashapp/`, exact match) |
| 6 | `api/tests/unit/domain/test_error_codes.py::test_all_codes_present_exactly` |
| 6 | `…::test_every_code_has_spec` |
| 6 | `…::test_only_transient_three_retryable` |
| 6 | `…::test_always_person_set` |
| 7 | `api/tests/unit/domain/test_money.py::test_half_up_2_675_to_2_68` |
| 7 | `…::test_money_eq_boundary_0_005` (0.005 equal, 0.006 not) |
| 7 | `…::test_mixed_currency_arithmetic_raises` |
| 7 | `…::test_float_rejected_by_to_money` |
| 7 | `…::test_moneystr_serialises_as_string_json_and_openapi` |
| 7 | `…::test_money_dataclass_quantises_and_validates_currency` |
| 8 | `api/tests/unit/domain/test_config_keys.py::test_registry_has_every_key_with_defaults` (parametrized over the 28 names) |
| 8 | `…::test_defaults_validate_against_type` |
| 8 | `…::test_fable_model_id_rejected` |
| 8 | `…::test_admin_only_write_default_true` |
| 8 | `…::test_group_keys` |
| 8 | `…::test_tolerance_values_are_decimal` |
| 9 | `api/tests/unit/domain/test_clock.py::test_system_clock_is_utc_aware` |
| 9 | `…::test_frozen_clock_satisfies_protocol_and_advances` |
| 10 | `api/tests/unit/services/test_history.py::test_record_history_writes_row_with_all_fields` |
| 10 | `…::test_defaults_to_system_actor_and_clock_time` |
| 10 | `…::test_payload_with_decimal_serialises` |
| 10 | `…::test_does_not_commit` |
| 11 | `api/tests/unit/data/test_repositories.py::test_work_item_by_content_hash` |
| 11 | `…::test_claim_respects_stage_state_and_live_lock` (expired lock is free) |
| 11 | `…::test_history_for_item_ordered` |
| 11 | `…::test_outbox_claim_batch_orders_priority_and_respects_not_before` |
| 11 | `…::test_outbox_mark_published_and_failed` |
| 11 | `…::test_load_all_models_discovers_modules` |
| 11 | `…::test_updated_at_bumps_and_version_increments_on_update` |

Gates for the coder: `uv run ruff check . && uv run ruff format --check .` and `uv run pyright` only.

## Assumptions and deviations

- SQLAlchemy 2.0's Oracle dialect has no built-in JSON type, so `JsonDoc` compiles to native `JSON` through a `UserDefinedType`. If DEV ATP rejects the binding, the fallback is a CLOB with an `IS JSON` check, recorded here. **VERIFY** with the `atp` tests.
- `oracledb.defaults.fetch_decimals = True` is set inside s01's `create_engine` (a one-line edit), not as a side effect of importing a module.
- Some interfaces are added beyond the AC so later stories never edit these repositories: `WorkItemRepository.claim/get_for_update/by_content_hash/children_of`, `OutboxRepository.claim_batch/mark_*`, `HistoryRepository.for_item`, `Page` in `domain/paging.py`, `ModelRole`/`BankFeeBand` in `config_keys.py`, and `HistoryAction`/`SourceKind`/`ActorKind` and the hint TypedDicts in `domain/work_item.py`. s28 imports `ModelRole` from here and doesn't define its own.
- `WorkItem` uses `version_id_col`, so concurrent ORM updates fail loudly (`StaleDataError`). Bulk Core updates must bump `version` themselves.
- `UPDATED_AT`/`CREATED_AT` defaults use `utcnow()` (wall clock), not the injected `Clock`. Tests that need exact times set them explicitly.
- `roll_up` returns `PAYMENT_APPLY_FAILED_SYSTEM` when nothing applies and no candidate fits, for example when every line was reversed (s38). AC5 fixes the status list, so no new status is added.
- Enum columns carry no DB CHECK constraints, so appending an enum value never needs a migration.
- `NOT_BEFORE` is NOT NULL (an index-friendliness choice). `emit` (s03) sets it to now when there's no delay.
- The `atp` fixture reads `CASHAPP_TEST_ATP=1` plus s27 settings. It is skipped otherwise.

## Risks

- `AT` as a column name: not on SQLAlchemy's Oracle reserved list. ATP accepts it unquoted in tests elsewhere, but **VERIFY** in `test_upgrade_downgrade_upgrade_on_dev_atp`.
- With thin mode and a native JSON bind of a `str`, ATP may store the string as a JSON scalar instead of parsing it. If so, `OracleJson` must bind with `DB_TYPE_JSON` via `setinputsizes`, or pass the dict directly. The `atp` round-trip test catches this.
- aiosqlite doesn't exercise SKIP LOCKED or native JSON. Unit-test green is not proof; the `atp` tests run only when DEV credentials exist.
- The status-string grep test may flag legitimate literals that later stories put in docstrings. It checks string constants only via `ast` (docstrings are excluded), with exact equality.
- Every later story's tables must follow the naming rules above (lowercase SQLAlchemy names, no reserved words, names of at most 30 characters). Mergers should check for this.
