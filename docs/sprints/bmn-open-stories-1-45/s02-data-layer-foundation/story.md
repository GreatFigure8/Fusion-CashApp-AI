# s02-data-layer-foundation: Data layer foundation and the shared registries

- Issue: #2
- Wave: 1 (serialized spine, step 3 of 6)
- breaking: false

## Story

As every later station and screen, I want one data layer (generic repository, unit of work, core tables) and one module each for statuses, stages, error codes, money and config keys, so that nothing is defined twice (CLAUDE.md non-negotiable 7).

## Context

research.md wave 0 step 3, plus the a6 rails: oracledb `fetch_decimals=True`, `Numeric(asdecimal=True)`, money serialised as strings. These registries are created COMPLETE here (every value later stories need is listed below), so later stories import them and rarely edit them; if one must append, it appends only. Reference doc §5 is the source for statuses.

## Acceptance criteria

1. [unit] `cashapp/data/repository.py`: `BaseRepository[ModelT]` with `get(id) -> ModelT | None`, `list(*, where: Sequence[ColumnElement[bool]] = (), order_by=(), offset=0, limit=50) -> Page[ModelT]` (`Page{items, total, offset, limit}`), `add(entity) -> ModelT`, `update(entity, **changes) -> ModelT`, `delete(entity)`, and `select_for_update_skip_locked(stmt, limit) -> list[ModelT]`. Repositories flush, never commit. A static check test asserts no `commit(` call under `cashapp/data/repositories/` and no `sqlalchemy` import outside `cashapp/data/` and `alembic/`.
2. [unit] `cashapp/data/uow.py`: `UnitOfWork` (async context manager) exposing `session`, `work_items`, `history`, `outbox`, `repo(cls: type[R]) -> R` (instantiates any repository on the same session, so later stories never edit the UoW), `commit()`, `rollback()`; leaving the block without commit rolls back. `UowFactory = Callable[[], UnitOfWork]`, built by `make_uow_factory(engine)`.
3. [integration] One Alembic base revision creates `WORK_ITEM`, `WORK_ITEM_HISTORY`, `OUTBOX` (identity PKs, upper snake case, JSON columns native on ATP) with exactly these columns:
   - `WORK_ITEM`: ID, PARENT_ID (FK self, null), SOURCE_KIND (MAILBOX|FOLDER|BACKLOG|MANUAL), SOURCE_REF, CONTENT_HASH (char 64), ARTIFACT_KEY, STAGE, STATE, ATTEMPTS, LAST_ERROR_CODE, LAST_ERROR_DETAIL (JSON), ESCALATION_SUMMARY (CLOB), CLAIM_EXPIRES_AT, LOCK_OWNER, LOCK_OWNER_NAME, LOCK_ACQUIRED_AT, LOCK_EXPIRES_AT, PAYER_NAME, CUSTOMER_ACCOUNT_NUMBER, CURRENCY (char 3), PAYMENT_AMOUNT NUMBER(18,2), PAYMENT_DATE, PAYMENT_STATUS, INFO_FLAGS (JSON array), HUMAN_HINTS (JSON), BATCH_ID (null, no FK yet), PRIORITY (int, live=100), AWAITING_SINCE, VERSION, CREATED_AT, UPDATED_AT. Unique (CONTENT_HASH, PARENT_ID) nulls-distinct; indexes on (STAGE, STATE), (STATE, AWAITING_SINCE), LOCK_OWNER.
   - `WORK_ITEM_HISTORY`: ID, WORK_ITEM_ID, AT, ACTOR_KIND (SYSTEM|USER), ACTOR_ID, ACTOR_NAME, ACTION (STAGE_TRANSITION|AUTOFIX_ATTEMPT|HUMAN_ACTION|FUSION_WRITE|DECISION|LOCK), FROM_STAGE, TO_STAGE, FROM_STATE, TO_STATE, ERROR_CODE, REASONING (CLOB), PAYLOAD (JSON), PURGED_AT.
   - `OUTBOX`: ID, TOPIC, MSG_KEY, PAYLOAD (JSON), PRIORITY, NOT_BEFORE, CREATED_AT, PUBLISHED_AT, ATTEMPTS, LAST_ERROR.
   On ATP the migration applies and downgrades cleanly (`-m atp`, DEV schema only); `alembic heads` returns one head.
4. [unit] `cashapp/domain/stages.py`: `Stage` StrEnum INTAKE, CLASSIFY, EXTRACT, ADJUDICATE, VALIDATE, RESOLVE_CUSTOMER, FAST_PATH, MATCH_RECEIPT, MATCH_LINES, APPLY, WRITE_BACK, DONE, and `PIPELINE_ORDER`. `ItemState` StrEnum PENDING, IN_PROGRESS, AWAITING_RECEIPT, ESCALATED, DONE, ARCHIVED.
5. [unit] `cashapp/domain/status.py` is the ONLY definition of: `PaymentStatus` (payment-success, payment-less-than-total-due-success, payment-more-than-total-due-success, payment-previously-applied, invoice-not-found, customer-not-found, missing-payment-date, receipt-not-found, zero-amount, payment-apply-failed-system, payment-apply-failed-receipt-closed, payment-apply-failed-zero-balance); `PAYMENT_FAILURE_PRECEDENCE` (invoice-not-found > customer-not-found > missing-payment-date > receipt-not-found > zero-amount > payment-apply-failed-*); `LineStatus` (allocation-applied, allocation-applied-short-pay, allocation-applied-less-than-instruction, allocation-applied-with-discount, allocation-previously-applied, allocation-invoice-not-found, allocation-customer-not-found, allocation-no-remaining-balance, allocation-zero-amount, allocation-missing-payment-date, allocation-no-receipt-match, allocation-apply-failed, allocation-reversed, allocation-dry-run); `InfoFlag` (payment-header-line-mismatch, multiple-accounts-same-receipt, discount-rejected-by-fusion, currency-resolved-from-customer, alias-used); `roll_up(header: HeaderResult, lines: Sequence[LineStatus]) -> PaymentStatus` derived strictly from header and line results; `ExceptionInfo` dataclass `{type, error_code, reason, severity, title, detail, error_details}` with every key always present. A test asserts no other module defines these string values (grep over `cashapp/`).
6. [unit] `cashapp/domain/error_codes.py`: `ErrorCode` StrEnum with `ErrorSpec{category: TRANSIENT|DATA|AMBIGUITY|POLICY|SYSTEM, retryable: bool, always_person: bool, description}` for: RECEIPT_NOT_YET_AVAILABLE, RECEIPT_AMBIGUOUS, RECEIPT_RESERVED, AMOUNT_VARIANCE, CUSTOMER_NOT_FOUND, CUSTOMER_MULTIPLE_ACCOUNTS, INVOICE_NOT_FOUND, INVOICE_CLOSED, INVOICE_CURRENCY_MISMATCH, INVOICE_STATUS_INVALID, INVALID_INVOICE_NUMBER, INVALID_DATE, INVALID_CURRENCY, MISSING_PAYMENT_DATE, ZERO_AMOUNT_LINE, LOW_EXTRACTION_CONFIDENCE, EXTRACTION_FAILED, CLASSIFICATION_FAILED, LLM_REFUSAL, LLM_TRANSIENT, UNSUPPORTED_ARTIFACT, FUSION_OVERAPPLY, FUSION_ALREADY_APPLIED, FUSION_LOCKED, FUSION_TRANSIENT, FUSION_GL_DATE, FUSION_FAULT, FUSION_DISCOUNT_REJECTED, FUSION_WRITE_DISABLED, WRITE_BACK_FAILED, REVERSAL_FAILED, AGED_OUT, PREPAYMENT, PO_SO_ERS_ONLY, DUAL_CURRENCY, UNGROUNDED, SYSTEM_DEAD_LETTER. Only FUSION_LOCKED, FUSION_TRANSIENT, LLM_TRANSIENT are `retryable`; PREPAYMENT, PO_SO_ERS_ONLY, DUAL_CURRENCY, UNGROUNDED are `always_person`.
7. [unit] `cashapp/domain/money.py`: `Money(amount: Decimal, currency: str)` frozen; `to_money(value) -> Decimal` quantised to 2 dp with `ROUND_HALF_UP` (never `round`); `money_eq(a, b) -> bool` is `|a − b| ≤ 0.005`; arithmetic refuses mixed currencies; Pydantic annotated type `MoneyStr` serialises Decimal as a string in JSON and OpenAPI. Tests cover 2.675 → 2.68, 0.005 equality boundary, mixed-currency error.
8. [unit] `cashapp/domain/config_keys.py`: `ConfigKey[T]{name, group, type, default, description, admin_only_write=True}` registry `CONFIG_KEYS` holding every key (defaults in brackets): intake.poll_interval_seconds [300], receipt_watcher.poll_interval_seconds [300], matching.date_window_days [5], matching.tolerances {USD:0.10, EUR:0.10, INR:0.49, "*":0.10}, matching.bank_fee_bands [[]], matching.scorer_weights [{}], matching.min_score [0.0], retries.max_attempts {"*":3}, retries.backoff_seconds [[30,120,600]], aging.awaiting_receipt_max_days [30], escalation.min_extraction_confidence [0.8], models.reader_a {model_id:"claude-opus-5-5", effort:"high", timeout_s:120}, models.reader_b {model_id:"cohere.command-a-vision", effort:null, timeout_s:120}, models.adjudicator {model_id:"claude-opus-5-5", effort:"medium", timeout_s:120}, models.workhorse {model_id:"claude-haiku-5-5", effort:"low", timeout_s:60}, extraction.fanin_timeout_seconds [180], concurrency.per_stage {"*":4}, concurrency.apply_per_receipt [1], locks.lease_minutes [30], backlog.rate_limit_per_minute [20], retention.raw_artifact_days [null], retention.extraction_days [null], retention.history_payload_days [null], budget.daily_usd [null], notifications.recipients [{}], notifications.batch_window_seconds [300], reports.daily_summary_cutover [ "07:00" ], discount.enabled [false]. A validator rejects any model_id containing "fable".
9. [unit] `cashapp/domain/clock.py`: `Clock` Protocol (`now() -> datetime` UTC) with `SystemClock`.
10. [unit] `cashapp/services/history.py`: `record_history(uow, item_id, entry: HistoryEntry)` — the one writer of history rows, used by every story; `HistoryEntry` mirrors the columns.
11. [unit] `cashapp/data/models/` holds one module per domain area (`work_item.py`, `outbox.py`); `WorkItemRepository`, `HistoryRepository`, `OutboxRepository` subclass the base and add only entity-specific queries. Later stories add NEW repository modules under `cashapp/data/repositories/` rather than editing these.

## Out of scope

Runtime config service (s28), StageRunner and relay (s03), locking service (s40).

## Deps

- s01-scaffold-monorepo — `create_engine`, Alembic env. plannable.
- s27-settings-secrets-wiring — `get_settings().atp`. plannable.

## Lifecycle pinned here (who moves each state)

PENDING: intake (s06/s34/s35), StageRunner success (s03), auto-fix retry/reroute (s18), human requeue (s18), receipt wake (s14), classification override (s07). IN_PROGRESS: StageRunner claim (s03); exits on persist, failure, or claim expiry (recovered to PENDING by s30 at startup). AWAITING_RECEIPT: s18 handler for RECEIPT_NOT_YET_AVAILABLE; exits s14 wake → PENDING, s14 aging → ESCALATED. ESCALATED: s18, s14 (aging), s38 (after reversal); exit: s18 requeue. DONE: s17 write-back, s16 fast path. ARCHIVED: s07 (not remittance), s34 (envelope parent). Lock fields: s40 only. Claim fields: s03 only.

## Test-support files owned

`api/tests/support/db.py` (aiosqlite async engine + UoW fixture for unit tests; `atp` fixture using DEV DSN, skipped without it), `api/tests/support/factories.py` (`make_work_item(**overrides)`), `api/tests/support/clock.py` (`FrozenClock`).

## Assumptions

- Unit tests run on aiosqlite; Oracle-only behaviour (SKIP LOCKED, JSON) is covered by `-m atp` integration tests against DEV ATP.
- All registries are created complete now so parallel stories don't conflict editing them.
