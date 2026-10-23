"""Runtime configuration: validated reads, a TTL cache with immutable snapshots, audited writes.

Keys and defaults live in the registry (`cashapp.domain.config_keys`). This module is the only
place that reads or writes stored overrides. A missing row means "registry default, version 0".
"""

import asyncio
import copy
import datetime
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Protocol, cast

from pydantic import JsonValue, ValidationError

from cashapp.data.models.config import ConfigChange, ConfigSetting
from cashapp.data.repositories.config import (
    ConfigChangeRepository,
    ConfigSettingRepository,
    DuplicateConfigKeyError,
)
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain import config_keys as ck
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.config_keys import CONFIG_GROUPS, CONFIG_KEYS, ConfigKey
from cashapp.domain.paging import Page
from cashapp.domain.principal import Permission, Principal
from cashapp.services.config_groups import (
    WILDCARD,
    AgingConfig,
    BacklogConfig,
    BudgetConfig,
    ConcurrencyConfig,
    DiscountConfig,
    EscalationConfig,
    ExtractionConfig,
    IntakeConfig,
    LocksConfig,
    MatchingConfig,
    ModelRole,
    ModelsConfig,
    NotificationsConfig,
    ReceiptWatcherConfig,
    ReportsConfig,
    RetentionConfig,
    RetriesConfig,
)

logger = logging.getLogger(__name__)

FABLE_MESSAGE = "Claude Fable models are not allowed (zero data retention)"
MAX_REASON_LENGTH = 1000
RESTART_NOTE = " [takes effect on restart]"
DEFAULT_TTL_SECONDS = 15.0

type ErrorDict = dict[str, Any]


# --------------------------------------------------------------------------- errors


class ConfigError(Exception):
    """Base class for configuration service errors."""


class UnknownConfigKey(ConfigError):  # noqa: N818
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Unknown config key {key!r}")


class ConfigValidationError(ConfigError):
    def __init__(self, key: str, errors: list[ErrorDict]) -> None:
        self.key = key
        self.errors = errors
        summary = "; ".join(str(e.get("msg", "")) for e in errors)
        super().__init__(f"Invalid value for config key {key!r}: {summary}")


class ConfigConflict(ConfigError):  # noqa: N818
    def __init__(self, key: str, expected_version: int, current_version: int) -> None:
        self.key = key
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            f"Config key {key!r} is at version {current_version}, not {expected_version}"
        )


class ConfigForbidden(ConfigError):  # noqa: N818
    """The principal lacks Permission.CONFIG_WRITE."""


# --------------------------------------------------------------------------- validation


def lookup_key(name: str) -> ConfigKey[Any]:
    key = CONFIG_KEYS.get(name)
    if key is None:
        raise UnknownConfigKey(name)
    return key


def _clean_message(msg: str) -> str:
    cleaned = msg.removeprefix("Value error, ")
    return FABLE_MESSAGE if "fable" in cleaned.lower() else cleaned


def _pydantic_errors(exc: ValidationError) -> list[ErrorDict]:
    return [
        {"loc": list(err["loc"]), "msg": _clean_message(str(err["msg"]))} for err in exc.errors()
    ]


def _bool_leaks(raw: object, dumped: object, loc: list[str | int]) -> list[ErrorDict]:
    """Find places where a bool was accepted as a number (pydantic lax mode allows it)."""
    if isinstance(raw, bool):
        if isinstance(dumped, bool):
            return []
        return [{"loc": loc, "msg": "A boolean is not a valid number"}]
    found: list[ErrorDict] = []
    if isinstance(raw, Mapping) and isinstance(dumped, Mapping):
        raw_map = cast(Mapping[Any, Any], raw)
        dumped_map = cast(Mapping[Any, Any], dumped)
        for name, item in raw_map.items():
            if name in dumped_map:
                found.extend(_bool_leaks(item, dumped_map[name], [*loc, str(name)]))
    elif isinstance(raw, list | tuple) and isinstance(dumped, list):
        raw_list = cast(list[Any], raw)
        dumped_list = cast(list[Any], dumped)
        for index, (item, out) in enumerate(zip(raw_list, dumped_list, strict=False)):
            found.extend(_bool_leaks(item, out, [*loc, index]))
    return found


def _fail(msg: str, *loc: str | int) -> ErrorDict:
    return {"loc": list(loc), "msg": msg}


def _check_non_negative_map(value: Mapping[str, Any], *, minimum: float) -> list[ErrorDict]:
    return [
        _fail(f"Must be at least {minimum:g}", name)
        for name, item in value.items()
        if item < minimum
    ]


def _check_cutover(value: str) -> list[ErrorDict]:
    hours, minutes = (int(part) for part in value.split(":"))
    if hours > 23 or minutes > 59:
        return [_fail("Must be a time of day, HH:MM (00:00 to 23:59)")]
    return []


def _min_int(minimum: int) -> Callable[[Any], list[ErrorDict]]:
    def check(value: Any) -> list[ErrorDict]:
        if value is None or value >= minimum:
            return []
        return [_fail(f"Must be at least {minimum}")]

    return check


def _model_role(value: ck.ModelRole) -> list[ErrorDict]:
    return [_fail(FABLE_MESSAGE, "model_id")] if "fable" in value.model_id.lower() else []


def _map_with_wildcard(minimum: float) -> Callable[[Any], list[ErrorDict]]:
    def check(value: Mapping[str, Any]) -> list[ErrorDict]:
        errors = _check_non_negative_map(value, minimum=minimum)
        if WILDCARD not in value:
            errors.append(_fail(f'The "{WILDCARD}" fallback entry is required'))
        return errors

    return check


def _backoff(value: list[int]) -> list[ErrorDict]:
    if not value:
        return [_fail("At least one backoff delay is required")]
    return [_fail("Must be at least 0", i) for i, item in enumerate(value) if item < 0]


def _fraction(value: float) -> list[ErrorDict]:
    return [] if 0.0 <= value <= 1.0 else [_fail("Must be between 0 and 1")]


def _non_negative_number(value: Any) -> list[ErrorDict]:
    return [] if value is None or value >= 0 else [_fail("Must not be negative")]


def _fee_bands(value: list[ck.BankFeeBand]) -> list[ErrorDict]:
    return [
        _fail("min_fee must not exceed max_fee", i)
        for i, band in enumerate(value)
        if band.min_fee > band.max_fee
    ]


def _weights(value: Mapping[str, float]) -> list[ErrorDict]:
    return _check_non_negative_map(value, minimum=0)


def _tolerances(value: Mapping[str, Decimal]) -> list[ErrorDict]:
    errors = _map_with_wildcard(0)(value)
    errors.extend(
        _fail("Currency must be an upper-case code or *", name)
        for name in value
        if name != name.upper()
    )
    return errors


# Business rules the registry's types cannot express, keyed by config key name.
_EXTRA_CHECKS: Mapping[str, Callable[[Any], list[ErrorDict]]] = MappingProxyType(
    {
        ck.INTAKE_POLL_INTERVAL_SECONDS.name: _min_int(1),
        ck.RECEIPT_WATCHER_POLL_INTERVAL_SECONDS.name: _min_int(1),
        ck.MATCHING_DATE_WINDOW_DAYS.name: _min_int(0),
        ck.MATCHING_TOLERANCES.name: _tolerances,
        ck.MATCHING_BANK_FEE_BANDS.name: _fee_bands,
        ck.MATCHING_SCORER_WEIGHTS.name: _weights,
        ck.MATCHING_MIN_SCORE.name: _non_negative_number,
        ck.RETRIES_MAX_ATTEMPTS.name: _map_with_wildcard(0),
        ck.RETRIES_BACKOFF_SECONDS.name: _backoff,
        ck.AGING_AWAITING_RECEIPT_MAX_DAYS.name: _min_int(1),
        ck.ESCALATION_MIN_EXTRACTION_CONFIDENCE.name: _fraction,
        ck.MODELS_READER_A.name: _model_role,
        ck.MODELS_READER_B.name: _model_role,
        ck.MODELS_ADJUDICATOR.name: _model_role,
        ck.MODELS_WORKHORSE.name: _model_role,
        ck.EXTRACTION_FANIN_TIMEOUT_SECONDS.name: _min_int(1),
        ck.CONCURRENCY_PER_STAGE.name: _map_with_wildcard(1),
        ck.CONCURRENCY_APPLY_PER_RECEIPT.name: _min_int(1),
        ck.LOCKS_LEASE_MINUTES.name: _min_int(1),
        ck.BACKLOG_RATE_LIMIT_PER_MINUTE.name: _min_int(1),
        ck.RETENTION_RAW_ARTIFACT_DAYS.name: _min_int(1),
        ck.RETENTION_EXTRACTION_DAYS.name: _min_int(1),
        ck.RETENTION_HISTORY_PAYLOAD_DAYS.name: _min_int(1),
        ck.BUDGET_DAILY_USD.name: _non_negative_number,
        ck.NOTIFICATIONS_BATCH_WINDOW_SECONDS.name: _min_int(0),
        ck.REPORTS_DAILY_SUMMARY_CUTOVER.name: _check_cutover,
    }
)


def validate_value[T](key: ConfigKey[T], value: object) -> T:
    """The one validation boundary: registry type, no bool-as-number, key business rules."""
    try:
        result = key.validate(value)
    except ValidationError as exc:
        raise ConfigValidationError(key.name, _pydantic_errors(exc)) from exc
    except ValueError as exc:
        raise ConfigValidationError(key.name, [_fail(_clean_message(str(exc)))]) from exc
    errors = _bool_leaks(value, key.dump(result), [])
    check = _EXTRA_CHECKS.get(key.name)
    if not errors and check is not None:
        errors = check(result)
    if errors:
        raise ConfigValidationError(key.name, errors)
    return result


def to_json[T](key: ConfigKey[T], value: T) -> JsonValue:
    """The JSON form stored in the database (Decimal becomes a string)."""
    return cast(JsonValue, key.dump(value))


def normalize_reason(key: str, reason: str, *, suffix: str = "") -> str:
    """Trim and check a reason; `suffix` is appended after the length check is applied to the
    text, so the stored reason stays within the limit."""
    cleaned = reason.strip()
    if not cleaned:
        raise ConfigValidationError(key, [_fail("A reason is required", "reason")])
    if len(cleaned) > MAX_REASON_LENGTH:
        raise ConfigValidationError(
            key, [_fail(f"Reason must be at most {MAX_REASON_LENGTH} characters", "reason")]
        )
    if suffix:
        cleaned = cleaned[: MAX_REASON_LENGTH - len(suffix)] + suffix
    return cleaned


# --------------------------------------------------------------------------- store + snapshot


@dataclass(frozen=True, slots=True)
class StoredSetting:
    key: str
    value: JsonValue
    version: int
    updated_at: datetime.datetime
    updated_by: str


class ConfigStore(Protocol):
    async def load(self) -> Mapping[str, StoredSetting]: ...


class DbConfigStore:
    """Reads every stored override in its own unit of work; never commits."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def load(self) -> Mapping[str, StoredSetting]:
        async with self._uow_factory() as uow:
            rows = await uow.repo(ConfigSettingRepository).all()
        return {
            row.key: StoredSetting(
                key=row.key,
                value=cast(JsonValue, row.value),
                version=row.version,
                updated_at=row.updated_at,
                updated_by=row.updated_by,
            )
            for row in rows
        }


def effective_value[T](key: ConfigKey[T], stored: StoredSetting | None) -> tuple[T, int]:
    """Validated stored value (or a private copy of the default) plus its version.

    A stored value that no longer validates (schema drift) never crashes a reader: the
    default is served and a warning names the key.
    """
    if stored is not None:
        try:
            return validate_value(key, stored.value), stored.version
        except ConfigValidationError as exc:
            logger.warning("Stored config %r is invalid (%s); using the default", key.name, exc)
    return copy.deepcopy(key.default), 0


def _model_role_of(role: ck.ModelRole) -> ModelRole:
    return ModelRole(role.model_id, role.effort, float(role.timeout_s))


def _channel_of(address: str) -> str:
    return "webhook" if address.lower().startswith(("http://", "https://")) else "email"


def _recipients(raw: Mapping[str, list[str]]) -> dict[str, dict[str, tuple[str, ...]]]:
    """Registry form is kind -> addresses; split each kind's addresses by channel."""
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    for kind, addresses in raw.items():
        channels: dict[str, list[str]] = {}
        for address in addresses:
            channels.setdefault(_channel_of(address), []).append(address)
        result[kind] = {channel: tuple(items) for channel, items in channels.items()}
    return result


class ConfigSnapshot:
    """An immutable view of every key, taken once per event or poll cycle."""

    def __init__(
        self, stored: Mapping[str, StoredSetting], taken_at: datetime.datetime | None = None
    ) -> None:
        for name in stored:
            if name not in CONFIG_KEYS:
                logger.warning("Ignoring unknown stored config key %r", name)
        values: dict[str, Any] = {}
        versions: dict[str, int] = {}
        for name, key in CONFIG_KEYS.items():
            values[name], versions[name] = effective_value(key, stored.get(name))
        self._values: Mapping[str, Any] = MappingProxyType(values)
        self._versions: Mapping[str, int] = MappingProxyType(versions)
        self.taken_at = taken_at if taken_at is not None else SystemClock().now()

    def get[T](self, key: ConfigKey[T]) -> T:
        if key.name in self._values:
            return cast(T, self._values[key.name])
        return copy.deepcopy(key.default)

    def version(self, key: ConfigKey[Any]) -> int:
        """Stored version of `key`; 0 means the registry default is in effect."""
        return self._versions.get(key.name, 0)

    def intake(self) -> IntakeConfig:
        return IntakeConfig(self.get(ck.INTAKE_POLL_INTERVAL_SECONDS))

    def receipt_watcher(self) -> ReceiptWatcherConfig:
        return ReceiptWatcherConfig(self.get(ck.RECEIPT_WATCHER_POLL_INTERVAL_SECONDS))

    def matching(self) -> MatchingConfig:
        return MatchingConfig(
            date_window_days=self.get(ck.MATCHING_DATE_WINDOW_DAYS),
            tolerances=self.get(ck.MATCHING_TOLERANCES),
            bank_fee_bands=tuple(self.get(ck.MATCHING_BANK_FEE_BANDS)),
            scorer_weights=self.get(ck.MATCHING_SCORER_WEIGHTS),
            min_score=self.get(ck.MATCHING_MIN_SCORE),
        )

    def retries(self) -> RetriesConfig:
        return RetriesConfig(
            max_attempts=self.get(ck.RETRIES_MAX_ATTEMPTS),
            backoff_seconds=tuple(self.get(ck.RETRIES_BACKOFF_SECONDS)),
        )

    def aging(self) -> AgingConfig:
        return AgingConfig(self.get(ck.AGING_AWAITING_RECEIPT_MAX_DAYS))

    def escalation(self) -> EscalationConfig:
        return EscalationConfig(self.get(ck.ESCALATION_MIN_EXTRACTION_CONFIDENCE))

    def models(self) -> ModelsConfig:
        return ModelsConfig(
            reader_a=_model_role_of(self.get(ck.MODELS_READER_A)),
            reader_b=_model_role_of(self.get(ck.MODELS_READER_B)),
            adjudicator=_model_role_of(self.get(ck.MODELS_ADJUDICATOR)),
            workhorse=_model_role_of(self.get(ck.MODELS_WORKHORSE)),
        )

    def extraction(self) -> ExtractionConfig:
        return ExtractionConfig(self.get(ck.EXTRACTION_FANIN_TIMEOUT_SECONDS))

    def concurrency(self) -> ConcurrencyConfig:
        return ConcurrencyConfig(
            per_stage=self.get(ck.CONCURRENCY_PER_STAGE),
            apply_per_receipt=self.get(ck.CONCURRENCY_APPLY_PER_RECEIPT),
        )

    def locks(self) -> LocksConfig:
        return LocksConfig(self.get(ck.LOCKS_LEASE_MINUTES))

    def backlog(self) -> BacklogConfig:
        return BacklogConfig(self.get(ck.BACKLOG_RATE_LIMIT_PER_MINUTE))

    def retention(self) -> RetentionConfig:
        return RetentionConfig(
            raw_artifact_days=self.get(ck.RETENTION_RAW_ARTIFACT_DAYS),
            extraction_days=self.get(ck.RETENTION_EXTRACTION_DAYS),
            history_payload_days=self.get(ck.RETENTION_HISTORY_PAYLOAD_DAYS),
        )

    def budget(self) -> BudgetConfig:
        return BudgetConfig(self.get(ck.BUDGET_DAILY_USD))

    def notifications(self) -> NotificationsConfig:
        return NotificationsConfig(
            recipients=_recipients(self.get(ck.NOTIFICATIONS_RECIPIENTS)),
            batch_window_seconds=self.get(ck.NOTIFICATIONS_BATCH_WINDOW_SECONDS),
        )

    def reports(self) -> ReportsConfig:
        return ReportsConfig(
            datetime.time.fromisoformat(self.get(ck.REPORTS_DAILY_SUMMARY_CUTOVER))
        )

    def discount(self) -> DiscountConfig:
        return DiscountConfig(self.get(ck.DISCOUNT_ENABLED))


class RuntimeConfig:
    """Cached access to configuration: values are at most `ttl_seconds` old."""

    def __init__(
        self,
        store: ConfigStore,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._ttl = ttl_seconds
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._lock = asyncio.Lock()
        self._snapshot: ConfigSnapshot | None = None
        self._generation = 0

    def _fresh(self) -> ConfigSnapshot | None:
        snap = self._snapshot
        if snap is None:
            return None
        age = (self._clock.now() - snap.taken_at).total_seconds()
        return snap if 0 <= age < self._ttl else None

    async def snapshot(self) -> ConfigSnapshot:
        cached = self._fresh()
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._fresh()
            if cached is not None:
                return cached
            generation = self._generation
            try:
                stored = await self._store.load()
            except Exception:
                if self._snapshot is None:
                    raise
                logger.warning("Config reload failed; serving the previous snapshot", exc_info=True)
                return self._snapshot
            fresh = ConfigSnapshot(stored, self._clock.now())
            if generation == self._generation:
                self._snapshot = fresh
            return fresh

    async def get[T](self, key: ConfigKey[T]) -> T:
        return (await self.snapshot()).get(key)

    def invalidate(self) -> None:
        """Drop the cache; the next read reloads. Call after a committed write."""
        self._generation += 1
        self._snapshot = None

    async def intake(self) -> IntakeConfig:
        return (await self.snapshot()).intake()

    async def receipt_watcher(self) -> ReceiptWatcherConfig:
        return (await self.snapshot()).receipt_watcher()

    async def matching(self) -> MatchingConfig:
        return (await self.snapshot()).matching()

    async def retries(self) -> RetriesConfig:
        return (await self.snapshot()).retries()

    async def aging(self) -> AgingConfig:
        return (await self.snapshot()).aging()

    async def escalation(self) -> EscalationConfig:
        return (await self.snapshot()).escalation()

    async def models(self) -> ModelsConfig:
        return (await self.snapshot()).models()

    async def extraction(self) -> ExtractionConfig:
        return (await self.snapshot()).extraction()

    async def concurrency(self) -> ConcurrencyConfig:
        return (await self.snapshot()).concurrency()

    async def locks(self) -> LocksConfig:
        return (await self.snapshot()).locks()

    async def backlog(self) -> BacklogConfig:
        return (await self.snapshot()).backlog()

    async def retention(self) -> RetentionConfig:
        return (await self.snapshot()).retention()

    async def budget(self) -> BudgetConfig:
        return (await self.snapshot()).budget()

    async def notifications(self) -> NotificationsConfig:
        return (await self.snapshot()).notifications()

    async def reports(self) -> ReportsConfig:
        return (await self.snapshot()).reports()

    async def discount(self) -> DiscountConfig:
        return (await self.snapshot()).discount()


def build_runtime_config(
    uow_factory: UowFactory,
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    clock: Clock | None = None,
) -> RuntimeConfig:
    return RuntimeConfig(DbConfigStore(uow_factory), ttl_seconds=ttl_seconds, clock=clock)


# --------------------------------------------------------------------------- audit + writer


class ConfigAudit:
    """The change log. Public so other services can audit their own keys (a key need not be
    in the registry, e.g. "access.group_role_map")."""

    @staticmethod
    async def record(
        uow: UnitOfWork,
        key: str,
        old: JsonValue | None,
        new: JsonValue,
        principal: Principal,
        reason: str,
        *,
        clock: Clock | None = None,
    ) -> None:
        now = (clock if clock is not None else SystemClock()).now()
        await uow.repo(ConfigChangeRepository).add(
            ConfigChange(
                key=key,
                old_value=old,
                new_value=new,
                changed_by=principal.subject,
                changed_by_name=principal.display_name,
                changed_at=now,
                reason=normalize_reason(key, reason),
            )
        )

    @staticmethod
    async def history(
        uow: UnitOfWork, key: str, *, offset: int = 0, limit: int = 50
    ) -> Page[ConfigChange]:
        return await uow.repo(ConfigChangeRepository).history(key, offset, limit)


class ConfigWriter:
    """Validated, versioned, audited writes. Never commits: the caller owns the transaction."""

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def set(
        self,
        uow: UnitOfWork,
        key: ConfigKey[Any] | str,
        value: object,
        principal: Principal,
        reason: str,
        expected_version: int,
        *,
        permission: Permission = Permission.CONFIG_WRITE,
    ) -> int:
        """Write `value` if the stored version is `expected_version`; return the new version.

        ``permission`` is what the caller must hold: config:write by default, engine:control for
        the engine's own keys.
        """
        registry_key = lookup_key(key if isinstance(key, str) else key.name)
        if not principal.can(permission):
            raise ConfigForbidden(f"Missing permission {permission.value}")
        cleaned_reason = normalize_reason(
            registry_key.name,
            reason,
            suffix=RESTART_NOTE if registry_key.restart_required else "",
        )
        new_json = to_json(registry_key, validate_value(registry_key, value))

        repo = uow.repo(ConfigSettingRepository)
        row = await repo.get_for_update(registry_key.name)
        current_version = row.version if row is not None else 0
        if current_version != expected_version:
            raise ConfigConflict(registry_key.name, expected_version, current_version)

        now = self._clock.now()
        old_json: JsonValue | None
        if row is None:
            old_json = None
            new_version = 1
            try:
                await repo.insert_new(
                    ConfigSetting(
                        key=registry_key.name,
                        value=new_json,
                        version=new_version,
                        updated_at=now,
                        updated_by=principal.subject,
                    )
                )
            except DuplicateConfigKeyError as exc:
                raise ConfigConflict(registry_key.name, expected_version, 1) from exc
        else:
            old_json = cast(JsonValue, row.value)
            new_version = current_version + 1
            await repo.update(
                row,
                value=new_json,
                version=new_version,
                updated_at=now,
                updated_by=principal.subject,
            )
        await ConfigAudit.record(
            uow, registry_key.name, old_json, new_json, principal, cleaned_reason, clock=self._clock
        )
        return new_version


# --------------------------------------------------------------------------- catalogue (read model)


@dataclass(frozen=True, slots=True)
class ConfigEntryData:
    key: str
    group: str
    description: str
    value: JsonValue
    default: JsonValue
    version: int
    updated_by: str | None
    updated_by_name: str | None
    updated_at: datetime.datetime | None
    admin_only_write: bool
    restart_required: bool
    secret_ref: bool
    last_changed_at: datetime.datetime | None
    last_changed_by: str | None


@dataclass(frozen=True, slots=True)
class ConfigGroupData:
    group: str
    label: str
    count: int
    description: str


def list_config_groups() -> list[ConfigGroupData]:
    """Every group with its key count, by `GroupSpec.order` and then by name."""
    counts: dict[str, int] = {}
    for key in CONFIG_KEYS.values():
        counts[key.group] = counts.get(key.group, 0) + 1
    groups = [
        ConfigGroupData(group, CONFIG_GROUPS[group].label, count, CONFIG_GROUPS[group].description)
        for group, count in counts.items()
    ]
    return sorted(groups, key=lambda g: (CONFIG_GROUPS[g.group].order, g.group))


async def list_config_entries(uow: UnitOfWork, only: str | None = None) -> list[ConfigEntryData]:
    """Every registry key (or just `only`) with its effective value, read fresh."""
    keys = [lookup_key(only)] if only is not None else list(CONFIG_KEYS.values())
    stored = {row.key: row for row in await uow.repo(ConfigSettingRepository).all()}
    latest = await uow.repo(ConfigChangeRepository).latest_by_key([k.name for k in keys])
    entries: list[ConfigEntryData] = []
    for key in keys:
        row = stored.get(key.name)
        snapshot_row = (
            StoredSetting(
                key.name, cast(JsonValue, row.value), row.version, row.updated_at, row.updated_by
            )
            if row is not None
            else None
        )
        value, version = effective_value(key, snapshot_row)
        change = latest.get(key.name)
        entries.append(
            ConfigEntryData(
                key=key.name,
                group=key.group,
                description=key.description,
                value=to_json(key, value),
                default=to_json(key, key.default),
                version=version,
                updated_by=row.updated_by if row is not None else None,
                updated_by_name=change.changed_by_name if change is not None else None,
                updated_at=row.updated_at if row is not None else None,
                admin_only_write=key.admin_only_write,
                restart_required=key.restart_required,
                secret_ref=key.secret_ref,
                last_changed_at=change.changed_at if change is not None else None,
                last_changed_by=change.changed_by_name if change is not None else None,
            )
        )
    return entries
