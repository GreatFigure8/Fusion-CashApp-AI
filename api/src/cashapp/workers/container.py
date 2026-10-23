"""The worker container: lazy, one per process, built from each owner's factory by import path.

Importing this module imports no integration SDK. Factories and the types they serve are named by
import path and loaded the first time a service is resolved.
"""

import importlib
import logging
from collections.abc import Callable, Mapping
from functools import cached_property
from typing import Any, Final, TypeVar, cast

from cashapp.data.engine import create_engine
from cashapp.data.uow import UowFactory, make_uow_factory
from cashapp.domain.clock import Clock, SystemClock
from cashapp.pipeline.bus import EventBus, build_event_bus
from cashapp.pipeline.events import TopicNamer
from cashapp.pipeline.failures import EscalateAllHandler, FailureHandler
from cashapp.pipeline.health import BusHealth
from cashapp.services.config import RuntimeConfig, build_runtime_config
from cashapp.settings import Settings
from cashapp.workers.apply_gate import ReceiptApplyGate
from cashapp.workers.inflight import InFlightTrackingBus, StageLimiter

T = TypeVar("T")

log = logging.getLogger(__name__)

LLM_CLIENTS_TYPE: Final = "cashapp.integrations.llm.base:LlmClients"
FAILURE_HANDLER_FACTORY: Final = "cashapp.services.autofix.engine:build_failure_handler"

# "module:Type" -> "module:factory". Types are matched by identity after a lazy import.
_SERVICES: Final[dict[str, str]] = {
    "cashapp.integrations.fusion.client:FusionClient": (
        "cashapp.integrations.fusion.factory:build_fusion_client"
    ),
    "cashapp.integrations.llm.base:LlmClients": (
        "cashapp.integrations.llm.factory:build_llm_clients"
    ),
    "cashapp.integrations.storage.base:ObjectStore": (
        "cashapp.integrations.storage.factory:build_object_store"
    ),
    "cashapp.observability.metrics:Metrics": "cashapp.observability.metrics:build_metrics",
}


class UnknownServiceError(LookupError):
    """``resolve`` was asked for a type nobody registered."""


def load_factory(path: str) -> Callable[..., Any]:
    """Import ``"pkg.mod:attr"`` and return the attribute."""
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError(f"Factory path must look like 'pkg.mod:attr', got {path!r}")
    return cast("Callable[..., Any]", getattr(importlib.import_module(module_name), attr))


def _is_missing_module(exc: ModuleNotFoundError, module_name: str) -> bool:
    """True only when ``module_name`` itself (or a parent package) is what is absent."""
    missing = exc.name
    return missing is not None and (missing == module_name or module_name.startswith(missing + "."))


class WorkerContainer:
    """Satisfies the pipeline ``Container`` Protocol."""

    def __init__(
        self,
        settings: Settings,
        *,
        overrides: Mapping[type[Any], object] | None = None,
        bus: EventBus | None = None,
        uow_factory: UowFactory | None = None,
        config: RuntimeConfig | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings
        self._overrides: dict[type[Any], object] = dict(overrides or {})
        self._given_bus = bus
        self._given_uow_factory = uow_factory
        self._given_config = config
        self._given_clock = clock
        self._resolved: dict[type[Any], object] = {}
        self._engine: Any = None
        self._on_processed: Callable[..., None] | None = None

    # --- members --------------------------------------------------------------------------

    @cached_property
    def clock(self) -> Clock:
        return self._given_clock if self._given_clock is not None else SystemClock()

    @cached_property
    def uow_factory(self) -> UowFactory:
        if self._given_uow_factory is not None:
            return self._given_uow_factory
        atp = self.settings.atp
        # create_engine already sets pool_pre_ping; passing it twice is a TypeError.
        options = {k: v for k, v in atp.engine_kwargs().items() if k != "pool_pre_ping"}
        self._engine = create_engine(atp.url().render_as_string(hide_password=False), **options)
        return make_uow_factory(self._engine)

    @cached_property
    def config(self) -> RuntimeConfig:
        if self._given_config is not None:
            return self._given_config
        return build_runtime_config(self.uow_factory)

    @cached_property
    def limiter(self) -> StageLimiter:
        return StageLimiter(self.config)

    @cached_property
    def tracking_bus(self) -> InFlightTrackingBus:
        inner = self._given_bus if self._given_bus is not None else build_event_bus(self.settings)
        return InFlightTrackingBus(inner, self.limiter, self._notify_processed)

    @property
    def bus(self) -> InFlightTrackingBus:
        return self.tracking_bus

    @cached_property
    def failure_handler(self) -> FailureHandler:
        try:
            factory = load_factory(FAILURE_HANDLER_FACTORY)
        except ModuleNotFoundError as exc:
            module_name = FAILURE_HANDLER_FACTORY.partition(":")[0]
            if not _is_missing_module(exc, module_name):
                raise
            log.warning("auto-fix engine not installed; every failure escalates to a person")
            return EscalateAllHandler()
        return cast("FailureHandler", factory(self))

    # --- processed-event hook (set by HostTelemetry) --------------------------------------

    def set_on_processed(self, callback: Callable[..., None] | None) -> None:
        self._on_processed = callback

    def _notify_processed(self, stage: Any) -> None:
        if self._on_processed is not None:
            self._on_processed(stage)

    # --- resolve --------------------------------------------------------------------------

    def resolve(self, key: type[T]) -> T:
        if key in self._overrides:
            return cast("T", self._overrides[key])
        if key in self._resolved:
            return cast("T", self._resolved[key])
        service = self._build(key)
        self._resolved[key] = service
        return cast("T", service)

    def _build(self, key: type[Any]) -> object:
        if key is ReceiptApplyGate:
            return ReceiptApplyGate(self.config)
        if key is BusHealth:
            return BusHealth(self.bus, TopicNamer.from_settings(self.settings.streaming))
        for type_path, factory_path in _SERVICES.items():
            if load_factory(type_path) is key:
                factory = load_factory(factory_path)
                if type_path == LLM_CLIENTS_TYPE:
                    # Usage rows reuse this container's engine and follow its runtime config.
                    return factory(self.settings, self.config, uow_factory=self.uow_factory)
                return factory(self.settings)
        registered = sorted([*_SERVICES, "ReceiptApplyGate", "BusHealth"])
        raise UnknownServiceError(
            f"No service registered for {key.__name__}. Registered: {', '.join(registered)}"
        )

    # --- shutdown -------------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close services this container built (not injected overrides), the bus, and the engine."""
        for service in list(self._resolved.values()):
            closer = getattr(service, "aclose", None)
            if closer is None:
                continue
            try:
                await closer()
            except Exception:
                log.exception("closing %s failed", type(service).__name__)
        try:
            await self.bus.close()
        except Exception:
            log.exception("closing the event bus failed")
        if self._engine is not None:
            await self._engine.dispose()
