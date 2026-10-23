"""Deploy-time settings: one typed, closed, frozen model, loaded once at startup.

Business-tunable values live in the runtime config service (s28), not here. Every setting is an
environment variable named `CASHAPP_<GROUP>__<FIELD>`; any string value of the form
`vault:<secret-ocid>` is resolved from the secret source (OCI Vault when deployed) before the
model is finally validated. Consumers index attributes; there are no `.get(default)` fallbacks.
"""

import asyncio
import functools
import types
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import (
    BaseModel,
    ConfigDict,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from cashapp.secrets import (
    VAULT_PREFIX,
    EnvSecretSource,
    SecretResolutionError,
    SecretSource,
    VaultSecretSource,
    collect_secret_refs,
    resolve_secret_refs,
)

ENV_PREFIX = "CASHAPP_"
NESTED_DELIMITER = "__"
POD_PLACEHOLDER = "<POD>"

Env = Literal["local", "dev", "test", "prod"]


class _Group(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AtpSettings(_Group):
    dsn: str
    user: str
    password: SecretStr
    wallet_dir: str | None = None
    wallet_password: SecretStr | None = None
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout_seconds: int = 30

    def url(self) -> URL:
        """SQLAlchemy URL with credentials only; the DSN travels in `connect_args`."""
        return URL.create(
            "oracle+oracledb",
            username=self.user,
            password=self.password.get_secret_value(),
        )

    def connect_args(self) -> dict[str, object]:
        args: dict[str, object] = {"dsn": self.dsn}
        if self.wallet_dir is not None:
            args["config_dir"] = self.wallet_dir
            args["wallet_location"] = self.wallet_dir
            if self.wallet_password is not None:
                args["wallet_password"] = self.wallet_password.get_secret_value()
        return args

    def engine_kwargs(self) -> dict[str, object]:
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "pool_timeout": self.pool_timeout_seconds,
            "pool_pre_ping": True,
            "connect_args": self.connect_args(),
        }


class StreamingSettings(_Group):
    bootstrap_servers: str
    sasl_username: str
    sasl_password: SecretStr
    topic_prefix: str = "cashapp"
    consumer_group: str
    env: str | None = None

    @property
    def topic_env(self) -> str:
        if self.env is None:
            raise RuntimeError("streaming.env is unset; load settings through load_settings()")
        return self.env


class ObjectStorageSettings(_Group):
    namespace: str
    bucket: str
    region: Literal["us-ashburn-1"] = "us-ashburn-1"


class AnthropicSettings(_Group):
    api_key: SecretStr
    base_url: str | None = None


class OciGenAiSettings(_Group):
    endpoint: str = "https://inference.generativeai.us-ashburn-1.oci.oraclecloud.com"
    compartment_ocid: str
    dedicated_endpoint_ocid: str
    # Cluster utilisation from OCI Monitoring (s36). The namespace, metric name and dimension key
    # are UNVERIFIED against a live tenancy, so the metric stays off until a query is set. The
    # query is a template with a `{cluster_ocid}` placeholder.
    dedicated_cluster_ocid: str | None = None
    cluster_metric_namespace: str = "oci_generativeai"
    cluster_metric_query: str | None = None


class IdentitySettings(_Group):
    issuer: str
    jwks_url: str
    audience: str
    groups_claim: str = "groups"
    bootstrap_admin_group: str = "CashApp-Admins"


class FusionTestDataSettings(_Group):
    business_unit: str
    transaction_type: str
    receipt_method: str
    bank_account: str


class FusionPodSettings(_Group):
    base_url: str
    username: str
    password: SecretStr
    is_production: bool = False
    testdata: FusionTestDataSettings | None = None

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


class FusionSettings(_Group):
    pods: dict[str, FusionPodSettings]
    default_pod: str
    write_enabled: bool = False
    # Deploy-time gate: the unapply SOAP contract is UNVERIFIED until a live probe confirms it.
    unapply_verified: bool = False
    relationships_report_path: str

    @field_validator("pods", mode="before")
    @classmethod
    def _lower_pod_keys(cls, value: object) -> object:
        if isinstance(value, dict):
            return {str(key).lower(): item for key, item in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        return value

    @field_validator("default_pod")
    @classmethod
    def _lower_default_pod(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def _check_pods(self) -> "FusionSettings":
        if not self.pods:
            raise ValueError("at least one Fusion pod is required")
        if self.default_pod not in self.pods:
            raise ValueError("default_pod must be one of the configured pods")
        return self


class ObservabilitySettings(_Group):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    otlp_endpoint: str | None = None
    oci_monitoring_namespace: str = "cashapp"


class WorkerSettings(_Group):
    health_port: int = 8081
    shutdown_grace_seconds: int = 30


class IntakeSettings(_Group):
    drop_folder: str


class SmtpSettings(_Group):
    host: str
    port: int = 587
    username: str
    password: SecretStr
    from_address: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter=NESTED_DELIMITER,
        case_sensitive=False,
        extra="forbid",
        frozen=True,
        env_file_encoding="utf-8",
    )

    env: Env
    atp: AtpSettings
    streaming: StreamingSettings
    object_storage: ObjectStorageSettings
    anthropic: AnthropicSettings
    oci_genai: OciGenAiSettings
    identity: IdentitySettings
    fusion: FusionSettings
    observability: ObservabilitySettings = ObservabilitySettings()
    worker: WorkerSettings = WorkerSettings()
    intake: IntakeSettings
    smtp: SmtpSettings | None = None

    @model_validator(mode="after")
    def _default_streaming_env(self) -> "Settings":
        if self.streaming.env is None:
            # Frozen model: the topic label follows the deployment environment.
            object.__setattr__(self.streaming, "env", self.env)
        return self


class SettingsError(Exception):
    """Settings are missing or invalid. Names only; never values."""

    def __init__(
        self,
        *,
        missing: tuple[str, ...] = (),
        invalid: tuple[str, ...] = (),
        detail: str | None = None,
    ) -> None:
        self.missing = missing
        self.invalid = invalid
        parts: list[str] = []
        if missing:
            parts.append("missing " + ", ".join(missing))
        if invalid:
            parts.append("invalid " + ", ".join(invalid))
        if detail:
            parts.append(detail)
        super().__init__("Invalid settings: " + "; ".join(parts))


# --- env var naming -------------------------------------------------------------------------


def _env_name(path: tuple[str | int, ...]) -> str:
    return ENV_PREFIX + NESTED_DELIMITER.join(str(part).upper() for part in path)


def _group_of(annotation: Any) -> tuple[type[BaseModel], bool] | None:
    """Return (model class, is_dict_of_models) for a group annotation, else None."""
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        for arg in get_args(annotation):
            if arg is not type(None):
                found = _group_of(arg)
                if found is not None:
                    return found
        return None
    if origin is dict:
        value_type = get_args(annotation)[1]
        if isinstance(value_type, type) and issubclass(value_type, BaseModel):
            return value_type, True
        return None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    return None


def _leaf_paths(
    model: type[BaseModel],
    prefix: tuple[str, ...],
    *,
    required_only: bool,
) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    for name, field in model.model_fields.items():
        if required_only and not field.is_required():
            continue
        group = _group_of(field.annotation)
        if group is None:
            paths.append((*prefix, name))
        elif group[1]:
            paths.extend(
                _leaf_paths(group[0], (*prefix, name, POD_PLACEHOLDER), required_only=required_only)
            )
        else:
            paths.extend(_leaf_paths(group[0], (*prefix, name), required_only=required_only))
    return paths


def env_var_names() -> list[str]:
    """Every leaf setting as an env var name; dict keys (Fusion pods) render as `<POD>`."""
    return [_env_name(path) for path in _leaf_paths(Settings, (), required_only=False)]


def _missing_names(loc: tuple[str | int, ...]) -> list[str]:
    """Env var names for a missing value; a missing group expands to its required fields."""
    model: type[BaseModel] = Settings
    for index, part in enumerate(loc):
        field = model.model_fields.get(str(part)) if isinstance(part, str) else None
        if field is None:
            break
        group = _group_of(field.annotation)
        if group is None or group[1]:
            break
        model = group[0]
        if index == len(loc) - 1:
            expanded = _leaf_paths(model, tuple(str(p) for p in loc), required_only=True)
            return [_env_name(p) for p in expanded] or [_env_name(loc)]
    return [_env_name(loc)]


def _settings_error(exc: ValidationError) -> SettingsError:
    missing: list[str] = []
    invalid: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        loc = tuple(error["loc"])
        if error["type"] == "missing":
            missing.extend(_missing_names(loc))
        else:
            invalid.append(f"{_env_name(loc) if loc else 'settings'} ({error['type']})")
    return SettingsError(
        missing=tuple(dict.fromkeys(missing)), invalid=tuple(dict.fromkeys(invalid))
    )


# --- loading --------------------------------------------------------------------------------


def _reveal(data: Any) -> Any:
    if isinstance(data, SecretStr):
        return data.get_secret_value()
    if isinstance(data, dict):
        return {key: _reveal(item) for key, item in data.items()}  # pyright: ignore[reportUnknownVariableType]
    return data


def _paths_with_ref(data: Any, ref: str, prefix: tuple[str, ...] = ()) -> list[str]:
    if isinstance(data, str):
        return [_env_name(prefix)] if data == VAULT_PREFIX + ref else []
    if isinstance(data, dict):
        found: list[str] = []
        for key, item in data.items():  # pyright: ignore[reportUnknownVariableType]
            found.extend(_paths_with_ref(item, ref, (*prefix, str(key))))  # pyright: ignore[reportUnknownArgumentType]
        return found
    return []


async def aload_settings(
    *, secret_source: SecretSource | None = None, env_file: str | Path | None = ".env"
) -> Settings:
    """Load, resolve `vault:` references once, and validate. Raises `SettingsError` only."""
    try:
        first = Settings(_env_file=env_file)  # pyright: ignore[reportCallIssue]
    except ValidationError as exc:
        raise _settings_error(exc) from None  # never chain: pydantic's message carries inputs

    raw: dict[str, Any] = _reveal(first.model_dump())
    if not collect_secret_refs(raw):
        return first

    source = secret_source
    if source is None:
        source = EnvSecretSource() if first.env == "local" else VaultSecretSource.from_environment()
    try:
        resolved = await resolve_secret_refs(raw, source)
    except SecretResolutionError as exc:
        paths = ", ".join(_paths_with_ref(raw, exc.ref))
        raise SettingsError(detail=f"could not resolve {exc.ref} for {paths}") from None
    try:
        return Settings.model_validate(resolved)
    except ValidationError as exc:
        raise _settings_error(exc) from None


def _run(coro_factory: Callable[[], Coroutine[Any, Any, Settings]]) -> Settings:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    # Inside a running loop (uvicorn, Alembic's async env): run in a one-shot thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro_factory()).result()


def load_settings(
    *, secret_source: SecretSource | None = None, env_file: str | Path | None = ".env"
) -> Settings:
    """Sync entry point for startup code; works with or without a running event loop."""
    return _run(functools.partial(aload_settings, secret_source=secret_source, env_file=env_file))


@functools.cache
def get_settings() -> Settings:
    """The process-wide settings, loaded on first use. Tests call `get_settings.cache_clear()`."""
    return load_settings()
