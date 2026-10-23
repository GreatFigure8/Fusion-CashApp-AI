"""FastAPI dependency for the LLM role clients. Defined once; routers import ``LlmClientsDep``."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.integrations.llm.base import LlmClients
from cashapp.integrations.llm.factory import build_llm_clients
from cashapp.services.runtime_settings import RuntimeSettings


@lru_cache
def _clients_for(runtime: RuntimeSettings) -> LlmClients:
    return build_llm_clients(runtime)


def get_llm_clients(runtime: RuntimeSettingsDep) -> LlmClients:
    """One set of role clients per process, built from settings. Tests override this."""
    return _clients_for(runtime)


LlmClientsDep = Annotated[LlmClients, Depends(get_llm_clients)]
