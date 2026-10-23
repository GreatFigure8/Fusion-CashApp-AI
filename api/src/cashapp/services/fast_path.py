"""Decision rules of the already-applied fast path.

No ORM and no request objects; Fusion is reached only through the ``FusionClient`` protocol, and
only for reads. A remittance qualifies only when every invoice-like line points at a transaction
that is already closed and the receipt(s) that closed each one can be determined. Any doubt means
the normal path.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from cashapp.domain.extraction import ExtractedLine, LineKind
from cashapp.domain.money import money_eq
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import FusionTransaction, TransactionKind
from cashapp.pipeline.errors import StageError

# UNVERIFIED against a live pod; fail-closed: any other status is not counted as an application.
ACTIVE_APPLICATION_STATUSES: Final[frozenset[str]] = frozenset({"APP"})

_ZERO: Final = Decimal("0")


@dataclass(frozen=True, slots=True)
class LineTransaction:
    line_no: int
    line: ExtractedLine
    transaction: FusionTransaction


@dataclass(frozen=True, slots=True)
class LineMatch:
    matched: tuple[LineTransaction, ...]
    unmatched_line_nos: tuple[int, ...]
    ambiguous_line_nos: tuple[int, ...]

    def transactions(self) -> list[FusionTransaction]:
        """The matched transactions, deduplicated by ``customer_trx_id`` and sorted by it."""
        unique = {m.transaction.customer_trx_id: m.transaction for m in self.matched}
        return [unique[key] for key in sorted(unique)]


@dataclass(frozen=True, slots=True)
class ClosingReceipts:
    receipt_ids: set[int]
    complete: bool  # True only when the fast path may be taken
    all_closed: bool = False
    by_transaction: Mapping[int, tuple[int, ...]] = field(
        default_factory=lambda: dict[int, tuple[int, ...]]()
    )
    open_numbers: tuple[str, ...] = ()
    undetermined_numbers: tuple[str, ...] = ()


def _kind_of(kind: LineKind) -> TransactionKind | None:
    if kind is LineKind.INVOICE:
        return TransactionKind.INVOICE
    if kind is LineKind.CREDIT_MEMO:
        return TransactionKind.CREDIT_MEMO
    return None


def match_line_transactions(
    lines: Sequence[ExtractedLine], transactions: Sequence[FusionTransaction]
) -> LineMatch:
    """Pair each lookup line with the one Fusion transaction it names."""
    by_number: dict[str, list[FusionTransaction]] = {}
    for transaction in transactions:
        by_number.setdefault(transaction.number.strip(), []).append(transaction)

    matched: list[LineTransaction] = []
    unmatched: list[int] = []
    ambiguous: list[int] = []
    for line in sorted(lines, key=lambda x: x.line_no):
        candidates = by_number.get(line.transaction_number.strip(), [])
        wanted = _kind_of(line.kind)
        if wanted is not None:
            same_kind = [t for t in candidates if t.kind is wanted]
            candidates = same_kind or candidates
        if not candidates:
            unmatched.append(line.line_no)
        elif len(candidates) > 1:
            ambiguous.append(line.line_no)
        else:
            matched.append(LineTransaction(line.line_no, line, candidates[0]))
    return LineMatch(tuple(matched), tuple(unmatched), tuple(ambiguous))


def is_closed(transaction: FusionTransaction) -> bool:
    """Zero remaining balance; ``abs`` makes this sign-aware for credit memos."""
    return money_eq(abs(transaction.balance), _ZERO)


async def find_closing_receipts(
    transactions: Sequence[FusionTransaction],
    fusion: FusionClient,
    *,
    unmatched_line_nos: Sequence[int] = (),
    ambiguous_line_nos: Sequence[int] = (),
) -> ClosingReceipts:
    """The receipt(s) that closed every transaction, or ``complete=False`` when in any doubt."""
    if not transactions or unmatched_line_nos or ambiguous_line_nos:
        return ClosingReceipts(receipt_ids=set(), complete=False)

    ordered = sorted(transactions, key=lambda t: t.customer_trx_id)
    open_numbers = tuple(t.number for t in ordered if not is_closed(t))
    if open_numbers:
        return ClosingReceipts(receipt_ids=set(), complete=False, open_numbers=open_numbers)

    by_transaction: dict[int, tuple[int, ...]] = {}
    undetermined: list[str] = []
    for transaction in ordered:
        try:
            applications = await fusion.list_transaction_applications(transaction.customer_trx_id)
        except FusionError as exc:
            raise StageError(
                exc.code,
                {
                    "op": "list_transaction_applications",
                    "customer_trx_id": transaction.customer_trx_id,
                    "fusion_code": exc.fusion_code,
                },
            ) from exc
        receipts = tuple(
            sorted(
                {
                    a.receipt_id
                    for a in applications
                    if a.status.upper() in ACTIVE_APPLICATION_STATUSES
                }
            )
        )
        by_transaction[transaction.customer_trx_id] = receipts
        if not receipts:
            undetermined.append(transaction.number)

    receipt_ids = {rid for ids in by_transaction.values() for rid in ids}
    return ClosingReceipts(
        receipt_ids=receipt_ids,
        complete=not undetermined and bool(receipt_ids),
        all_closed=True,
        by_transaction=by_transaction,
        undetermined_numbers=tuple(undetermined),
    )


def closing_reason(match: LineMatch, closing: ClosingReceipts) -> str:
    """The audit sentence, for example "all 3 invoices already closed by receipts 1, 2"."""
    transactions = match.transactions()
    invoices = sum(1 for t in transactions if t.kind is TransactionKind.INVOICE)
    memos = len(transactions) - invoices
    parts: list[str] = []
    if invoices or not memos:
        parts.append(f"{invoices} invoice{'s' if invoices != 1 else ''}")
    if memos:
        parts.append(f"{memos} credit memo{'s' if memos != 1 else ''}")
    if len(parts) == 1:
        subject = f"all {parts[0]}"
    else:
        subject = f"all {len(transactions)} transactions ({' and '.join(parts)})"
    ids = sorted(closing.receipt_ids)
    noun = "receipt" if len(ids) == 1 else "receipts"
    return (
        f"{subject} already closed by {noun} {', '.join(str(i) for i in ids)}; remittance attached"
    )
