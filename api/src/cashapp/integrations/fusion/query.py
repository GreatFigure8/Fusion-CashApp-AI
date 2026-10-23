"""REST query building: the only place `q=` literals are produced."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime

REST_BASE = "/fscmRestApi/resources/11.13.18.05"
CRM_BASE = "/crmRestApi/resources/11.13.18.05"  # UNVERIFIED
CUSTOMER_ACCOUNTS_PATH = f"{CRM_BASE}/accounts"  # UNVERIFIED: resource name

# Explicit field lists (CLAUDE.md: always send fields=). Names marked UNVERIFIED are tracked in
# CONTRACTS.md and confirmed by the live probes.
FIELDS_INVOICE = ",".join(
    [
        "CustomerTransactionId",
        "TransactionNumber",
        "InvoiceBalanceAmount",
        "EnteredAmount",  # UNVERIFIED: original amount field
        "BillToCustomerNumber",
        "BillToSite",  # UNVERIFIED
        "BusinessUnit",
        "InvoiceCurrencyCode",
        "InvoiceStatus",
        "PaymentTerms",  # UNVERIFIED
    ]
)
FIELDS_CREDIT_MEMO = ",".join(
    [
        "CustomerTransactionId",
        "TransactionNumber",
        "TransactionBalanceDue",  # UNVERIFIED
        "EnteredAmount",  # UNVERIFIED
        "BillToCustomerNumber",
        "BillToSite",  # UNVERIFIED
        "BusinessUnit",
        "CurrencyCode",  # UNVERIFIED
        "TransactionStatus",  # UNVERIFIED
    ]
)
FIELDS_RECEIPT = ",".join(
    [
        "StandardReceiptId",
        "ReceiptNumber",
        "Amount",
        "UnappliedAmount",
        "Currency",
        "CustomerAccountNumber",
        "ReceiptDate",
        "CreationDate",  # UNVERIFIED
        "Status",
        "State",
        "Comments",  # UNVERIFIED
    ]
)
FIELDS_REMITTANCE_REFERENCE = "ReferenceNumber"  # UNVERIFIED
FIELDS_RECEIPT_APPLICATION = ",".join(  # UNVERIFIED: child resource and every field
    ["ReceivableApplicationId", "CustomerTransactionId", "AmountApplied", "ApplyDate", "Status"]
)
FIELDS_ATTACHMENTS = "AttachedDocumentId,FileName,Title,CreationDate"  # UNVERIFIED (s17)
FIELDS_CUSTOMER_ACCOUNT = ",".join(  # UNVERIFIED: resource and every field
    ["AccountNumber", "PartyName", "SiteNumber", "SitePurpose", "Location", "Address", "Currency"]
)

_CONTROL_LIMIT = 0x20


def q_literal(value: str) -> str:
    """Quote a string for a Fusion `q=` expression: single quotes doubled, control chars refused."""
    if any(ord(ch) < _CONTROL_LIMIT or ord(ch) == 0x7F for ch in value):
        raise ValueError("control characters are not allowed in a Fusion query literal")
    return "'" + value.replace("'", "''") + "'"


def q_in(field: str, values: Sequence[str]) -> str:
    if not values:
        raise ValueError("q_in needs at least one value")
    return f"{field} in ({','.join(q_literal(v) for v in values)})"


def q_date(value: date) -> str:
    return q_literal(value.isoformat())


def q_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    # UNVERIFIED: CreationDate literal format.
    return q_literal(value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00"))


def chunked(values: Iterable[str], size: int = 50) -> list[list[str]]:
    """Deduplicate (order kept) then split into chunks of at most `size`."""
    if size < 1:
        raise ValueError("size must be positive")
    unique = list(dict.fromkeys(values))
    return [unique[i : i + size] for i in range(0, len(unique), size)]
