"""Fusion integration: the one client every station uses to talk to Oracle Fusion."""

from cashapp.integrations.fusion.client import (
    FusionClient,
    FusionClientOptions,
    HttpFusionClient,
    ReceiptDateBasis,
)
from cashapp.integrations.fusion.errors import (
    FUSION_CODE_MAP,
    NOISE_CODES,
    FusionError,
    FusionFault,
)
from cashapp.integrations.fusion.factory import FusionClientFactory, build_fusion_client
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
    "FusionClientOptions",
    "FusionCustomer",
    "FusionCustomerSite",
    "FusionError",
    "FusionFault",
    "FusionMessage",
    "FusionReceipt",
    "FusionTransaction",
    "HttpFusionClient",
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
