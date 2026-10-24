"""Providers for the services the core chat tools (and most later ones) need.

Each is built from the dependency the routers already use, so a tool and a router share one
construction path.
"""

from typing import Any

from cashapp.api.config_deps import get_runtime_config
from cashapp.api.fusion_deps import get_fusion_client
from cashapp.api.llm_deps import get_llm_clients
from cashapp.api.mcp_deps import get_mcp_client
from cashapp.api.routers.exceptions import get_exceptions_service
from cashapp.api.routers.requeue import get_requeue_service
from cashapp.api.runtime_deps import get_runtime_settings
from cashapp.api.storage_deps import get_object_store
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.llm.base import LlmClients
from cashapp.integrations.storage.base import ObjectStore
from cashapp.services.autofix.requeue import RequeueService
from cashapp.services.chat.tools.registry import Provider
from cashapp.services.config import RuntimeConfig
from cashapp.services.exceptions_query import ExceptionsQueryService


async def _requeue() -> RequeueService:
    return get_requeue_service(await get_runtime_config())


async def _exceptions() -> ExceptionsQueryService:
    return get_exceptions_service(await get_runtime_config())


def _llm() -> LlmClients:
    return get_llm_clients(get_runtime_settings())


def _store() -> ObjectStore:
    return get_object_store(get_runtime_settings())


def _fusion() -> FusionClient:
    runtime = get_runtime_settings()
    return get_fusion_client(runtime, get_mcp_client(runtime))


PROVIDERS: dict[type[Any], Provider] = {
    RuntimeConfig: get_runtime_config,
    LlmClients: _llm,
    ObjectStore: _store,
    FusionClient: _fusion,
    RequeueService: _requeue,
    ExceptionsQueryService: _exceptions,
}
