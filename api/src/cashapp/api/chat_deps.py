"""FastAPI wiring for the chat tool registry and the services tools may fetch."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.api.tool_providers import discover_providers
from cashapp.services.chat.tools import build_registry
from cashapp.services.chat.tools.registry import ToolRegistry, ToolServices


@lru_cache
def get_tool_registry() -> ToolRegistry:
    """The one registry per process: every tool module under ``services/chat/tools``."""
    return build_registry()


@lru_cache
def get_tool_services() -> ToolServices:
    """The services tools may fetch, from every provider module. Tests override this."""
    return ToolServices(discover_providers())


ToolRegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]
ToolServicesDep = Annotated[ToolServices, Depends(get_tool_services)]
