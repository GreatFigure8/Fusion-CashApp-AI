"""Extra receipt signals from the receipt-signals data model, SQL run through the MCP server
(statement line reference, payer bank account hash). Best effort: a missing model or a parse failure
yields no evidence, never an error. Bank account hashes and statement references stay in memory;
nothing here is persisted.
"""

import logging
from collections.abc import Sequence
from typing import Final

from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.datamodels import RECEIPT_SIGNALS_PATH
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import FusionReceipt
from cashapp.integrations.fusion.xmlutil import (
    XmlParseError,
    child_text,
    iter_local,
    safe_fromstring,
)
from cashapp.services.matching.receipts import ReceiptEvidence

# The data model's catalog name (integrations/fusion/datamodels; UNVERIFIED live).
RECEIPT_SIGNALS_REPORT_PATH: Final = RECEIPT_SIGNALS_PATH

_ROW_TAG: Final = "G_1"


def _parse(xml: bytes, wanted: set[int]) -> dict[int, ReceiptEvidence]:
    found: dict[int, ReceiptEvidence] = {}
    for row in iter_local(safe_fromstring(xml), _ROW_TAG):
        raw_id = child_text(row, "CASH_RECEIPT_ID")
        if raw_id is None or not raw_id.isdigit() or int(raw_id) not in wanted:
            continue
        receipt_id = int(raw_id)
        previous = found.get(receipt_id)
        reference = child_text(row, "STATEMENT_LINE_REFERENCE")
        account = child_text(row, "PAYER_BANK_ACCOUNT_HASH")
        found[receipt_id] = ReceiptEvidence(
            receipt_id=receipt_id,
            statement_reference=reference or (previous.statement_reference if previous else None),
            payer_bank_account=account or (previous.payer_bank_account if previous else None),
        )
    return found


async def fetch_receipt_evidence(
    fusion: FusionClient,
    receipts: Sequence[FusionReceipt],
    *,
    log: logging.Logger | logging.LoggerAdapter[logging.Logger],
) -> dict[int, ReceiptEvidence]:
    """Evidence for the pool's receipts; ``{}`` plus one warning when the report is missing."""
    if not receipts:
        return {}
    dates = [r.receipt_date for r in receipts]
    params = {
        "P_DATE_FROM": min(dates).isoformat(),
        "P_DATE_TO": max(dates).isoformat(),
    }
    try:
        xml = await fusion.run_report(RECEIPT_SIGNALS_REPORT_PATH, params)
        return _parse(xml, {r.receipt_id for r in receipts})
    except (FusionError, XmlParseError) as exc:
        log.warning(
            "receipt_signals_unavailable",
            extra={"error_type": type(exc).__name__, "receipt_count": len(receipts)},
        )
        return {}
