"""Shared FastAPI dependency for the Fusion client. Tests override it with the fake."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.factory import build_fusion_client
from cashapp.services.runtime_settings import RuntimeSettings


@lru_cache
def _client_for(runtime: RuntimeSettings) -> FusionClient:
    return build_fusion_client(runtime)


def get_fusion_client(runtime: RuntimeSettingsDep) -> FusionClient:
    """One Fusion client per API process, built from the DB-stored settings."""
    return _client_for(runtime)


FusionClientDep = Annotated[FusionClient, Depends(get_fusion_client)]
