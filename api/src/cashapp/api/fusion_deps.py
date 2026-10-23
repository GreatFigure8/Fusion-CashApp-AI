"""Shared FastAPI dependency for the Fusion client. Tests override it with the fake."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.factory import build_fusion_client
from cashapp.settings import get_settings


@lru_cache
def get_fusion_client() -> FusionClient:
    """One Fusion client per API process, built from settings."""
    return build_fusion_client(get_settings())


FusionClientDep = Annotated[FusionClient, Depends(get_fusion_client)]
