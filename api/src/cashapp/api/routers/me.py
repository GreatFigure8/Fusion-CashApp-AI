"""The signed-in caller's identity, roles and permissions."""

import logging

from fastapi import APIRouter

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.schemas.me import MeResponse
from cashapp.auth.deps import PrincipalDep
from cashapp.services.config import ConfigSnapshot
from cashapp.services.ui_context import resolve_ui_context
from cashapp.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["identity"])


@router.get("/me", response_model=MeResponse)
async def get_me(principal: PrincipalDep, runtime: RuntimeConfigDep) -> MeResponse:
    snapshot: ConfigSnapshot | None
    try:
        snapshot = await runtime.snapshot()
    except Exception as exc:  # /me must keep answering when the config store is down
        logger.warning("UI context config unreadable: %s", type(exc).__name__)
        snapshot = None
    return MeResponse.from_principal(principal, resolve_ui_context(get_settings().env, snapshot))
