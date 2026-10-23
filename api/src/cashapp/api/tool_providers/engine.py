"""The chat tool provider for engine control: how a tool handler gets its ``EngineService``.

Built from the same process-wide service the router uses, so a chat action and a button press
share one status cache and one set of rules.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from cashapp.api.engine_deps import get_engine_service
from cashapp.services.engine.service import EngineService

PROVIDERS: dict[type[Any], Callable[[], object | Awaitable[object]]] = {
    EngineService: get_engine_service,
}
