"""`FusionClient`: the one interface every station uses to talk to Fusion.

`McpFusionClient` (mcp_client.py) is the real implementation: reads and REST writes go through
the fusion-sql-mcp server, the receipt apply goes direct over SOAP. `FakeFusionClient` (fake.py)
is the in-memory twin. Names marked UNVERIFIED are tracked in CONTRACTS.md and confirmed by the
`-m live` probes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Literal, Protocol

from cashapp.integrations.fusion.models import (
    ApplyRequest,
    ApplyResult,
    AttachmentRef,
    CustomerRelationship,
    FusionApplication,
    FusionCustomer,
    FusionReceipt,
    FusionTransaction,
    PaymentTerms,
    UnapplyRequest,
    UnapplyResult,
)

__all__ = ["FusionClient", "ReceiptDateBasis"]

ReceiptDateBasis = Literal["receipt_date", "creation_date"]


class FusionClient(Protocol):
    pod_name: str

    async def find_transactions(self, numbers: Sequence[str]) -> list[FusionTransaction]: ...

    async def find_receipts(
        self,
        *,
        customer_numbers: Sequence[str],
        date_from: date,
        date_to: date,
        by: ReceiptDateBasis = "receipt_date",
    ) -> list[FusionReceipt]: ...

    async def receipts_created_since(
        self, since: datetime, *, limit: int = 500
    ) -> list[FusionReceipt]: ...

    async def get_receipt(self, receipt_id: int) -> FusionReceipt: ...

    async def list_receipt_applications(self, receipt_id: int) -> list[FusionApplication]: ...

    async def list_transaction_applications(
        self, customer_trx_id: int
    ) -> list[FusionApplication]: ...

    async def get_customer_account(self, account_number: str) -> FusionCustomer: ...

    async def get_payment_terms(self, term: int | str) -> PaymentTerms | None: ...

    async def customer_relationships(
        self, account_numbers: Sequence[str]
    ) -> list[CustomerRelationship]: ...

    async def apply_receipt(self, request: ApplyRequest) -> ApplyResult: ...

    async def unapply_receipt(self, request: UnapplyRequest) -> UnapplyResult: ...

    async def set_receipt_comment(self, receipt_id: int, text: str) -> None: ...

    async def attach_to_receipt(
        self, receipt_id: int, filename: str, content: bytes, content_type: str, title: str
    ) -> AttachmentRef: ...

    async def list_receipt_attachments(self, receipt_id: int) -> list[AttachmentRef]: ...

    async def run_report(self, path: str, params: Mapping[str, str], fmt: str = "xml") -> bytes: ...

    async def rest_get(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> dict[str, Any]: ...

    async def get_raw(self, path: str, params: Mapping[str, str] | None = None) -> bytes: ...

    async def rest_post(self, path: str, json: Mapping[str, Any]) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...
