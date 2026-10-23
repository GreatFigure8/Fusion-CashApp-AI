"""The Fusion MCP connection: live status for the connection card, and a one-click test."""

from typing import Annotated

from fastapi import APIRouter, Depends

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.fusion_deps import FusionClientDep
from cashapp.api.mcp_deps import McpClientDep
from cashapp.api.schemas.mcp import McpStatusOut, McpTestOut
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.mcp_status import McpStatusService

router = APIRouter(prefix="/integrations/mcp", tags=["integrations"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_READ))]
WriterDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_WRITE))]

_service: McpStatusService | None = None


def get_mcp_status_service(
    mcp: McpClientDep,
    fusion: FusionClientDep,
    config: RuntimeConfigDep,
    uow_factory: UowFactoryDep,
) -> McpStatusService:
    """One service per process (it holds the 15 second health cache); tests override this."""
    global _service
    if _service is None:
        _service = McpStatusService(mcp, fusion, config, uow_factory)
    return _service


StatusServiceDep = Annotated[McpStatusService, Depends(get_mcp_status_service)]


@router.get("/status", response_model=McpStatusOut)
async def get_status(_: ReaderDep, service: StatusServiceDep) -> McpStatusOut:
    return McpStatusOut.of(await service.status())


@router.post("/test", response_model=McpTestOut)
async def run_test(principal: WriterDep, service: StatusServiceDep) -> McpTestOut:
    """Never a 5xx for a server failure: the failure is reported in `error`."""
    return McpTestOut.of(await service.test(principal))
