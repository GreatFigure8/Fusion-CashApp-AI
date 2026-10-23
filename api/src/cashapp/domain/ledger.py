"""The application ledger vocabulary: one definition for stations, routers and reporting."""

from enum import StrEnum
from typing import Final


class LedgerStatus(StrEnum):
    PLANNED = "PLANNED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    DRY_RUN = "DRY_RUN"


APPLIED_BY_SYSTEM: Final = "system"


def idempotency_key(item_id: int, receipt_id: int, customer_trx_id: int) -> str:
    """One ledger row per (work item, receipt, transaction)."""
    return f"{item_id}:{receipt_id}:{customer_trx_id}"
