"""Fusion integration: the one client every station uses to talk to Oracle Fusion.

`McpFusionClient`, `McpFusionOptions`, `FusionClientFactory` and `build_fusion_client` load on first
use: they import the MCP package, which itself imports `fusion.errors`, so an eager import here
would be circular.
"""

from typing import TYPE_CHECKING, Any

from cashapp.integrations.fusion.client import FusionClient, ReceiptDateBasis
from cashapp.integrations.fusion.errors import (
    FUSION_CODE_MAP,
    NOISE_CODES,
    FusionError,
    FusionFault,
)
from cashapp.integrations.fusion.guard import WRITE_METHODS, WriteGuard, read_only
from cashapp.integrations.fusion.models import (
    ApplyRequest,
    ApplyResult,
    AttachmentRef,
    CustomerRelationship,
    FusionApplication,
    FusionCustomer,
    FusionCustomerSite,
    FusionMessage,
    FusionReceipt,
    FusionTransaction,
    TransactionKind,
    UnapplyRequest,
    UnapplyResult,
)
from cashapp.integrations.fusion.query import q_in, q_literal
from cashapp.integrations.fusion.soap import accounting_date_for

if TYPE_CHECKING:
    from cashapp.integrations.fusion.factory import FusionClientFactory, build_fusion_client
    from cashapp.integrations.fusion.mcp_client import McpFusionClient, McpFusionOptions

_LAZY = {
    "FusionClientFactory": "cashapp.integrations.fusion.factory",
    "build_fusion_client": "cashapp.integrations.fusion.factory",
    "McpFusionClient": "cashapp.integrations.fusion.mcp_client",
    "McpFusionOptions": "cashapp.integrations.fusion.mcp_client",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module), name)


__all__ = [
    "FUSION_CODE_MAP",
    "NOISE_CODES",
    "WRITE_METHODS",
    "ApplyRequest",
    "ApplyResult",
    "AttachmentRef",
    "CustomerRelationship",
    "FusionApplication",
    "FusionClient",
    "FusionClientFactory",
    "FusionCustomer",
    "FusionCustomerSite",
    "FusionError",
    "FusionFault",
    "FusionMessage",
    "FusionReceipt",
    "FusionTransaction",
    "McpFusionClient",
    "McpFusionOptions",
    "ReceiptDateBasis",
    "TransactionKind",
    "UnapplyRequest",
    "UnapplyResult",
    "WriteGuard",
    "accounting_date_for",
    "build_fusion_client",
    "q_in",
    "q_literal",
    "read_only",
]
