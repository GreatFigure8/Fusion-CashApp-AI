"""FastAPI dependencies for the event bus, read-only from the API.

The API only asks the bus for consumer lag and dead-letter depth; it never publishes (events go
out through the outbox). One bus client and one ``BusHealth`` per process, built on first use.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.api.runtime_deps import get_runtime_settings
from cashapp.pipeline.bus import EventBus, build_event_bus
from cashapp.pipeline.events import TopicNamer
from cashapp.pipeline.health import BusHealth


@lru_cache
def get_event_bus() -> EventBus:
    """The process-wide bus client. Tests override this dependency."""
    return build_event_bus(get_runtime_settings())


@lru_cache
def get_bus_health() -> BusHealth:
    runtime = get_runtime_settings()
    return BusHealth(get_event_bus(), TopicNamer.from_config(runtime.streaming(), runtime.env))


EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
BusHealthDep = Annotated[BusHealth, Depends(get_bus_health)]
