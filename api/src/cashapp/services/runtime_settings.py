"""Typed access to every setting that used to live in the deploy environment.

`RuntimeSettings` wraps `RuntimeConfig` (the one DB-backed settings path). A hot key is read
through its TTL cache on every use. A restart-required key is read once by `start()` and pinned
for the life of the process, so a client built from it never changes underneath its callers.
Secrets are never stored: a secret key holds a Vault OCID and `secret()` resolves it at use.
"""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from cashapp.data.engine import create_engine
from cashapp.data.uow import UowFactory, make_uow_factory
from cashapp.domain import config_keys as ck
from cashapp.domain.clock import Clock
from cashapp.domain.config_keys import CONFIG_KEYS, REQUIRED_KEYS, ConfigKey, FusionPod
from cashapp.secrets import SecretResolver
from cashapp.services.config import RuntimeConfig, build_runtime_config
from cashapp.settings import Settings, build_secret_source

logger = logging.getLogger(__name__)

OBJECT_STORAGE_REGION = "us-ashburn-1"


class SettingsNotLoadedError(RuntimeError):
    """A restart-required key was read before `start()` finished."""


class SettingsIncompleteError(RuntimeError):
    """`start()` found required keys unset or inconsistent. Names only; never values."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("Settings are incomplete: " + "; ".join(problems))


@dataclass(frozen=True, slots=True)
class StreamingConfig:
    """Queue naming. The queue is a database table, so there is no connection to configure."""

    topic_prefix: str
    consumer_group: str


@dataclass(frozen=True, slots=True)
class ObjectStorageConfig:
    namespace: str
    bucket: str
    region: str = OBJECT_STORAGE_REGION


@dataclass(frozen=True, slots=True)
class AnthropicConfig:
    api_key_ref: str
    base_url: str | None


@dataclass(frozen=True, slots=True)
class OciGenAiConfig:
    endpoint: str
    compartment_ocid: str
    dedicated_endpoint_ocid: str


@dataclass(frozen=True, slots=True)
class IdentityConfig:
    issuer: str
    jwks_url: str
    audience: str
    groups_claim: str
    userinfo_url: str | None


@dataclass(frozen=True, slots=True)
class FusionConfig:
    pods: Mapping[str, FusionPod]
    default_pod: str


@dataclass(frozen=True, slots=True)
class FusionWriteFlags:
    write_enabled: bool
    unapply_verified: bool


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    otlp_endpoint: str | None
    oci_monitoring_namespace: str


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    from_address: str
    password_ref: str


@dataclass(frozen=True, slots=True)
class ClusterMetricSettings:
    cluster_ocid: str | None
    namespace: str
    query: str | None


def _empty(value: object) -> bool:
    return value is None or value == "" or value == {}


class RuntimeSettings:
    """The single reader of deploy settings. Built once per process; `start()` before use."""

    def __init__(
        self,
        config: RuntimeConfig,
        resolver: SecretResolver,
        *,
        env: str,
        settings: Settings | None = None,
    ) -> None:
        self._config = config
        self._resolver = resolver
        self._env = env
        self._settings = settings
        self._pinned: dict[str, Any] = {}
        self._started = False
        self._problems: list[str] = []

    # --- lifecycle ----------------------------------------------------------------------

    async def start(self, *, strict: bool = True) -> None:
        """Pin the restart-required keys and check the required ones. Idempotent.

        With ``strict=False`` (the API) missing required keys do not stop the process: it starts
        in setup mode so the keys can be entered, `problems` lists what is missing, and any use of
        a missing key raises `SettingsIncompleteError`. Workers stay strict.
        """
        if self._started:
            return
        snapshot = await self._config.snapshot()
        pinned: dict[str, Any] = {
            name: snapshot.get(key) for name, key in CONFIG_KEYS.items() if key.restart_required
        }
        problems = self._check(pinned, snapshot.get(ck.FUSION_RELATIONSHIPS_REPORT_PATH))
        if problems and strict:
            raise SettingsIncompleteError(problems)
        self._pinned = pinned
        self._started = True
        self._problems = problems
        if problems:
            logger.warning("settings incomplete, running in setup mode: %s", "; ".join(problems))
            return
        # Imported here: the pipeline layer sits above services.
        from cashapp.pipeline.events import TopicNamer, set_default_namer

        set_default_namer(TopicNamer.from_config(self.streaming(), self._env))
        logger.info("runtime settings loaded", extra={"pinned_keys": len(pinned)})

    @property
    def problems(self) -> list[str]:
        """Required keys still unset; empty when the process is fully configured."""
        return list(self._problems)

    @staticmethod
    def _check(pinned: Mapping[str, Any], report_path: object) -> list[str]:
        problems: list[str] = []
        for key in REQUIRED_KEYS:
            value = pinned[key.name] if key.restart_required else report_path
            if _empty(value):
                problems.append(f"{key.name} is not set")
        pods = pinned[ck.FUSION_PODS.name]
        default_pod = pinned[ck.FUSION_DEFAULT_POD.name]
        if pods and default_pod is not None and default_pod not in pods:
            problems.append("fusion.default_pod must be one of fusion.pods")
        smtp_names = (
            ck.SMTP_HOST,
            ck.SMTP_USERNAME,
            ck.SMTP_FROM_ADDRESS,
            ck.SMTP_PASSWORD_REF,
        )
        smtp_set = [key for key in smtp_names if not _empty(pinned[key.name])]
        if smtp_set and len(smtp_set) != len(smtp_names):
            unset = [key.name for key in smtp_names if _empty(pinned[key.name])]
            problems.append("smtp is partly configured; also set " + ", ".join(unset))
        return problems

    @property
    def started(self) -> bool:
        return self._started

    @property
    def env(self) -> str:
        return self._env

    @property
    def settings(self) -> Settings:
        """The bootstrap settings (database connection, secret source, health port)."""
        if self._settings is None:
            raise SettingsNotLoadedError("bootstrap settings were not given to RuntimeSettings")
        return self._settings

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    # --- keys ---------------------------------------------------------------------------

    def pinned[T](self, key: ConfigKey[T]) -> T:
        """A restart-required key's value, as read by `start()`."""
        if not key.restart_required:
            raise ValueError(f"{key.name} is a hot key; use get()")
        if not self._started:
            raise SettingsNotLoadedError(f"{key.name} read before settings were loaded")
        value: T = self._pinned[key.name]
        return value

    async def get[T](self, key: ConfigKey[T]) -> T:
        """Hot keys through the TTL cache; restart-required keys from the pinned values."""
        if key.restart_required:
            return self.pinned(key)
        return await self._config.get(key)

    async def secret(self, key_or_ref: ConfigKey[str | None] | str) -> SecretStr:
        """Resolve a secret key (or a Vault OCID) at use. The value is never stored or logged."""
        if isinstance(key_or_ref, str):
            ref: str | None = key_or_ref
        else:
            ref = await self.get(key_or_ref)
        if not ref:
            name = key_or_ref if isinstance(key_or_ref, str) else key_or_ref.name
            raise SettingsIncompleteError([f"{name} is not set"])
        return await self._resolver.resolve(ref)

    def invalidate_secrets(self, ref: str | None = None) -> None:
        self._resolver.invalidate(ref)

    # --- pinned views -------------------------------------------------------------------

    def _text(self, key: ConfigKey[str | None]) -> str:
        value = self.pinned(key)
        if value is None:
            raise SettingsIncompleteError([f"{key.name} is not set"])
        return value

    def streaming(self) -> StreamingConfig:
        prefix = self.pinned(ck.STREAMING_TOPIC_PREFIX)
        return StreamingConfig(topic_prefix=prefix, consumer_group=f"{prefix}-{self._env}")

    def object_storage(self) -> ObjectStorageConfig:
        return ObjectStorageConfig(
            namespace=self._text(ck.OBJECT_STORAGE_NAMESPACE),
            bucket=self._text(ck.OBJECT_STORAGE_BUCKET),
        )

    def anthropic(self) -> AnthropicConfig:
        return AnthropicConfig(
            api_key_ref=self._text(ck.ANTHROPIC_API_KEY_REF),
            base_url=self.pinned(ck.ANTHROPIC_BASE_URL),
        )

    def oci_genai(self) -> OciGenAiConfig:
        return OciGenAiConfig(
            endpoint=self.pinned(ck.OCI_GENAI_ENDPOINT),
            compartment_ocid=self._text(ck.OCI_GENAI_COMPARTMENT_OCID),
            dedicated_endpoint_ocid=self._text(ck.OCI_GENAI_DEDICATED_ENDPOINT_OCID),
        )

    def identity(self) -> IdentityConfig:
        return IdentityConfig(
            issuer=self._text(ck.IDENTITY_ISSUER),
            jwks_url=self._text(ck.IDENTITY_JWKS_URL),
            audience=self._text(ck.IDENTITY_AUDIENCE),
            groups_claim=self.pinned(ck.IDENTITY_GROUPS_CLAIM),
            userinfo_url=self.pinned(ck.IDENTITY_USERINFO_URL),
        )

    def fusion(self) -> FusionConfig:
        return FusionConfig(
            pods=MappingProxyType(dict(self.pinned(ck.FUSION_PODS))),
            default_pod=self._text(ck.FUSION_DEFAULT_POD),
        )

    def observability(self) -> ObservabilityConfig:
        return ObservabilityConfig(
            log_level=self.pinned(ck.OBSERVABILITY_LOG_LEVEL),
            otlp_endpoint=self.pinned(ck.OBSERVABILITY_OTLP_ENDPOINT),
            oci_monitoring_namespace=self.pinned(ck.OBSERVABILITY_OCI_MONITORING_NAMESPACE),
        )

    def intake_folder(self) -> Path:
        return Path(self._text(ck.INTAKE_DROP_FOLDER))

    def smtp(self) -> SmtpConfig | None:
        """None means the email channel is off (no host)."""
        host = self.pinned(ck.SMTP_HOST)
        if host is None:
            return None
        return SmtpConfig(
            host=host,
            port=self.pinned(ck.SMTP_PORT),
            username=self._text(ck.SMTP_USERNAME),
            from_address=self._text(ck.SMTP_FROM_ADDRESS),
            password_ref=self._text(ck.SMTP_PASSWORD_REF),
        )

    # --- hot views ----------------------------------------------------------------------

    async def fusion_writes(self) -> FusionWriteFlags:
        snapshot = await self._config.snapshot()
        return FusionWriteFlags(
            write_enabled=snapshot.get(ck.FUSION_WRITE_ENABLED),
            unapply_verified=snapshot.get(ck.FUSION_UNAPPLY_VERIFIED),
        )

    async def relationships_report_path(self) -> str:
        path = await self.get(ck.FUSION_RELATIONSHIPS_REPORT_PATH)
        if not path:
            raise SettingsIncompleteError(["fusion.relationships_report_path is not set"])
        return path

    async def cluster_metric(self) -> ClusterMetricSettings:
        snapshot = await self._config.snapshot()
        return ClusterMetricSettings(
            cluster_ocid=snapshot.get(ck.OCI_GENAI_DEDICATED_CLUSTER_OCID),
            namespace=snapshot.get(ck.OCI_GENAI_CLUSTER_METRIC_NAMESPACE),
            query=snapshot.get(ck.OCI_GENAI_CLUSTER_METRIC_QUERY),
        )

    async def shutdown_grace_seconds(self) -> int:
        return await self.get(ck.WORKER_SHUTDOWN_GRACE_SECONDS)


def build_runtime_settings(
    settings: Settings,
    uow_factory: UowFactory,
    *,
    clock: Clock | None = None,
    resolver: SecretResolver | None = None,
) -> RuntimeSettings:
    """The process's settings reader over its DB-backed config and its secret source."""
    return RuntimeSettings(
        build_runtime_config(uow_factory, clock=clock),
        resolver
        if resolver is not None
        else SecretResolver(build_secret_source(settings, uow_factory)),
        env=settings.env,
        settings=settings,
    )


def _tool_engine(settings: Settings) -> AsyncEngine:
    atp = settings.atp
    # create_engine already sets pool_pre_ping; passing it twice would be a TypeError.
    options = {k: v for k, v in atp.engine_kwargs().items() if k != "pool_pre_ping"}
    return create_engine(atp.url().render_as_string(hide_password=False), **options)


async def start_runtime_settings(settings: Settings) -> RuntimeSettings:
    """A started `RuntimeSettings` over a private engine, for evals and one-shot tools that are
    already inside their event loop. Workers and the API start their own."""
    runtime = build_runtime_settings(settings, make_uow_factory(_tool_engine(settings)))
    await runtime.start()
    return runtime


def load_runtime_settings(settings: Settings) -> RuntimeSettings:
    """Blocking form for sync command-line entry points.

    The start-up read runs in its own event loop and the engine is disposed afterwards, so the
    tool's later `asyncio.run` calls open fresh connections in their own loop.
    """

    async def load() -> RuntimeSettings:
        engine = _tool_engine(settings)
        runtime = build_runtime_settings(settings, make_uow_factory(engine))
        try:
            await runtime.start()
        finally:
            await engine.dispose()
        return runtime

    return asyncio.run(load())
