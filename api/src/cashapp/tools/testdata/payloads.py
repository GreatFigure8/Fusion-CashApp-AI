"""POST bodies for the test-data records.

Every field name here is UNVERIFIED until confirmed on a non-production pod (see CONTRACTS.md);
all of them live in this module so a rename touches one file. Money is serialised as a 2 dp string.
Business unit, transaction type, receipt method and bank account come from the pod's `testdata`
settings, never from code.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from cashapp.domain.config_keys import FusionTestData
from cashapp.integrations.fusion.query import FIELDS_REMITTANCE_REFERENCE
from cashapp.tools.testdata.models import PlannedReceipt, PlannedTransaction
from cashapp.tools.testdata.tagging import tag_marker

# UNVERIFIED: resource paths and the complete action.
PATH_INVOICES: Final = "receivablesInvoices"
PATH_CREDIT_MEMOS: Final = "receivablesCreditMemos"
PATH_RECEIPTS: Final = "standardReceipts"
ACTION_COMPLETE: Final = "action/completeTransaction"

# UNVERIFIED: body field names.
TRANSACTION_SOURCE: Final = "Manual"  # UNVERIFIED: batch source for manually created invoices
INVOICE_LINES_KEY: Final = "receivablesInvoiceLines"  # UNVERIFIED: child resource name
REFERENCES_KEY: Final = "remittanceReferences"  # UNVERIFIED: nested child on the receipt


def money_text(value: Decimal) -> str:
    return f"{value:.2f}"


def complete_path(resource: str, fusion_id: int) -> str:
    return f"{resource}/{int(fusion_id)}/{ACTION_COMPLETE}"


def _transaction_body(
    txn: PlannedTransaction,
    *,
    tag: str,
    customer_account: str,
    defaults: FusionTestData,
    bill_to_site: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "TransactionNumber": txn.number,
        "BusinessUnit": defaults.business_unit,
        "TransactionSource": TRANSACTION_SOURCE,
        "TransactionType": defaults.transaction_type,
        "TransactionDate": txn.transaction_date.isoformat(),
        "AccountingDate": txn.transaction_date.isoformat(),
        "BillToCustomerNumber": customer_account,
        "Comments": tag_marker(tag),
        INVOICE_LINES_KEY: [
            {
                "LineNumber": 1,
                "Description": f"CashApp test data {txn.number}",
                "Quantity": 1,
                "UnitSellingPrice": money_text(txn.amount),
            }
        ],
    }
    if bill_to_site is not None:
        body["BillToSite"] = bill_to_site
    if txn.terms is not None:
        body["PaymentTerms"] = txn.terms
    return body


def invoice_payload(
    txn: PlannedTransaction,
    *,
    tag: str,
    customer_account: str,
    defaults: FusionTestData,
    bill_to_site: str | None = None,
) -> dict[str, Any]:
    body = _transaction_body(
        txn,
        tag=tag,
        customer_account=customer_account,
        defaults=defaults,
        bill_to_site=bill_to_site,
    )
    body["InvoiceCurrencyCode"] = txn.currency
    return body


def credit_memo_payload(
    txn: PlannedTransaction,
    *,
    tag: str,
    customer_account: str,
    defaults: FusionTestData,
    bill_to_site: str | None = None,
) -> dict[str, Any]:
    """Same shape as an invoice on the credit memo resource; the line price is negative."""
    body = _transaction_body(
        txn,
        tag=tag,
        customer_account=customer_account,
        defaults=defaults,
        bill_to_site=bill_to_site,
    )
    body["CurrencyCode"] = txn.currency  # UNVERIFIED: the credit memo currency field name
    return body


def receipt_payload(
    receipt: PlannedReceipt,
    *,
    tag: str,
    customer_account: str,
    defaults: FusionTestData,
) -> dict[str, Any]:
    """An unapplied receipt: there is deliberately no application child in the body."""
    body: dict[str, Any] = {
        "ReceiptNumber": receipt.number,
        "BusinessUnit": defaults.business_unit,
        "ReceiptMethod": defaults.receipt_method,
        "ReceiptDate": receipt.receipt_date.isoformat(),
        "AccountingDate": receipt.receipt_date.isoformat(),
        "Amount": money_text(receipt.amount),
        "Currency": receipt.currency,
        "CustomerAccountNumber": customer_account,
        "RemittanceBankAccountNumber": defaults.bank_account,  # UNVERIFIED
        "Comments": tag_marker(tag),
    }
    if receipt.references:
        body[REFERENCES_KEY] = [{FIELDS_REMITTANCE_REFERENCE: ref} for ref in receipt.references]
    return body
