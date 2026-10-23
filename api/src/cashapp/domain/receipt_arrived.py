"""The ``ReceiptArrived`` event: "Fusion has a new receipt". Pure model, no upward imports."""

from datetime import date
from typing import TYPE_CHECKING, Final, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from cashapp.domain.money import CurrencyCode, MoneyStr

if TYPE_CHECKING:
    from cashapp.integrations.fusion.models import FusionReceipt

# The topic is ``default_namer().named(RECEIPT_ARRIVED_TOPIC)``; the message key is the receipt id.
RECEIPT_ARRIVED_TOPIC: Final = "receipt-arrived"


class ReceiptArrived(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid4)
    receipt_id: int
    receipt_number: str
    customer_account_number: str | None
    currency: CurrencyCode
    amount: MoneyStr
    unapplied_amount: MoneyStr
    receipt_date: date
    creation_date: AwareDatetime

    @classmethod
    def from_fusion(cls, r: "FusionReceipt", *, event_id: UUID | None = None) -> Self:
        return cls(
            event_id=event_id if event_id is not None else uuid4(),
            receipt_id=r.receipt_id,
            receipt_number=r.receipt_number,
            customer_account_number=r.customer_account_number,
            currency=r.currency,
            amount=r.amount,
            unapplied_amount=r.unapplied_amount,
            receipt_date=r.receipt_date,
            creation_date=r.creation_date,
        )
