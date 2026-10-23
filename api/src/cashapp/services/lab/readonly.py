"""A read-only face of the Fusion client for the matching lab.

The wrapper exposes read methods only. There is no write attribute to call, so a replay can
never apply, unapply, comment on or attach to a receipt (pyright and the attribute check agree).
"""

from collections.abc import Mapping, Sequence
from datetime import date

from cashapp.integrations.fusion.client import FusionClient, ReceiptDateBasis
from cashapp.integrations.fusion.models import (
    CustomerRelationship,
    FusionApplication,
    FusionReceipt,
    FusionTransaction,
    PaymentTerms,
)


class ReadOnlyFusion:
    def __init__(self, client: FusionClient) -> None:
        self.__client = client

    async def find_receipts(
        self,
        *,
        customer_numbers: Sequence[str],
        date_from: date,
        date_to: date,
        by: ReceiptDateBasis = "receipt_date",
    ) -> list[FusionReceipt]:
        return await self.__client.find_receipts(
            customer_numbers=customer_numbers, date_from=date_from, date_to=date_to, by=by
        )

    async def get_receipt(self, receipt_id: int) -> FusionReceipt:
        return await self.__client.get_receipt(receipt_id)

    async def find_transactions(self, numbers: Sequence[str]) -> list[FusionTransaction]:
        return await self.__client.find_transactions(numbers)

    async def list_receipt_applications(self, receipt_id: int) -> list[FusionApplication]:
        return await self.__client.list_receipt_applications(receipt_id)

    async def run_report(self, path: str, params: Mapping[str, str], fmt: str = "xml") -> bytes:
        return await self.__client.run_report(path, params, fmt)

    async def get_payment_terms(self, term: int | str) -> PaymentTerms | None:
        return await self.__client.get_payment_terms(term)

    async def customer_relationships(
        self, account_numbers: Sequence[str]
    ) -> list[CustomerRelationship]:
        return await self.__client.customer_relationships(account_numbers)
