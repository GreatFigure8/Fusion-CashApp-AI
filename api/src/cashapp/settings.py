"""Bootstrap settings: the few values a process needs before it can read the database.

Everything else is a DB config key (`cashapp.domain.config_keys`), read
through `cashapp.services.runtime_settings.RuntimeSettings`, versioned and audited. What stays
here, and why:

- `env`: picks the topic label and the local/deployed behaviour before any I/O.
- `atp`: the database connection itself.
- `worker.health_port`: bound before the database is reachable, pinned by the deployment manifest.
- `secrets`: the master key that decrypts the secrets stored in the database (which cannot be
  stored in the database itself), and the optional switch to OCI Vault or a local value map.

Every setting is an environment variable named `CASHAPP_<GROUP>__<FIELD>`; a string value of the
form `vault:<secret-ocid>` is resolved from the secret source before the model is finally
validated. This is the only module that reads the process environment. Any other `CASHAPP_*`
variable is refused by name; a variable that moved to the database names its new key.
"""

import asyncio
import functools
import json
import os
import re
import tempfile
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from dotenv import dotenv_values
from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    SecretStr,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

from cashapp.domain.config_keys import (
    CONFIG_KEYS,
    FUSION_DEFAULT_POD,
    FUSION_PODS,
    REQUIRED_KEYS,
)
from cashapp.secrets import (
    VAULT_PREFIX,
    EnvSecretSource,
    SecretResolutionError,
    SecretSource,
    VaultSecretSource,
    collect_secret_refs,
    resolve_secret_refs,
)

if TYPE_CHECKING:
    from cashapp.data.uow import UowFactory

ENV_PREFIX = "CASHAPP_"
NESTED_DELIMITER = "__"

Env = Literal["local", "dev", "test", "prod"]

OCI_RESOURCE_PRINCIPAL_ENV = "OCI_RESOURCE_PRINCIPAL_VERSION"


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


class WorkerBootstrapSettings(_Group):
    health_port: int = 8081


class SecretSourceSettings(_Group):
    """How secrets are reached. `local_values` maps a secret OCID to its value, local env only."""

    source: Literal["db", "vault", "env"] | None = None
    signer: Literal["resource_principal", "instance_principal"] | None = None
    local_values: dict[str, SecretStr] = {}
    # Base64 of 32 random bytes. It encrypts the secrets stored in the database, so it cannot
    # live there; it travels with the database connection.
    master_key: SecretStr | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter=NESTED_DELIMITER,
        case_sensitive=False,
        extra="forbid",
        frozen=True,
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # `CASHAPP_X=` in a template means unset
    )

    env: Env
    atp: AtpSettings
    worker: WorkerBootstrapSettings = WorkerBootstrapSettings()
    secrets: SecretSourceSettings = SecretSourceSettings()

    @model_validator(mode="after")
    def _local_values_only_locally(self) -> "Settings":
        if self.secrets.local_values and self.env != "local":
            raise ValueError("secrets.local_values is only allowed when env is local")
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


# --- the env contract -----------------------------------------------------------------------

_ATP_FIELDS: Final = tuple(AtpSettings.model_fields)
BOOTSTRAP_ENV_NAMES: Final[frozenset[str]] = frozenset(
    {
        "CASHAPP_ENV",
        *(f"CASHAPP_ATP__{name.upper()}" for name in _ATP_FIELDS),
        "CASHAPP_WORKER__HEALTH_PORT",
        "CASHAPP_SECRETS__SOURCE",
        "CASHAPP_SECRETS__SIGNER",
        "CASHAPP_SECRETS__LOCAL_VALUES",
        "CASHAPP_SECRETS__MASTER_KEY",
    }
)
"""Names the process reads; a name under `CASHAPP_SECRETS__LOCAL_VALUES__` is also accepted."""

TOOL_ENV_NAMES: Final[frozenset[str]] = frozenset({"CASHAPP_IDENTIFIER_DENYLIST"})
"""Typer option of the anonymise CLI, not a setting."""

_LOCAL_VALUES_PREFIX: Final = "CASHAPP_SECRETS__LOCAL_VALUES__"

type _Kind = Literal["str", "bool", "int", "secret"]

# env name -> (DB key, kind). A `secret` env value is `vault:<ocid>` and becomes the OCID.
_SIMPLE_LEGACY: Final[Mapping[str, tuple[str, _Kind]]] = {
    "CASHAPP_STREAMING__TOPIC_PREFIX": ("streaming.topic_prefix", "str"),
    "CASHAPP_OBJECT_STORAGE__NAMESPACE": ("object_storage.namespace", "str"),
    "CASHAPP_OBJECT_STORAGE__BUCKET": ("object_storage.bucket", "str"),
    "CASHAPP_ANTHROPIC__BASE_URL": ("anthropic.base_url", "str"),
    "CASHAPP_ANTHROPIC__API_KEY": ("anthropic.api_key_ref", "secret"),
    "CASHAPP_OCI_GENAI__ENDPOINT": ("oci_genai.endpoint", "str"),
    "CASHAPP_OCI_GENAI__COMPARTMENT_OCID": ("oci_genai.compartment_ocid", "str"),
    "CASHAPP_OCI_GENAI__DEDICATED_ENDPOINT_OCID": ("oci_genai.dedicated_endpoint_ocid", "str"),
    "CASHAPP_OCI_GENAI__DEDICATED_CLUSTER_OCID": ("oci_genai.dedicated_cluster_ocid", "str"),
    "CASHAPP_OCI_GENAI__CLUSTER_METRIC_NAMESPACE": ("oci_genai.cluster_metric_namespace", "str"),
    "CASHAPP_OCI_GENAI__CLUSTER_METRIC_QUERY": ("oci_genai.cluster_metric_query", "str"),
    "CASHAPP_IDENTITY__ISSUER": ("identity.issuer", "str"),
    "CASHAPP_IDENTITY__JWKS_URL": ("identity.jwks_url", "str"),
    "CASHAPP_IDENTITY__AUDIENCE": ("identity.audience", "str"),
    "CASHAPP_IDENTITY__GROUPS_CLAIM": ("identity.groups_claim", "str"),
    "CASHAPP_FUSION__DEFAULT_POD": ("fusion.default_pod", "str"),
    "CASHAPP_FUSION__WRITE_ENABLED": ("fusion.write_enabled", "bool"),
    "CASHAPP_FUSION__UNAPPLY_VERIFIED": ("fusion.unapply_verified", "bool"),
    "CASHAPP_FUSION__RELATIONSHIPS_REPORT_PATH": ("fusion.relationships_report_path", "str"),
    "CASHAPP_OBSERVABILITY__LOG_LEVEL": ("observability.log_level", "str"),
    "CASHAPP_OBSERVABILITY__OTLP_ENDPOINT": ("observability.otlp_endpoint", "str"),
    "CASHAPP_OBSERVABILITY__OCI_MONITORING_NAMESPACE": (
        "observability.oci_monitoring_namespace",
        "str",
    ),
    "CASHAPP_WORKER__SHUTDOWN_GRACE_SECONDS": ("worker.shutdown_grace_seconds", "int"),
    "CASHAPP_INTAKE__DROP_FOLDER": ("intake.drop_folder", "str"),
    "CASHAPP_SMTP__HOST": ("smtp.host", "str"),
    "CASHAPP_SMTP__PORT": ("smtp.port", "int"),
    "CASHAPP_SMTP__USERNAME": ("smtp.username", "str"),
    "CASHAPP_SMTP__PASSWORD": ("smtp.password_ref", "secret"),
    "CASHAPP_SMTP__FROM_ADDRESS": ("smtp.from_address", "str"),
}

_POD_ENV: Final = re.compile(r"^CASHAPP_FUSION__PODS(?:__([A-Z0-9_]+?)__([A-Z_]+(?:__[A-Z_]+)?))?$")
_POD_FIELDS: Final = {
    "BASE_URL": "base_url",
    "USERNAME": "username",
    "PASSWORD": "password_ref",
    "IS_PRODUCTION": "is_production",
}
_POD_TESTDATA: Final = {
    "TESTDATA__BUSINESS_UNIT": "business_unit",
    "TESTDATA__TRANSACTION_TYPE": "transaction_type",
    "TESTDATA__RECEIPT_METHOD": "receipt_method",
    "TESTDATA__BANK_ACCOUNT": "bank_account",
}

RETIRED_ENV_NAMES: Final[frozenset[str]] = frozenset(
    {
        "CASHAPP_STREAMING__ENV",
        "CASHAPP_OBJECT_STORAGE__REGION",
        "CASHAPP_IDENTITY__BOOTSTRAP_ADMIN_GROUP",
    }
)
"""Removed without a DB key: the value is now a constant or the bootstrap `env`."""

LEGACY_ENV_TO_KEY: Final[Mapping[str, str]] = {
    **{name: key for name, (key, _) in _SIMPLE_LEGACY.items()},
    "CASHAPP_FUSION__PODS": FUSION_PODS.name,
}
"""Every removed env name (a pod variable maps through the `CASHAPP_FUSION__PODS` prefix) and the
DB key it moved to."""


def _legacy_key_of(name: str) -> str | None:
    if name in LEGACY_ENV_TO_KEY:
        return LEGACY_ENV_TO_KEY[name]
    if name.startswith("CASHAPP_FUSION__PODS__"):
        return FUSION_PODS.name
    return None


def _is_known(name: str) -> bool:
    return (
        name in BOOTSTRAP_ENV_NAMES
        or name in TOOL_ENV_NAMES
        or name.startswith(_LOCAL_VALUES_PREFIX)
    )


def _scan_environ(environ: Mapping[str, str], *, allow_legacy: bool) -> None:
    """Refuse any `CASHAPP_*` name that is not bootstrap. Names only; never values."""
    invalid: list[str] = []
    for raw in sorted(environ):
        name = raw.upper()
        if not name.startswith(ENV_PREFIX) or _is_known(name):
            continue
        moved = _legacy_key_of(name)
        if moved is not None:
            if not allow_legacy:
                invalid.append(f"{name} (moved to DB key {moved})")
        elif name in RETIRED_ENV_NAMES:
            if not allow_legacy:
                invalid.append(f"{name} (no longer used)")
        else:
            invalid.append(f"{name} (unknown setting)")
    if invalid:
        raise SettingsError(invalid=tuple(invalid))


# --- legacy seed (read by the one-off data migration) ---------------------------------------


@dataclass(slots=True)
class LegacySeed:
    """Values for DB keys, read from the deploy environment of the process that runs the seed."""

    values: dict[str, JsonValue] = field(default_factory=lambda: {})
    missing: list[str] = field(default_factory=lambda: [])
    """DB keys (`REQUIRED_KEYS`) with no value in the environment."""
    plaintext_secrets: list[str] = field(default_factory=lambda: [])
    """Env names whose secret was not a `vault:<ocid>` reference."""


def _convert(raw: str, kind: _Kind) -> JsonValue | None:
    text = raw.strip()
    if not text:
        return None
    if kind == "bool":
        return text.lower() in {"1", "true", "yes", "on"}
    if kind == "int":
        return int(text)
    return text


def _pod_value(pods: dict[str, dict[str, JsonValue]], pod: str, name: str, value: str) -> None:
    entry = pods.setdefault(pod.lower(), {})
    if name in _POD_FIELDS:
        field_name = _POD_FIELDS[name]
        if field_name == "is_production":
            entry[field_name] = value.lower() in {"1", "true", "yes", "on"}
        else:
            entry[field_name] = value
    elif name in _POD_TESTDATA:
        testdata = entry.setdefault("testdata", {})
        if isinstance(testdata, dict):
            testdata[_POD_TESTDATA[name]] = value


def read_legacy_seed(environ: Mapping[str, str] | None = None) -> LegacySeed:
    """Map the removed env variables onto DB keys: `vault:<ocid>` becomes the OCID."""
    source = {k.upper(): v for k, v in (os.environ if environ is None else environ).items()}
    seed = LegacySeed()
    for name, (key, kind) in _SIMPLE_LEGACY.items():
        if name not in source:
            continue
        converted = _convert(source[name], kind)
        if converted is None:
            continue
        if kind == "secret":
            text = str(converted)
            if text.startswith(VAULT_PREFIX) and len(text) > len(VAULT_PREFIX):
                seed.values[key] = text.removeprefix(VAULT_PREFIX)
            else:
                seed.plaintext_secrets.append(name)
            continue
        seed.values[key] = converted

    pods: dict[str, dict[str, JsonValue]] = {}
    for name, value in source.items():
        if not name.startswith("CASHAPP_FUSION__PODS__") or not value.strip():
            continue
        match = _POD_ENV.match(name)
        if match is None or match.group(1) is None:
            continue
        pod, rest = match.group(1), match.group(2)
        if rest == "PASSWORD":
            if value.startswith(VAULT_PREFIX) and len(value) > len(VAULT_PREFIX):
                _pod_value(pods, pod, rest, value.removeprefix(VAULT_PREFIX))
            else:
                seed.plaintext_secrets.append(name)
            continue
        _pod_value(pods, pod, rest, value)
    if "CASHAPP_FUSION__PODS" in source and source["CASHAPP_FUSION__PODS"].strip():
        parsed: Any = json.loads(source["CASHAPP_FUSION__PODS"])
        if isinstance(parsed, dict):
            seed.values[FUSION_PODS.name] = {str(k).lower(): v for k, v in parsed.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    elif pods:
        seed.values[FUSION_PODS.name] = dict(pods)  # pyright: ignore[reportArgumentType]
    default_pod = seed.values.get(FUSION_DEFAULT_POD.name)
    if isinstance(default_pod, str):
        seed.values[FUSION_DEFAULT_POD.name] = default_pod.lower()

    seed.missing = [key.name for key in REQUIRED_KEYS if key.name not in seed.values]
    return seed


def legacy_env_name(key: str) -> str:
    """The env name a DB key was seeded from, for error messages."""
    for name, mapped in LEGACY_ENV_TO_KEY.items():
        if mapped == key:
            return name if key != FUSION_PODS.name else "CASHAPP_FUSION__PODS__<POD>__*"
    return key


def seed_key_names() -> list[str]:
    """Every DB key the seed can write (the downgrade deletes only these)."""
    return [name for name in dict.fromkeys(LEGACY_ENV_TO_KEY.values()) if name in CONFIG_KEYS]


# --- OCI signer and secret source -----------------------------------------------------------


def oci_signer(settings: Settings) -> Any | None:
    """The OCI request signer for this process, or None to use the developer's ~/.oci/config.

    Resource principal when the platform injects one, instance principal on compute, nothing
    locally. `secrets.signer` overrides the detection.
    """
    import oci  # pyright: ignore[reportMissingTypeStubs]

    sdk: Any = oci
    kind = settings.secrets.signer
    if kind is None and os.environ.get(OCI_RESOURCE_PRINCIPAL_ENV):
        kind = "resource_principal"
    if kind == "resource_principal":
        return sdk.auth.signers.get_resource_principals_signer()
    if kind == "instance_principal":
        return sdk.auth.signers.InstancePrincipalsSecurityTokenSigner()
    if settings.env == "local":
        return None
    try:
        return sdk.auth.signers.InstancePrincipalsSecurityTokenSigner()
    except Exception:
        return None  # not on OCI compute


def build_secret_source(
    settings: Settings, uow_factory: "UowFactory | None" = None
) -> SecretSource:
    """The encrypted database store by default, the local value map under `env=local` when no
    master key is set, OCI Vault only when `secrets.source` asks for it."""
    default = "env" if settings.env == "local" and settings.secrets.master_key is None else "db"
    source = settings.secrets.source or default
    if source == "env":
        return EnvSecretSource(
            {ref: value.get_secret_value() for ref, value in settings.secrets.local_values.items()}
        )
    if source == "db":
        if settings.secrets.master_key is None:
            raise SettingsError(missing=("CASHAPP_SECRETS__MASTER_KEY",))
        if uow_factory is None:
            raise SettingsError(detail="stored secrets cannot be read before the database is open")
        # Imported here: the services layer imports this module.
        from cashapp.secrets import SecretCipher
        from cashapp.services.app_secrets import DbSecretSource

        cipher = SecretCipher(settings.secrets.master_key.get_secret_value())
        return DbSecretSource(uow_factory, cipher)
    signer = oci_signer(settings)
    if signer is None:
        raise SettingsError(detail="no OCI signer is available to reach Vault")
    return VaultSecretSource.from_signer(signer)


# --- loading --------------------------------------------------------------------------------


def _env_name(path: tuple[str | int, ...]) -> str:
    return ENV_PREFIX + NESTED_DELIMITER.join(str(part).upper() for part in path)


def _settings_error(exc: ValidationError) -> SettingsError:
    missing: list[str] = []
    invalid: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        loc = tuple(error["loc"])
        name = _env_name(loc) if loc else "settings"
        if error["type"] == "missing":
            missing.append(name)
        else:
            invalid.append(f"{name} ({error['type']})")
    return SettingsError(
        missing=tuple(dict.fromkeys(missing)), invalid=tuple(dict.fromkeys(invalid))
    )


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


def _merged_environ(env_file: str | Path | None) -> dict[str, str]:
    merged: dict[str, str] = {}
    if env_file is not None and Path(env_file).is_file():
        merged.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    merged.update(os.environ)
    return merged


def _bootstrap_only_env_file(env_file: str | Path | None) -> str | None:
    """A temp copy of the `.env` with only bootstrap lines, so legacy lines can't trip `forbid`."""
    if env_file is None or not Path(env_file).is_file():
        return None
    lines = [
        f"{name}={json.dumps(value)}"
        for name, value in dotenv_values(env_file).items()
        if value is not None and _is_known(name.upper())
    ]
    handle, path = tempfile.mkstemp(prefix="cashapp-bootstrap-", suffix=".env")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
    return path


def _remove(path: str) -> None:
    Path(path).unlink(missing_ok=True)


async def aload_settings(
    *,
    secret_source: SecretSource | None = None,
    env_file: str | Path | None = ".env",
    allow_legacy_env: bool = False,
) -> Settings:
    """Load, resolve `vault:` references once, and validate. Raises `SettingsError` only.

    `allow_legacy_env` is for the one data migration that seeds the DB keys from the old
    environment; it tolerates removed names but still refuses unknown ones.
    """
    _scan_environ(_merged_environ(env_file), allow_legacy=allow_legacy_env)
    temp_file = _bootstrap_only_env_file(env_file) if allow_legacy_env else None
    effective_file: str | Path | None = temp_file if allow_legacy_env else env_file
    try:
        try:
            first = Settings(_env_file=effective_file)  # pyright: ignore[reportCallIssue]
        except ValidationError as exc:
            raise _settings_error(exc) from None  # never chain: pydantic's message carries inputs

        raw: dict[str, Any] = _reveal(first.model_dump())
        if not collect_secret_refs(raw):
            return first

        source = secret_source if secret_source is not None else build_secret_source(first)
        try:
            resolved = await resolve_secret_refs(raw, source)
        except SecretResolutionError as exc:
            paths = ", ".join(_paths_with_ref(raw, exc.ref))
            raise SettingsError(detail=f"could not resolve {exc.ref} for {paths}") from None
        try:
            return Settings.model_validate(resolved)
        except ValidationError as exc:
            raise _settings_error(exc) from None
    finally:
        if temp_file is not None:
            _remove(temp_file)


def _run(coro_factory: Callable[[], Coroutine[Any, Any, Settings]]) -> Settings:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    # Inside a running loop (uvicorn, Alembic's async env): run in a one-shot thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro_factory()).result()


def load_settings(
    *,
    secret_source: SecretSource | None = None,
    env_file: str | Path | None = ".env",
    allow_legacy_env: bool = False,
) -> Settings:
    """Sync entry point for startup code; works with or without a running event loop."""
    return _run(
        functools.partial(
            aload_settings,
            secret_source=secret_source,
            env_file=env_file,
            allow_legacy_env=allow_legacy_env,
        )
    )


@functools.cache
def get_settings() -> Settings:
    """The process-wide bootstrap settings. Tests call `get_settings.cache_clear()`."""
    return load_settings()
