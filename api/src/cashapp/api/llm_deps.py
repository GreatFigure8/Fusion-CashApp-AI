"""FastAPI dependency for the LLM role clients. Defined once; routers import ``LlmClientsDep``."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.integrations.llm.base import LlmClients
from cashapp.integrations.llm.factory import build_llm_clients
from cashapp.settings import get_settings


@lru_cache
def get_llm_clients() -> LlmClients:
    """One set of role clients per process, built from settings. Tests override this."""
    return build_llm_clients(get_settings())


LlmClientsDep = Annotated[LlmClients, Depends(get_llm_clients)]
