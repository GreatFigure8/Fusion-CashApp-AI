"""What a worker process runs: roles, their state, and the container they are built from.

Owned by the pipeline so stations depend on no host code. ``Container`` is a Protocol only; the
worker host (s30) implements it. ``resolve`` looks up integration types (``FusionClient``,
``LlmClients``, ``ObjectStore``, ``ReceiptApplyGate`` and so on) so this module imports none of
them.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol, TypeVar

from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock
from cashapp.services.config import RuntimeConfig
from cashapp.services.runtime_settings import RuntimeSettings
from cashapp.settings import Settings

if TYPE_CHECKING:
    from cashapp.pipeline.bus import EventBus
    from cashapp.pipeline.failures import FailureHandler

T = TypeVar("T")

RoleKind = Literal["consumer", "poller", "relay"]
RoleStatus = Literal["starting", "running", "degraded", "stopping", "stopped"]


@dataclass(slots=True)
class RoleState:
    name: str
    status: RoleStatus
    last_activity_at: datetime | None = None
    detail: str | None = None


class Runnable(Protocol):
    async def run(self, stop: asyncio.Event) -> None: ...

    def state(self) -> RoleState: ...


class Container(Protocol):
    @property
    def settings(self) -> Settings: ...

    @property
    def runtime(self) -> RuntimeSettings: ...

    @property
    def uow_factory(self) -> UowFactory: ...

    @property
    def config(self) -> RuntimeConfig: ...

    @property
    def bus(self) -> "EventBus": ...

    @property
    def clock(self) -> Clock: ...

    @property
    def failure_handler(self) -> "FailureHandler": ...

    def resolve(self, key: type[T]) -> T:
        """The registered service for ``key``; ``KeyError`` when nothing is registered."""
        ...


@dataclass(frozen=True, slots=True)
class RoleSpec:
    name: str
    kind: RoleKind
    build: Callable[[Container], Runnable]
