# s28-runtime-config-service: plan

Issue #28. Wave 1 spine, step 5 (after s04, before s26). Python only; no web files.

## Standards followed

- CLAUDE.md layering: routers (transmission) → services (rules) → repositories (only ORM code). Routers never import SQLAlchemy; services never import FastAPI (s04's static test covers `cashapp/services/`); repositories flush, never commit; the caller's unit of work owns the transaction.
- `python-web-app:building-python-web-apps`: Pydantic v2 schemas separate from ORM models; shared deps as `Annotated` aliases; one error shape (`ApiError` from s01).
- `python-web-app:wiring-application-config`: one strict validation boundary (`validate_value`), registry-driven closed surface (unknown stored keys ignored with a warning naming the key), no `or`-defaults (falsy values such as `0`, `false`, `null` are real values), defaults deep-copied, never persist a partial object (each key is written whole), `bool` is not accepted where an int/number is expected (strict mode).
- Money: `Decimal` values (tolerances, bank-fee bands, budget) validated through s02's `MoneyStr` / Decimal types and stored in JSON as strings; never `float`.
- Zero-retention rule: any `model_id` containing `fable` (case-insensitive) is rejected (s02's registry validator, re-run by the writer).
- Every human change is auditable: one `CONFIG_CHANGE` row per write, in the same transaction.

## Files to touch (all new; file-disjoint from other stories)

| Path | Purpose |
|---|---|
| `api/alembic/versions/<rev>_s28_config_tables.py` | The one revision: `CONFIG_SETTING`, `CONFIG_CHANGE`. `down_revision` = s04's head (the merger re-points it if needed; `alembic heads` must return one head). |
| `api/src/cashapp/data/models/config.py` | ORM `ConfigSetting`, `ConfigChange`. |
| `api/src/cashapp/data/repositories/config.py` | `ConfigSettingRepository`, `ConfigChangeRepository` (subclass `BaseRepository`). |
| `api/src/cashapp/services/config_groups.py` | Frozen group models (`IntakeConfig` … `DiscountConfig`, `ModelRole`, `BankFeeBand`). Re-exported from `services/config.py`. |
| `api/src/cashapp/services/config.py` | `ConfigStore`, `DbConfigStore`, `ConfigSnapshot`, `RuntimeConfig`, `build_runtime_config`, `validate_value`, `ConfigWriter`, `ConfigAudit`, errors. |
| `api/src/cashapp/services/group_roles.py` | `GroupRoleService` (replace with last-ADMIN guard and audit). |
| `api/src/cashapp/api/schemas/config.py` | Pydantic request/response schemas for both routers. |
| `api/src/cashapp/api/config_deps.py` | `get_runtime_config()` FastAPI dependency and the `RuntimeConfigDep` alias. |
| `api/src/cashapp/api/routers/config.py` | `GET /config`, `GET /config/{key}/history`, `PUT /config/{key}`. Auto-discovered (s01). |
| `api/src/cashapp/api/routers/access.py` | `GET/PUT /access/group-roles`, `GET /access/group-roles/history`. Auto-discovered. |
| `api/tests/support/config.py` | `make_runtime_config(overrides)` + `InMemoryConfigStore` (test-support file owned by this story). |
| `api/tests/services/test_config_runtime.py`, `api/tests/services/test_config_writer.py`, `api/tests/services/test_group_roles_service.py`, `api/tests/api/test_config_api.py`, `api/tests/api/test_access_api.py`, `api/tests/integration/test_config_migration_atp.py` | Tests (written and run only at step 5). |

Not touched: `cashapp/domain/config_keys.py` (s02 owns; read-only here), `cashapp/data/uow.py` (repos reached via `uow.repo(...)`), `cashapp/data/repositories/group_roles.py` and `cashapp/domain/principal.py` (s04), `main.py`, lockfiles.

## Migration

One Alembic revision, upper snake case, DEV ATP only:

- `CONFIG_SETTING`: `KEY VARCHAR2(128)` PK, `VALUE JSON NOT NULL`, `VERSION NUMBER(10) NOT NULL`, `UPDATED_AT TIMESTAMP WITH TIME ZONE NOT NULL`, `UPDATED_BY VARCHAR2(256) NOT NULL`.
- `CONFIG_CHANGE`: `ID` identity PK, `KEY VARCHAR2(128) NOT NULL`, `OLD_VALUE JSON NULL`, `NEW_VALUE JSON NOT NULL`, `CHANGED_BY VARCHAR2(256) NOT NULL`, `CHANGED_BY_NAME VARCHAR2(256) NOT NULL`, `CHANGED_AT TIMESTAMP WITH TIME ZONE NOT NULL`, `REASON VARCHAR2(1000) NOT NULL`; index `IX_CONFIG_CHANGE_KEY_AT (KEY, CHANGED_AT)`.
- No seed rows: a missing row means "registry default", version 0.
- JSON columns use the same JSON type helper s02 uses for `WORK_ITEM` (native JSON on ATP, generic JSON on aiosqlite).
- Downgrade drops both tables.

## Interfaces provided (pinned)

```python
# cashapp/services/config_groups.py  — all frozen (dataclass(frozen=True, slots=True));
# mapping fields are MappingProxyType over deep copies; sequences are tuples.
@dataclass(frozen=True, slots=True)
class ModelRole:  model_id: str; effort: str | None; timeout_s: float
class BankFeeBand: currency: str; min_fee: Decimal; max_fee: Decimal   # reuse s02's type if it defines one
class IntakeConfig: poll_interval_seconds: int
class ReceiptWatcherConfig: poll_interval_seconds: int
class MatchingConfig:
    date_window_days: int
    tolerances: Mapping[str, Decimal]            # currency -> tolerance, "*" fallback
    bank_fee_bands: tuple[BankFeeBand, ...]
    scorer_weights: Mapping[str, float]
    min_score: float
    def tolerance_for(self, currency: str) -> Decimal: ...   # upper-cased lookup, then "*"
class RetriesConfig:
    max_attempts: Mapping[str, int]              # ErrorCode value -> attempts, "*" fallback
    backoff_seconds: tuple[int, ...]
    def max_attempts_for(self, code: ErrorCode) -> int: ...
    def backoff_for(self, attempt: int) -> int: ...          # 1-based; clamps to last entry
class AgingConfig: awaiting_receipt_max_days: int
class EscalationConfig: min_extraction_confidence: float
class ModelsConfig: reader_a: ModelRole; reader_b: ModelRole; adjudicator: ModelRole; workhorse: ModelRole
class ExtractionConfig: fanin_timeout_seconds: int
class ConcurrencyConfig:
    per_stage: Mapping[str, int]; apply_per_receipt: int
    def for_stage(self, stage: Stage) -> int: ...            # "*" fallback
class LocksConfig: lease_minutes: int
class BacklogConfig: rate_limit_per_minute: int
class RetentionConfig: raw_artifact_days: int | None; extraction_days: int | None; history_payload_days: int | None
class BudgetConfig: daily_usd: Decimal | None
class NotificationsConfig:
    recipients: Mapping[str, Mapping[str, tuple[str, ...]]]  # kind -> channel -> addresses/webhooks
    batch_window_seconds: int
class ReportsConfig: daily_summary_cutover: datetime.time
class DiscountConfig: enabled: bool
```

```python
# cashapp/services/config.py
class ConfigError(Exception): ...
class UnknownConfigKey(ConfigError): key: str
class ConfigValidationError(ConfigError): key: str; errors: list[dict[str, Any]]   # pydantic-style loc/msg
class ConfigConflict(ConfigError): key: str; expected_version: int; current_version: int
class ConfigForbidden(ConfigError): ...          # principal lacks Permission.CONFIG_WRITE

@dataclass(frozen=True, slots=True)
class StoredSetting: key: str; value: JsonValue; version: int; updated_at: datetime; updated_by: str

class ConfigStore(Protocol):
    async def load(self) -> Mapping[str, StoredSetting]: ...

class DbConfigStore:                              # the real store; reads in its own UoW, never commits
    def __init__(self, uow_factory: UowFactory) -> None: ...
    async def load(self) -> Mapping[str, StoredSetting]: ...

def lookup_key(name: str) -> ConfigKey[Any]: ...                      # raises UnknownConfigKey
def validate_value(key: ConfigKey[T], value: object) -> T: ...        # TypeAdapter(key.type, strict for bool/int) + key validators (fable rule); raises ConfigValidationError
def to_json(key: ConfigKey[T], value: T) -> JsonValue: ...            # TypeAdapter dump mode="json" (Decimal -> str)

class ConfigSnapshot:                             # immutable; one per event / poll cycle
    taken_at: datetime
    def get(self, key: ConfigKey[T]) -> T: ...
    def version(self, key: ConfigKey[Any]) -> int: ...                # 0 = default
    def intake(self) -> IntakeConfig: ...
    def receipt_watcher(self) -> ReceiptWatcherConfig: ...
    def matching(self) -> MatchingConfig: ...
    def retries(self) -> RetriesConfig: ...
    def aging(self) -> AgingConfig: ...
    def escalation(self) -> EscalationConfig: ...
    def models(self) -> ModelsConfig: ...
    def extraction(self) -> ExtractionConfig: ...
    def concurrency(self) -> ConcurrencyConfig: ...
    def locks(self) -> LocksConfig: ...
    def backlog(self) -> BacklogConfig: ...
    def retention(self) -> RetentionConfig: ...
    def budget(self) -> BudgetConfig: ...
    def notifications(self) -> NotificationsConfig: ...
    def reports(self) -> ReportsConfig: ...
    def discount(self) -> DiscountConfig: ...

class RuntimeConfig:
    def __init__(self, store: ConfigStore, *, ttl_seconds: float = 15.0, clock: Clock | None = None) -> None: ...
    async def snapshot(self) -> ConfigSnapshot: ...    # cached <= ttl_seconds; asyncio.Lock prevents stampede
    async def get(self, key: ConfigKey[T]) -> T: ...
    def invalidate(self) -> None: ...                  # called by the API after a committed write
    # async twins of every snapshot group accessor, each `(await self.snapshot()).<group>()`:
    async def intake(self) -> IntakeConfig: ...        # ... and receipt_watcher, matching, retries, aging,
                                                       # escalation, models, extraction, concurrency, locks,
                                                       # backlog, retention, budget, notifications, reports, discount

def build_runtime_config(uow_factory: UowFactory, *, ttl_seconds: float = 15.0, clock: Clock | None = None) -> RuntimeConfig: ...

class ConfigWriter:
    def __init__(self, clock: Clock | None = None) -> None: ...
    async def set(self, uow: UnitOfWork, key: ConfigKey[Any] | str, value: object,
                  principal: Principal, reason: str, expected_version: int) -> int: ...   # returns new version

class ConfigAudit:
    @staticmethod
    async def record(uow: UnitOfWork, key: str, old: JsonValue | None, new: JsonValue,
                     principal: Principal, reason: str, *, clock: Clock | None = None) -> None: ...
    @staticmethod
    async def history(uow: UnitOfWork, key: str, *, offset: int = 0, limit: int = 50) -> Page[ConfigChange]: ...
```

Consumer rules (pinned for s03, s06–s45):
- Stations get `ctx.config: ConfigSnapshot` (s03 takes `await runtime.snapshot()` once per event) and call the sync accessors: `ctx.config.models().workhorse`.
- Pollers and the worker host hold `RuntimeConfig` (container `config`) and take one snapshot per cycle: `cfg = await container.config.snapshot(); cfg.intake().poll_interval_seconds`. The `await container.config.intake()` twins are equivalent.
- Invalid stored values (schema drift) never crash a station: the snapshot logs a warning naming the key and serves the registry default. Unknown stored keys are ignored with a warning.
- `ConfigAudit.record` keys used by other stories: `access.group_role_map` (here), `aliases` (s37), `retention.purge` (s45). A key need not be in `CONFIG_KEYS`.

```python
# cashapp/services/group_roles.py
@dataclass(frozen=True, slots=True)
class GroupRoleInput: group_name: str; role: Role
GROUP_ROLE_AUDIT_KEY = "access.group_role_map"
class LastAdminMappingRemoved(ConfigError): ...
class GroupRoleService:
    async def current(self, uow: UnitOfWork) -> list[GroupRoleInput]: ...
    async def replace(self, uow: UnitOfWork, mappings: Sequence[GroupRoleInput],
                      principal: Principal, reason: str) -> list[GroupRoleInput]: ...
    # trims/dedupes, sorts by (group_name, role); refuses with LastAdminMappingRemoved when no ADMIN
    # row remains; requires CONFIG_WRITE; calls GroupRoleRepository.replace_all then ConfigAudit.record
    # (old/new = sorted [{group_name, role}]) in the caller's transaction
```

```python
# cashapp/api/config_deps.py
async def get_runtime_config() -> RuntimeConfig   # process singleton, lazily built with build_runtime_config(<API uow factory>)
RuntimeConfigDep = Annotated[RuntimeConfig, Depends(get_runtime_config)]
```

### HTTP contract (for s21 and s31)

All errors use s01's shape `{"error":{code, message, request_id, details}}`.

- `GET /config` (`config:read`) → `200 ConfigEntry[]` (JSON array, registry order):
  `ConfigEntry{key, group, description, value, default, version, updated_by: str|null, updated_by_name: str|null, updated_at: datetime|null, admin_only_write: bool}`. `value` is the effective value (stored or default); version 0 and null `updated_*` mean "default". Decimal values are strings. `updated_by_name` comes from the latest `CONFIG_CHANGE` row (additive field; the UI shows the name).
- `GET /config/{key}/history?offset=0&limit=50` (`config:read`) → `200 {items: ConfigChangeOut[], total, offset, limit}`, newest first; `ConfigChangeOut{id, key, old_value, new_value, changed_by, changed_by_name, changed_at, reason}`. Unknown key → 404 `config_key_not_found`.
- `PUT /config/{key}` (`config:write`) body `ConfigUpdate{value: JsonValue, reason: str (1..1000, trimmed), expected_version: int >= 0}` → `200 ConfigEntry`. 404 `config_key_not_found`; 409 `config_conflict` with `details=[{"current_version": n}]`; 422 `invalid_config_value` with `details=[{"loc": [...], "msg": "..."}]` (includes the fable rule, message "Claude Fable models are not allowed (zero data retention)"); an empty reason is the framework's 422 validation error. After commit the router calls `runtime.invalidate()`.
- `GET /access/group-roles` (`config:read`) → `200 {mappings: [{group_name, role}], updated_by: str|null, updated_at: datetime|null}` (from the latest `access.group_role_map` change row; null before the first change).
- `PUT /access/group-roles` (`config:write`) body `{mappings: [{group_name, role}], reason}` → `200` same shape as GET. No ADMIN mapping left → 422 `last_admin_mapping`. Unknown role → 422 validation error.
- `GET /access/group-roles/history?offset&limit` (`config:read`) → same page shape as config history, key `access.group_role_map`.

### Test support

```python
# api/tests/support/config.py
class InMemoryConfigStore:                         # implements ConfigStore
    def __init__(self, values: Mapping[str, object] = ...) -> None: ...
    def set(self, key: str, value: object) -> None: ...        # validates; bumps version
    async def load(self) -> Mapping[str, StoredSetting]: ...
def make_runtime_config(overrides: Mapping[str, Any] | None = None, *, ttl_seconds: float = 0.0,
                        clock: Clock | None = None) -> RuntimeConfig: ...
def make_config_snapshot(overrides: Mapping[str, Any] | None = None) -> ConfigSnapshot: ...
```
Overrides are validated through `validate_value`; an unknown key raises `UnknownConfigKey` (so a typo in a station test fails loudly). The story's `overrides: dict = {}` signature becomes `Mapping | None = None` (no mutable default; same call shape).

## Write path (ConfigWriter.set)

1. `lookup_key` → 404 mapping. 2. `principal.can(Permission.CONFIG_WRITE)` else `ConfigForbidden` (defence in depth behind `require_permission`). 3. `reason.strip()` non-empty. 4. `validate_value` → `to_json`. 5. `ConfigSettingRepository.get_for_update(key)` (`SELECT … FOR UPDATE`); current version = row.version or 0; mismatch → `ConfigConflict`. 6. Insert (version 1) or update (version + 1, `UPDATED_AT/BY`); a concurrent first insert surfacing as `IntegrityError` maps to `ConfigConflict`. 7. `ConfigAudit.record(uow, key, old_json_or_None, new_json, principal, reason)`. 8. Flush; return new version. Never commits.

Repositories (in `data/repositories/config.py`): `ConfigSettingRepository.all() -> list[ConfigSetting]`, `get_for_update(key) -> ConfigSetting | None`; `ConfigChangeRepository.history(key, offset, limit) -> Page[ConfigChange]`, `latest_by_key(keys: Sequence[str]) -> dict[str, ConfigChange]`.

## TEST PLAN (written and run at step 5 only)

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `tests/integration/test_config_migration_atp.py::test_config_tables_upgrade_downgrade_atp` (`-m atp`) | Upgrade creates both tables with the exact columns/types, JSON native, identity PK; downgrade drops them; `alembic heads` is one head. |
| 1 | `tests/services/test_config_writer.py::test_tables_roundtrip_json_on_sqlite` | Value and old/new JSON (including Decimal-as-string) round-trip through the ORM models. |
| 2 | `tests/services/test_config_runtime.py::test_get_returns_registry_default_when_unset` | Empty store → `get(key)` equals `ConfigKey.default` for every registry key. |
| 2 | `…::test_get_returns_stored_value_validated` | Stored value returned with the key's type (e.g. tolerances become `Decimal`). |
| 2 | `…::test_invalid_stored_value_falls_back_to_default_with_warning` | Bad stored JSON → default + warning naming the key; unknown stored key ignored with warning. |
| 2 | `…::test_every_registry_group_has_an_accessor` | Every `ConfigKey.group` in `CONFIG_KEYS` maps to a snapshot accessor and every key is read by one (closed-surface coverage, both directions). |
| 2 | `…::test_matching_tolerance_for_currency_and_fallback` | `tolerance_for("inr") == Decimal("0.49")`, unknown currency → `"*"` value. |
| 2 | `…::test_retries_max_attempts_for_and_backoff` | `max_attempts_for(code)` falls back to `"*"`; `backoff_for(n)` clamps to the last entry. |
| 2 | `…::test_models_roles_typed` | `models().reader_a == ModelRole("claude-opus-5-5", "high", 120)` etc. |
| 2 | `…::test_group_models_are_frozen` | Attribute assignment and mapping mutation both raise. |
| 2 | `…::test_falsy_values_are_kept` | Stored `0`, `false`, `null` survive (no `or`-default). |
| 3 | `tests/services/test_config_writer.py::test_set_writes_value_and_change_row` | Version 0→1→2; `CONFIG_CHANGE` has who, name, when, old, new, reason; nothing committed by the writer (rollback leaves no rows). |
| 3 | `…::test_set_rejects_stale_expected_version` | `ConfigConflict` with current version; no change row written. |
| 3 | `…::test_set_rejects_invalid_value` | Wrong type, `bool` for int, negative where disallowed → `ConfigValidationError`; nothing written. |
| 3 | `…::test_set_requires_config_write_and_reason` | VIEWER/SYSTEM principal → `ConfigForbidden`; blank reason → `ConfigValidationError`. |
| 3 | `…::test_audit_record_is_public_for_free_text_keys` | `ConfigAudit.record(uow, "access.group_role_map", …)` writes a row; `history` pages newest first. |
| 4 | `tests/services/test_config_runtime.py::test_cache_refreshes_after_ttl` | FrozenClock: change in store invisible before ttl, visible after; default ttl is 15 s. |
| 4 | `…::test_invalidate_forces_reload` | `invalidate()` makes the next snapshot reload. |
| 4 | `…::test_snapshot_is_immutable_and_stable` | A snapshot taken before a change keeps old values; store loaded once under concurrent `snapshot()` calls. |
| 5 | `tests/api/test_config_api.py::test_get_config_lists_every_key` | 200; one entry per `CONFIG_KEYS` key with all fields; requires `config:read` (403 shape otherwise). |
| 5 | `…::test_get_config_history` | Rows newest first, paged; unknown key → 404 error shape. |
| 5 | `…::test_put_config_200_returns_new_entry` | ADMIN token: 200 with version+1, `updated_by_name`; subsequent GET shows the value immediately (invalidate). |
| 5 | `…::test_put_config_409_on_version_conflict` | Stale `expected_version` → 409 `config_conflict` single error shape. |
| 5 | `…::test_put_config_422_on_invalid_value` | 422 `invalid_config_value` with loc/msg details. |
| 5 | `…::test_put_config_403_without_config_write` | OPERATOR → 403 single error shape. |
| 6 | `tests/services/test_config_writer.py::test_fable_model_id_rejected` | `models.workhorse` with `claude-fable-…` (any case) → `ConfigValidationError`. |
| 6 | `tests/api/test_config_api.py::test_put_fable_model_returns_422` | 422 `invalid_config_value`, nothing stored. |
| 7 | `tests/api/test_access_api.py::test_get_group_roles` | 200 `{mappings, updated_by, updated_at}` with the s04 bootstrap row. |
| 7 | `…::test_put_group_roles_replaces_and_audits` | Mapping replaced via `GroupRoleRepository.replace_all`; one `access.group_role_map` change row with sorted old/new, same transaction. |
| 7 | `…::test_put_group_roles_refuses_removing_last_admin` | 422 `last_admin_mapping`; mapping unchanged; no change row. |
| 7 | `…::test_group_roles_history` | History returns the change rows; `config:read` required. |
| 7 | `tests/services/test_group_roles_service.py::test_replace_dedupes_and_rolls_back_on_failure` | Duplicates collapsed; audit failure rolls back the replace (same UoW). |

## Assumptions / deviations

- The issue's "typed accessor for group-to-role mapping" is served by s04's `GroupRoleRepository` plus the `/access/group-roles` endpoints here, audited in `CONFIG_CHANGE` (from story.md).
- `snapshot()` is `async` (it may hit the database); `ConfigSnapshot` carries the sync group accessors that stations use, and `RuntimeConfig` carries async twins. Stories citing `config.intake()` etc. use either form.
- `GET /config` adds `updated_by_name` (derived from the latest change row) so the UI can show a name without a schema change; `updated_by` stays the subject.
- `admin_only_write` is surfaced as data; writes of every key require `config:write` (ADMIN-only per s04's role map).
- `BankFeeBand{currency, min_fee, max_fee}` is pinned here unless s02's `config_keys.py` already types the band; then s28 reuses s02's type.
- Pydantic schemas live in a new `cashapp/api/schemas/config.py` (no schemas location pinned by s01).
- The API needs a UoW per request. If s02/s04 pin a request UoW dependency (s04's `current_principal` must reach `GroupRoleRepository`), routers use it; otherwise `config_deps.py` builds the factory once from `get_settings()` and s01's `create_engine`, and the merger reconciles to one dependency.
- `make_runtime_config` takes `Mapping | None = None` instead of a mutable `{}` default; ttl defaults to 0 in tests.
- `PUT /access/group-roles` takes no `expected_version` (not in the AC); last-writer-wins, every write audited.

## Risks

- `KEY` and `VALUE` are Oracle keywords (non-reserved); if ATP rejects them unquoted, the ORM quotes them. The `-m atp` migration test confirms.
- JSON column type on aiosqlite vs ATP must come from s02's shared helper; a divergent type would make unit tests pass and ATP fail.
- `SELECT … FOR UPDATE` on a missing row locks nothing; two concurrent first writes rely on the PK unique violation → `ConfigConflict` mapping.
- Workers see a change up to 15 s late (accepted: "within one poll or event").
- The group-role replace has no optimistic lock; two admins saving at once both succeed (audited). Revisit if s21 needs conflict detection.
- ConfigKey type strictness: `bool` passing as `int` must be blocked by strict validation; covered by `test_set_rejects_invalid_value`.
