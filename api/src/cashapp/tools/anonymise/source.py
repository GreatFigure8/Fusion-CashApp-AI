"""The local source folder: the previous build's production day and AR's labelled failure set.

Folder layout (UTF-8; CSV read with ``csv.DictReader``):

* ``messages.jsonl``: ``{message_id, payload, outcome}`` per line. ``payload`` is the prior
  extraction contract (``payerName``, optional ``payerBankAccount``, ``payments[]`` with
  ``reference_number``, ``payment_amount``, ``payment_date``, ``payment_currency``, optional
  ``po_refs`` / ``sales_order_refs`` / ``ers_refs`` and ``allocations[]`` with
  ``application_type``, ``invoice_number``, ``applied_amount``, ``credit_memo_id``; other keys such
  as ``paymentSummary`` or ``statusDescription`` are never read). ``outcome`` is
  ``{payment_status, lines[{invoice_number, line_status, applied_amount}], receipt_number}``.
* ``fusion/customers.csv``, ``transactions.csv``, ``receipts.csv``, ``applications.csv``,
  ``relationships.csv`` (all optional).
* ``labelled/failures.csv`` (optional): one row per failed line.

The real export is adapted to this shape here and nowhere else. Errors name the file, the line and
the field, never the value.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, NoReturn

from pydantic import BaseModel

from cashapp.domain.status import LineStatus, PaymentStatus
from cashapp.tools.anonymise.fixture_format import PriorLabel

MESSAGES_FILE: Final = "messages.jsonl"
CUSTOMERS_FILE: Final = "fusion/customers.csv"
TRANSACTIONS_FILE: Final = "fusion/transactions.csv"
RECEIPTS_FILE: Final = "fusion/receipts.csv"
APPLICATIONS_FILE: Final = "fusion/applications.csv"
RELATIONSHIPS_FILE: Final = "fusion/relationships.csv"
FAILURES_FILE: Final = "labelled/failures.csv"

_INVOICE_TYPES: Final = frozenset({"payment", "invoice"})
_CREDIT_MEMO_TYPES: Final = frozenset({"credit memo", "creditmemo", "credit_memo"})
_TRANSACTION_KINDS: Final = frozenset({"INVOICE", "CREDIT_MEMO"})

STATUS_ALIASES: Final[Mapping[str, PaymentStatus | LineStatus]] = MappingProxyType(
    {
        **{status.value: status for status in PaymentStatus},
        **{status.value: status for status in LineStatus},
        # s02 split the old catch-all apply failure into system / closed / zero-balance.
        "payment-apply-failed": PaymentStatus.PAYMENT_APPLY_FAILED_SYSTEM,
    }
)


def _label_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


LABEL_ALIASES: Final[Mapping[str, PriorLabel]] = MappingProxyType(
    {
        **{label.value: label for label in PriorLabel},
        "receipt_found_in_fusion": PriorLabel.RECEIPT_IN_FUSION,
        "in_fusion": PriorLabel.RECEIPT_IN_FUSION,
        "receipt_exists_in_fusion": PriorLabel.RECEIPT_IN_FUSION,
        "receipt_not_yet_entered": PriorLabel.NOT_YET_ENTERED,
        "not_entered_yet": PriorLabel.NOT_YET_ENTERED,
        "not_yet_in_fusion": PriorLabel.NOT_YET_ENTERED,
        "receipt_not_in_fusion": PriorLabel.NOT_IN_FUSION,
        "never_in_fusion": PriorLabel.NOT_IN_FUSION,
        "future_dated": PriorLabel.FUTURE,
        "future_receipt": PriorLabel.FUTURE,
        "future_dated_receipt": PriorLabel.FUTURE,
    }
)


class SourceFormatError(Exception):
    """The source folder does not match the pinned shape; names file, line and field only."""

    def __init__(self, file: str, line: int, field: str, reason: str) -> None:
        self.file = file
        self.line = line
        self.field = field
        self.reason = reason
        super().__init__(f"{file}:{line}: {field}: {reason}")


class SourceAllocation(BaseModel, frozen=True):
    transaction_number: str
    credit_memo: bool
    applied_amount: Decimal | None
    po_number: str | None = None
    sales_order: str | None = None
    ers_reference: str | None = None


class SourceOutcomeLine(BaseModel, frozen=True):
    transaction_number: str
    line_status: LineStatus
    applied_amount: Decimal | None


class SourceOutcome(BaseModel, frozen=True):
    payment_status: PaymentStatus
    lines: list[SourceOutcomeLine]
    receipt_number: str | None = None


class SourceMessage(BaseModel, frozen=True):
    """One payment of one message (a message with several payments becomes several of these)."""

    message_id: str
    payer_name: str | None
    payer_bank_account: str | None
    reference_number: str | None
    payment_amount: Decimal | None
    payment_date: date | None
    payment_currency: str | None
    allocations: list[SourceAllocation]
    po_refs: list[str]
    sales_order_refs: list[str]
    ers_refs: list[str]
    outcome: SourceOutcome


class SourceCustomer(BaseModel, frozen=True):
    account_number: str
    name: str
    currency_codes: tuple[str, ...]


class SourceTransaction(BaseModel, frozen=True):
    number: str
    kind: str
    original_amount: Decimal
    balance: Decimal
    currency: str
    status: str
    bill_to_customer_number: str | None
    bill_to_site: str | None
    business_unit: str | None
    payment_terms: str | None


class SourceReceipt(BaseModel, frozen=True):
    receipt_number: str
    amount: Decimal
    unapplied_amount: Decimal
    currency: str
    customer_account_number: str | None
    receipt_date: date
    creation_date: datetime
    status: str
    state: str
    remittance_references: tuple[str, ...]
    comments: str | None
    payer_bank_account: str | None


class SourceApplication(BaseModel, frozen=True):
    receipt_number: str
    transaction_number: str
    amount_applied: Decimal
    apply_date: date


class SourceRelationship(BaseModel, frozen=True):
    account_number: str
    related_account_number: str


class SourceLineLabel(BaseModel, frozen=True):
    transaction_number: str
    label: PriorLabel
    fusion_amount: Decimal | None


class SourceFailure(BaseModel, frozen=True):
    message_id: str
    label: PriorLabel
    fusion_amount: Decimal | None
    lines: list[SourceLineLabel]


class SourceBundle(BaseModel, frozen=True):
    messages: list[SourceMessage]
    customers: list[SourceCustomer]
    transactions: list[SourceTransaction]
    receipts: list[SourceReceipt]
    applications: list[SourceApplication]
    relationships: list[SourceRelationship]
    failures: list[SourceFailure]
    numeric_ids_coerced: int = 0


# --- field helpers ------------------------------------------------------------


class _Ctx:
    """Where a value came from, for error messages."""

    def __init__(self, file: str, line: int) -> None:
        self.file = file
        self.line = line
        self.coerced = 0

    def fail(self, field: str, reason: str) -> NoReturn:
        raise SourceFormatError(self.file, self.line, field, reason)


def _text(raw: object, ctx: _Ctx, field: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        ctx.fail(field, "expected text")
    stripped = raw.strip()
    return stripped or None


def _required_text(raw: object, ctx: _Ctx, field: str) -> str:
    value = _text(raw, ctx, field)
    if value is None:
        ctx.fail(field, "value is required")
    return value


def _identifier(raw: object, ctx: _Ctx, field: str) -> str | None:
    """Identifiers are strings; a JSON number is converted without exponent expansion."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        ctx.fail(field, "expected text or number")
    if isinstance(raw, int):
        ctx.coerced += 1
        return str(raw)
    if isinstance(raw, Decimal):
        rendered = str(raw)
        if "e" in rendered.casefold():
            ctx.fail(field, "number is written with an exponent; export it as text")
        ctx.coerced += 1
        return rendered
    return _text(raw, ctx, field)


def _required_identifier(raw: object, ctx: _Ctx, field: str) -> str:
    value = _identifier(raw, ctx, field)
    if value is None:
        ctx.fail(field, "value is required")
    return value


def _amount(raw: object, ctx: _Ctx, field: str) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        ctx.fail(field, "expected an amount")
    if isinstance(raw, int | Decimal):
        value = Decimal(raw)
    elif isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            value = Decimal(raw.strip().replace(",", ""))
        except InvalidOperation:
            ctx.fail(field, "not a valid amount")
    else:
        ctx.fail(field, "expected an amount")
    if not value.is_finite():
        ctx.fail(field, "not a valid amount")
    return value


def _required_amount(raw: object, ctx: _Ctx, field: str) -> Decimal:
    value = _amount(raw, ctx, field)
    if value is None:
        ctx.fail(field, "value is required")
    return value


def _date(raw: object, ctx: _Ctx, field: str) -> date | None:
    text = _text(raw, ctx, field)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        ctx.fail(field, "not an ISO 8601 date")


def _datetime(raw: object, ctx: _Ctx, field: str) -> datetime:
    text = _required_text(raw, ctx, field)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        ctx.fail(field, "not an ISO 8601 datetime")
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _mapping(raw: object, ctx: _Ctx, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        ctx.fail(field, "expected an object")
    return raw  # pyright: ignore[reportUnknownVariableType]


def _sequence(raw: object, ctx: _Ctx, field: str) -> Sequence[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        ctx.fail(field, "expected a list")
    return raw  # pyright: ignore[reportUnknownVariableType]


def _identifier_list(raw: object, ctx: _Ctx, field: str) -> list[str]:
    items: list[str] = []
    for item in _sequence(raw, ctx, field):
        value = _identifier(item, ctx, field)
        if value is not None:
            items.append(value)
    return items


def _payment_status(raw: object, ctx: _Ctx, field: str) -> PaymentStatus:
    status = STATUS_ALIASES.get(_required_text(raw, ctx, field).casefold())
    if not isinstance(status, PaymentStatus):
        ctx.fail(field, "unknown payment status")
    return status


def _line_status(raw: object, ctx: _Ctx, field: str) -> LineStatus:
    status = STATUS_ALIASES.get(_required_text(raw, ctx, field).casefold())
    if not isinstance(status, LineStatus):
        ctx.fail(field, "unknown line status")
    return status


def _label(raw: object, ctx: _Ctx, field: str) -> PriorLabel:
    label = LABEL_ALIASES.get(_label_key(_required_text(raw, ctx, field)))
    if label is None:
        ctx.fail(field, "unknown label")
    return label


# --- messages.jsonl ------------------------------------------------------------


def _parse_allocation(raw: object, ctx: _Ctx) -> SourceAllocation:
    item = _mapping(raw, ctx, "allocations")
    kind = (_required_text(item.get("application_type"), ctx, "application_type")).casefold()
    if kind in _INVOICE_TYPES:
        credit_memo = False
    elif kind in _CREDIT_MEMO_TYPES:
        credit_memo = True
    else:
        ctx.fail("application_type", "unknown application type")
    invoice = _identifier(item.get("invoice_number"), ctx, "invoice_number")
    memo = _identifier(item.get("credit_memo_id"), ctx, "credit_memo_id")
    number = (memo or invoice) if credit_memo else (invoice or memo)
    if number is None:
        ctx.fail("invoice_number", "allocation has no transaction number")
    return SourceAllocation(
        transaction_number=number,
        credit_memo=credit_memo,
        applied_amount=_amount(item.get("applied_amount"), ctx, "applied_amount"),
        po_number=_identifier(item.get("po_number"), ctx, "po_number"),
        sales_order=_identifier(item.get("sales_order"), ctx, "sales_order"),
        ers_reference=_identifier(item.get("ers_reference"), ctx, "ers_reference"),
    )


def _parse_outcome(
    raw: object, ctx: _Ctx
) -> tuple[PaymentStatus, list[SourceOutcomeLine], str | None]:
    outcome = _mapping(raw, ctx, "outcome")
    lines: list[SourceOutcomeLine] = []
    for item in _sequence(outcome.get("lines"), ctx, "outcome.lines"):
        line = _mapping(item, ctx, "outcome.lines")
        lines.append(
            SourceOutcomeLine(
                transaction_number=_required_identifier(
                    line.get("invoice_number"), ctx, "outcome.invoice_number"
                ),
                line_status=_line_status(line.get("line_status"), ctx, "outcome.line_status"),
                applied_amount=_amount(line.get("applied_amount"), ctx, "outcome.applied_amount"),
            )
        )
    return (
        _payment_status(outcome.get("payment_status"), ctx, "outcome.payment_status"),
        lines,
        _identifier(outcome.get("receipt_number"), ctx, "outcome.receipt_number"),
    )


def _parse_messages(path: Path) -> tuple[list[SourceMessage], int]:
    name = MESSAGES_FILE
    messages: list[SourceMessage] = []
    seen: set[str] = set()
    coerced = 0
    with path.open(encoding="utf-8") as handle:
        for number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            ctx = _Ctx(name, number)
            try:
                document = json.loads(raw_line, parse_float=Decimal)
            except json.JSONDecodeError:
                ctx.fail("line", "not valid JSON")
            root = _mapping(document, ctx, "line")
            base_id = _required_identifier(root.get("message_id"), ctx, "message_id")
            if base_id in seen:
                ctx.fail("message_id", "duplicate message id")
            seen.add(base_id)
            payload = _mapping(root.get("payload"), ctx, "payload")
            status, outcome_lines, receipt_number = _parse_outcome(root.get("outcome"), ctx)
            payments = _sequence(payload.get("payments"), ctx, "payments")
            if not payments:
                ctx.fail("payments", "message has no payments")
            allocations_by_payment = [
                [
                    _parse_allocation(a, ctx)
                    for a in _sequence(
                        _mapping(p, ctx, "payments").get("allocations"), ctx, "allocations"
                    )
                ]
                for p in payments
            ]
            for index, raw_payment in enumerate(payments, start=1):
                payment = _mapping(raw_payment, ctx, "payments")
                allocations = allocations_by_payment[index - 1]
                numbers = {a.transaction_number for a in allocations}
                lines = (
                    outcome_lines
                    if len(payments) == 1
                    else [x for x in outcome_lines if x.transaction_number in numbers]
                )
                messages.append(
                    SourceMessage(
                        message_id=base_id if index == 1 else f"{base_id}#{index}",
                        payer_name=_text(payload.get("payerName"), ctx, "payerName"),
                        payer_bank_account=_identifier(
                            payload.get("payerBankAccount"), ctx, "payerBankAccount"
                        ),
                        reference_number=_identifier(
                            payment.get("reference_number"), ctx, "reference_number"
                        ),
                        payment_amount=_amount(
                            payment.get("payment_amount"), ctx, "payment_amount"
                        ),
                        payment_date=_date(payment.get("payment_date"), ctx, "payment_date"),
                        payment_currency=_text(
                            payment.get("payment_currency"), ctx, "payment_currency"
                        ),
                        allocations=allocations,
                        po_refs=_identifier_list(payment.get("po_refs"), ctx, "po_refs"),
                        sales_order_refs=_identifier_list(
                            payment.get("sales_order_refs"), ctx, "sales_order_refs"
                        ),
                        ers_refs=_identifier_list(payment.get("ers_refs"), ctx, "ers_refs"),
                        outcome=SourceOutcome(
                            payment_status=status, lines=lines, receipt_number=receipt_number
                        ),
                    )
                )
            coerced += ctx.coerced
    return messages, coerced


# --- CSV files ------------------------------------------------------------


def _rows(root: Path, name: str, required: Sequence[str]) -> Iterator[tuple[_Ctx, dict[str, str]]]:
    path = root / name
    if not path.is_file():
        return
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        for column in required:
            if column not in header:
                raise SourceFormatError(name, 1, column, "column is missing")
        for row in reader:
            ctx = _Ctx(name, reader.line_num)
            yield ctx, {key: (value or "") for key, value in row.items() if key is not None}


def _split_list(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(";") if part.strip())


def _load_customers(root: Path) -> list[SourceCustomer]:
    result: list[SourceCustomer] = []
    for ctx, row in _rows(root, CUSTOMERS_FILE, ("account_number", "name", "currency_codes")):
        result.append(
            SourceCustomer(
                account_number=_required_identifier(row["account_number"], ctx, "account_number"),
                name=_required_text(row["name"], ctx, "name"),
                currency_codes=_split_list(row["currency_codes"]),
            )
        )
    return result


_TRANSACTION_COLUMNS: Final = (
    "number",
    "kind",
    "original_amount",
    "balance",
    "currency",
    "status",
    "bill_to_customer_number",
    "bill_to_site",
    "business_unit",
    "payment_terms",
)


def _load_transactions(root: Path) -> list[SourceTransaction]:
    result: list[SourceTransaction] = []
    seen: set[str] = set()
    for ctx, row in _rows(root, TRANSACTIONS_FILE, _TRANSACTION_COLUMNS):
        number = _required_identifier(row["number"], ctx, "number")
        if number in seen:
            ctx.fail("number", "duplicate transaction number")
        seen.add(number)
        kind = _required_text(row["kind"], ctx, "kind").upper().replace(" ", "_")
        if kind not in _TRANSACTION_KINDS:
            ctx.fail("kind", "unknown transaction kind")
        result.append(
            SourceTransaction(
                number=number,
                kind=kind,
                original_amount=_required_amount(row["original_amount"], ctx, "original_amount"),
                balance=_required_amount(row["balance"], ctx, "balance"),
                currency=_required_text(row["currency"], ctx, "currency"),
                status=_required_text(row["status"], ctx, "status"),
                bill_to_customer_number=_identifier(
                    row["bill_to_customer_number"], ctx, "bill_to_customer_number"
                ),
                bill_to_site=_text(row["bill_to_site"], ctx, "bill_to_site"),
                business_unit=_text(row["business_unit"], ctx, "business_unit"),
                payment_terms=_text(row["payment_terms"], ctx, "payment_terms"),
            )
        )
    return result


_RECEIPT_COLUMNS: Final = (
    "receipt_number",
    "amount",
    "unapplied_amount",
    "currency",
    "customer_account_number",
    "receipt_date",
    "creation_date",
    "status",
    "state",
    "remittance_references",
    "comments",
    "payer_bank_account",
)


def _load_receipts(root: Path) -> list[SourceReceipt]:
    result: list[SourceReceipt] = []
    seen: set[str] = set()
    for ctx, row in _rows(root, RECEIPTS_FILE, _RECEIPT_COLUMNS):
        number = _required_identifier(row["receipt_number"], ctx, "receipt_number")
        if number in seen:
            ctx.fail("receipt_number", "duplicate receipt number")
        seen.add(number)
        receipt_date = _date(row["receipt_date"], ctx, "receipt_date")
        if receipt_date is None:
            ctx.fail("receipt_date", "value is required")
        result.append(
            SourceReceipt(
                receipt_number=number,
                amount=_required_amount(row["amount"], ctx, "amount"),
                unapplied_amount=_required_amount(row["unapplied_amount"], ctx, "unapplied_amount"),
                currency=_required_text(row["currency"], ctx, "currency"),
                customer_account_number=_identifier(
                    row["customer_account_number"], ctx, "customer_account_number"
                ),
                receipt_date=receipt_date,
                creation_date=_datetime(row["creation_date"], ctx, "creation_date"),
                status=_required_text(row["status"], ctx, "status"),
                state=_required_text(row["state"], ctx, "state"),
                remittance_references=_split_list(row["remittance_references"]),
                comments=_text(row["comments"], ctx, "comments"),
                payer_bank_account=_identifier(
                    row["payer_bank_account"], ctx, "payer_bank_account"
                ),
            )
        )
    return result


def _load_applications(root: Path) -> list[SourceApplication]:
    result: list[SourceApplication] = []
    columns = ("receipt_number", "transaction_number", "amount_applied", "apply_date")
    for ctx, row in _rows(root, APPLICATIONS_FILE, columns):
        apply_date = _date(row["apply_date"], ctx, "apply_date")
        if apply_date is None:
            ctx.fail("apply_date", "value is required")
        result.append(
            SourceApplication(
                receipt_number=_required_identifier(row["receipt_number"], ctx, "receipt_number"),
                transaction_number=_required_identifier(
                    row["transaction_number"], ctx, "transaction_number"
                ),
                amount_applied=_required_amount(row["amount_applied"], ctx, "amount_applied"),
                apply_date=apply_date,
            )
        )
    return result


def _load_relationships(root: Path) -> list[SourceRelationship]:
    result: list[SourceRelationship] = []
    for ctx, row in _rows(root, RELATIONSHIPS_FILE, ("account_number", "related_account_number")):
        result.append(
            SourceRelationship(
                account_number=_required_identifier(row["account_number"], ctx, "account_number"),
                related_account_number=_required_identifier(
                    row["related_account_number"], ctx, "related_account_number"
                ),
            )
        )
    return result


_FAILURE_COLUMNS: Final = (
    "message_id",
    "payment_label",
    "payment_fusion_amount",
    "transaction_number",
    "line_label",
    "line_fusion_amount",
)


def _load_failures(root: Path, message_ids: set[str]) -> list[SourceFailure]:
    headers: dict[str, tuple[PriorLabel, Decimal | None]] = {}
    lines: dict[str, list[SourceLineLabel]] = {}
    for ctx, row in _rows(root, FAILURES_FILE, _FAILURE_COLUMNS):
        message_id = _required_identifier(row["message_id"], ctx, "message_id")
        if message_id not in message_ids:
            ctx.fail("message_id", "label refers to a message that is not in messages.jsonl")
        label = _label(row["payment_label"], ctx, "payment_label")
        amount = _amount(row["payment_fusion_amount"], ctx, "payment_fusion_amount")
        if headers.setdefault(message_id, (label, amount)) != (label, amount):
            ctx.fail("payment_label", "payment columns differ between rows of one message")
        lines.setdefault(message_id, [])
        number = _identifier(row["transaction_number"], ctx, "transaction_number")
        if number is not None:
            line_label = (
                _label(row["line_label"], ctx, "line_label") if row["line_label"].strip() else label
            )
            lines[message_id].append(
                SourceLineLabel(
                    transaction_number=number,
                    label=line_label,
                    fusion_amount=_amount(row["line_fusion_amount"], ctx, "line_fusion_amount"),
                )
            )
    return [
        SourceFailure(message_id=mid, label=label, fusion_amount=amount, lines=lines[mid])
        for mid, (label, amount) in headers.items()
    ]


def load_source(directory: Path) -> SourceBundle:
    """Read and validate the whole source folder."""
    messages_path = directory / MESSAGES_FILE
    if not messages_path.is_file():
        raise SourceFormatError(MESSAGES_FILE, 0, "file", "file is missing")
    messages, coerced = _parse_messages(messages_path)
    return SourceBundle(
        messages=messages,
        customers=_load_customers(directory),
        transactions=_load_transactions(directory),
        receipts=_load_receipts(directory),
        applications=_load_applications(directory),
        relationships=_load_relationships(directory),
        failures=_load_failures(directory, {m.message_id for m in messages}),
        numeric_ids_coerced=coerced,
    )
