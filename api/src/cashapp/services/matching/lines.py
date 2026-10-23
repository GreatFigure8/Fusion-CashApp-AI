"""Line matching: decide, for each remittance line, what (if anything) to apply to Fusion.

Pure: no I/O, no ORM, no Fusion client. Inputs are the extracted lines, the fresh Fusion
transactions and the receipt's remaining amount; the output is a plan of signed application steps
plus a verdict for every line that gets no step.
"""

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ExtractedLine, LineKind
from cashapp.domain.ledger import LedgerStatus
from cashapp.domain.money import money_eq, to_money
from cashapp.domain.status import LineStatus
from cashapp.integrations.fusion.models import (
    FusionApplication,
    FusionTransaction,
    TransactionKind,
)

# Compared upper-cased. VERIFY the values on the non-production pod (CONTRACTS.md).
OPEN_TRANSACTION_STATUSES: Final = frozenset({"OPEN", "COMPLETE"})
INACTIVE_APPLICATION_STATUSES: Final = frozenset({"REVERSED", "UNAPP"})
APPLICABLE_LINE_KINDS: Final = frozenset({LineKind.INVOICE, LineKind.CREDIT_MEMO, LineKind.UNKNOWN})
RECONCILABLE_ERROR_CODES: Final = frozenset(
    {ErrorCode.FUSION_ALREADY_APPLIED, ErrorCode.FUSION_TRANSIENT}
)

_HALF_CENT: Final = Decimal("0.005")
_ZERO: Final = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class LineStep:
    line_no: int
    transaction: FusionTransaction
    amount: Decimal  # signed: negative for credit memos; never zero
    kind: TransactionKind
    target_status: LineStatus  # APPLIED | APPLIED_SHORT_PAY | APPLIED_LESS_THAN_INSTRUCTION
    stated_amount: Decimal | None
    balance_before: Decimal
    merged_line_nos: tuple[int, ...] = ()
    discount: Decimal | None = None  # s39 fills it; s15 always None


@dataclass(frozen=True, slots=True)
class LineResultDraft:
    line_no: int
    line_status: LineStatus
    reason: str
    error_code: ErrorCode | None = None
    transaction_number: str = ""
    customer_trx_id: int | None = None
    stated_amount: Decimal | None = None
    balance_before: Decimal | None = None
    merged_into: int | None = None  # dedupe: the final status is copied from this primary line


@dataclass(frozen=True, slots=True)
class LinePlan:
    steps: list[LineStep]  # credit memos first, then invoices; stable by (kind, line_no)
    results: list[LineResultDraft]  # non-applicable verdicts and merged duplicates
    receipt_remaining_after: Decimal
    duplicates: dict[int, tuple[int, ...]]
    ignored_line_nos: tuple[int, ...]  # BANK_FEE / TARIFF / DISCOUNT


@dataclass(frozen=True, slots=True)
class Reconciliation:
    ledger_id: int
    application_id: int
    amount_applied: Decimal


class LedgerRowView(Protocol):
    """What ``reconcile_ledger`` reads from a ledger row; the ORM row satisfies it."""

    @property
    def id(self) -> int: ...

    @property
    def receipt_id(self) -> int: ...

    @property
    def customer_trx_id(self) -> int: ...

    @property
    def status(self) -> LedgerStatus: ...

    @property
    def error_code(self) -> ErrorCode | None: ...

    @property
    def fusion_application_id(self) -> int | None: ...


def number_key(number: str) -> str:
    """The key a transaction number is looked up by."""
    return number.strip().upper()


def is_active_application(a: FusionApplication) -> bool:
    return a.status.strip().upper() not in INACTIVE_APPLICATION_STATUSES


def apply_outcome_status(target: LineStatus | None, *, applied: bool) -> LineStatus:
    """The line status once Fusion answered: the planned target on success, else apply-failed."""
    if not applied:
        return LineStatus.ALLOCATION_APPLY_FAILED
    return target if target is not None else LineStatus.ALLOCATION_APPLIED


def index_transactions(
    found: Sequence[FusionTransaction],
    lines: Sequence[ExtractedLine],
    owners: Collection[str],
) -> tuple[dict[str, FusionTransaction], frozenset[str]]:
    """One transaction per number, plus the numbers that stayed ambiguous.

    A number held by several transactions is narrowed by the line's kind, then by whether the
    bill-to customer is the anchor or a related account.
    """
    by_number: dict[str, list[FusionTransaction]] = defaultdict(list)
    for transaction in found:
        by_number[number_key(transaction.number)].append(transaction)
    wanted_kinds: dict[str, set[TransactionKind]] = defaultdict(set)
    for line in lines:
        if line.kind is LineKind.INVOICE:
            wanted_kinds[number_key(line.transaction_number)].add(TransactionKind.INVOICE)
        elif line.kind is LineKind.CREDIT_MEMO:
            wanted_kinds[number_key(line.transaction_number)].add(TransactionKind.CREDIT_MEMO)

    chosen: dict[str, FusionTransaction] = {}
    ambiguous: set[str] = set()
    owner_set = set(owners)
    for key, candidates in by_number.items():
        pool = candidates
        if len(pool) > 1 and wanted_kinds.get(key):
            by_kind = [t for t in pool if t.kind in wanted_kinds[key]]
            pool = by_kind or pool
        if len(pool) > 1 and owner_set:
            owned = [t for t in pool if t.bill_to_customer_number in owner_set]
            pool = owned or pool
        if len(pool) == 1:
            chosen[key] = pool[0]
        else:
            ambiguous.add(key)
    return chosen, frozenset(ambiguous)


def reconcile_ledger(
    rows: Sequence[LedgerRowView], existing: Sequence[FusionApplication]
) -> list[Reconciliation]:
    """Ledger rows whose application already exists in Fusion (they were applied after all).

    A row qualifies when it is PLANNED, or FAILED with a code that may hide a landed apply. An
    application already owned by an APPLIED row is never claimed twice.
    """
    claimed = {
        r.fusion_application_id
        for r in rows
        if r.status is LedgerStatus.APPLIED and r.fusion_application_id is not None
    }
    found: list[Reconciliation] = []
    for row in rows:
        reconcilable = row.status is LedgerStatus.PLANNED or (
            row.status is LedgerStatus.FAILED and row.error_code in RECONCILABLE_ERROR_CODES
        )
        if not reconcilable:
            continue
        for application in existing:
            if (
                is_active_application(application)
                and application.receipt_id == row.receipt_id
                and application.customer_trx_id == row.customer_trx_id
                and application.application_id not in claimed
            ):
                claimed.add(application.application_id)
                found.append(
                    Reconciliation(row.id, application.application_id, application.amount_applied)
                )
                break
    return found


def _is_credit_memo(line: ExtractedLine, transaction: FusionTransaction | None) -> bool:
    if transaction is not None:
        return transaction.kind is TransactionKind.CREDIT_MEMO
    return line.kind is LineKind.CREDIT_MEMO


@dataclass(frozen=True, slots=True)
class _Group:
    primary: ExtractedLine
    others: tuple[ExtractedLine, ...]
    stated: Decimal | None


def _group_lines(
    lines: Sequence[ExtractedLine], transactions: Mapping[str, FusionTransaction]
) -> list[_Group]:
    buckets: dict[object, list[ExtractedLine]] = defaultdict(list)
    for line in sorted(lines, key=lambda ln: ln.line_no):
        key = number_key(line.transaction_number)
        found = transactions.get(key)
        buckets[found.customer_trx_id if found is not None else key].append(line)
    groups: list[_Group] = []
    for members in buckets.values():
        primary, others = members[0], tuple(members[1:])
        amounts = [m.amount_paid for m in members]
        if all(a is not None for a in amounts):
            stated: Decimal | None = to_money(sum((a for a in amounts if a is not None), _ZERO))
        else:
            stated = primary.amount_paid
        groups.append(_Group(primary, others, stated))
    groups.sort(key=lambda g: g.primary.line_no)
    return groups


def _draft(
    group: _Group,
    status: LineStatus,
    reason: str,
    *,
    code: ErrorCode | None = None,
    transaction: FusionTransaction | None = None,
) -> LineResultDraft:
    return LineResultDraft(
        line_no=group.primary.line_no,
        line_status=status,
        reason=reason,
        error_code=code,
        transaction_number=group.primary.transaction_number.strip(),
        customer_trx_id=transaction.customer_trx_id if transaction is not None else None,
        stated_amount=group.stated,
        balance_before=transaction.balance if transaction is not None else None,
    )


def _verdict(
    group: _Group,
    transaction: FusionTransaction | None,
    *,
    payment_currency: str,
    existing: Sequence[FusionApplication],
    owners: Collection[str] | None,
    ambiguous: Collection[str],
) -> LineResultDraft | None:
    """The first verdict that stops this line from being applied, or None when it is valid."""
    stated = group.stated
    if stated is not None and money_eq(stated, _ZERO):
        return _draft(
            group,
            LineStatus.ALLOCATION_ZERO_AMOUNT,
            "line amount is zero",
            code=ErrorCode.ZERO_AMOUNT_LINE,
            transaction=transaction,
        )
    if transaction is None:
        ambiguous_number = number_key(group.primary.transaction_number) in ambiguous
        return _draft(
            group,
            LineStatus.ALLOCATION_INVOICE_NOT_FOUND,
            "ambiguous transaction number"
            if ambiguous_number
            else "transaction not found in Fusion",
            code=ErrorCode.INVOICE_NOT_FOUND,
        )
    if transaction.bill_to_customer_number is None:
        return _draft(
            group,
            LineStatus.ALLOCATION_CUSTOMER_NOT_FOUND,
            "transaction has no bill-to customer",
            code=ErrorCode.CUSTOMER_NOT_FOUND,
            transaction=transaction,
        )
    if owners is not None and transaction.bill_to_customer_number not in set(owners):
        return _draft(
            group,
            LineStatus.ALLOCATION_CUSTOMER_NOT_FOUND,
            "bill-to outside anchor/related",
            code=ErrorCode.CUSTOMER_NOT_FOUND,
            transaction=transaction,
        )
    if transaction.currency.strip().upper() != payment_currency.strip().upper():
        return _draft(
            group,
            LineStatus.ALLOCATION_APPLY_FAILED,
            f"transaction currency {transaction.currency} differs from {payment_currency}",
            code=ErrorCode.INVOICE_CURRENCY_MISMATCH,
            transaction=transaction,
        )
    if transaction.status.strip().upper() not in OPEN_TRANSACTION_STATUSES:
        return _draft(
            group,
            LineStatus.ALLOCATION_APPLY_FAILED,
            f"transaction status {transaction.status} cannot take an application",
            code=ErrorCode.INVOICE_STATUS_INVALID,
            transaction=transaction,
        )
    if transaction.kind is TransactionKind.CREDIT_MEMO:
        no_balance = transaction.balance >= _HALF_CENT * -1
    else:
        no_balance = transaction.balance <= _HALF_CENT
    if no_balance:
        return _draft(
            group,
            LineStatus.ALLOCATION_NO_REMAINING_BALANCE,
            "no remaining balance",
            code=ErrorCode.INVOICE_CLOSED,
            transaction=transaction,
        )
    if any(
        is_active_application(a) and a.customer_trx_id == transaction.customer_trx_id
        for a in existing
    ):
        return _draft(
            group,
            LineStatus.ALLOCATION_PREVIOUSLY_APPLIED,
            "already applied from this receipt",
            transaction=transaction,
        )
    return None


def plan_lines(
    lines: Sequence[ExtractedLine],
    transactions: Mapping[str, FusionTransaction],
    receipt_remaining: Decimal,
    existing: Sequence[FusionApplication],
    payment_currency: str,
    *,
    header_amount: Decimal | None = None,
    tolerance: Decimal = Decimal("0.00"),
    owners: Collection[str] | None = None,
    ambiguous: Collection[str] = (),
) -> LinePlan:
    """Plan the applications for ``lines``. ``transactions`` is keyed by ``number_key``."""
    ignored = tuple(sorted(ln.line_no for ln in lines if ln.kind not in APPLICABLE_LINE_KINDS))
    applicable = [ln for ln in lines if ln.kind in APPLICABLE_LINE_KINDS]
    groups = _group_lines(applicable, transactions)

    results: list[LineResultDraft] = []
    valid: list[tuple[_Group, FusionTransaction]] = []
    for group in groups:
        transaction = transactions.get(number_key(group.primary.transaction_number))
        verdict = _verdict(
            group,
            transaction,
            payment_currency=payment_currency,
            existing=existing,
            owners=owners,
            ambiguous=ambiguous,
        )
        if verdict is not None:
            results.append(verdict)
        elif transaction is not None:
            valid.append((group, transaction))

    reconciles = _header_reconciles(groups, transactions, valid, header_amount, tolerance)

    ordered = sorted(
        valid,
        key=lambda pair: (
            0 if pair[1].kind is TransactionKind.CREDIT_MEMO else 1,
            pair[0].primary.line_no,
        ),
    )
    steps: list[LineStep] = []
    remaining = receipt_remaining
    for group, transaction in ordered:
        stated = group.stated
        if stated is None and not reconciles:
            results.append(
                _draft(
                    group,
                    LineStatus.ALLOCATION_APPLY_FAILED,
                    "no line amount and header does not reconcile",
                    code=ErrorCode.AMOUNT_VARIANCE,
                    transaction=transaction,
                )
            )
            continue
        balance = transaction.balance
        merged = tuple(o.line_no for o in group.others)
        if transaction.kind is TransactionKind.CREDIT_MEMO:
            wanted = abs(stated) if stated is not None else abs(balance)
            applied = to_money(min(wanted, abs(balance)))
            amount = -applied
            remaining += applied
            capped = (
                stated is not None and applied < abs(stated) and not money_eq(applied, abs(stated))
            )
            short = applied < abs(balance) and not money_eq(applied, abs(balance))
        else:
            if stated is not None and stated < _ZERO:
                results.append(
                    _draft(
                        group,
                        LineStatus.ALLOCATION_APPLY_FAILED,
                        "negative amount on an invoice line",
                        code=ErrorCode.AMOUNT_VARIANCE,
                        transaction=transaction,
                    )
                )
                continue
            wanted = stated if stated is not None else balance
            applied = to_money(min(wanted, balance, remaining))
            if applied <= _HALF_CENT:
                results.append(
                    _draft(
                        group,
                        LineStatus.ALLOCATION_APPLY_FAILED,
                        "receipt exhausted",
                        code=ErrorCode.AMOUNT_VARIANCE,
                        transaction=transaction,
                    )
                )
                continue
            amount = applied
            remaining -= applied
            capped = applied < wanted and not money_eq(applied, wanted)
            short = applied < balance and not money_eq(applied, balance)
        if capped:
            target = LineStatus.ALLOCATION_APPLIED_LESS_THAN_INSTRUCTION
        elif short:
            target = LineStatus.ALLOCATION_APPLIED_SHORT_PAY
        else:
            target = LineStatus.ALLOCATION_APPLIED
        steps.append(
            LineStep(
                line_no=group.primary.line_no,
                transaction=transaction,
                amount=amount,
                kind=transaction.kind,
                target_status=target,
                stated_amount=stated,
                balance_before=balance,
                merged_line_nos=merged,
            )
        )

    results.extend(_merged_drafts(groups, steps, results))
    results.sort(key=lambda r: r.line_no)
    duplicates = {g.primary.line_no: tuple(o.line_no for o in g.others) for g in groups if g.others}
    return LinePlan(
        steps=steps,
        results=results,
        receipt_remaining_after=to_money(remaining),
        duplicates=duplicates,
        ignored_line_nos=ignored,
    )


def _merged_drafts(
    groups: Sequence[_Group], steps: Sequence[LineStep], verdicts: Sequence[LineResultDraft]
) -> list[LineResultDraft]:
    """A draft for every duplicate line, carrying its primary's planned (or final) status."""
    step_of = {s.line_no: s for s in steps}
    verdict_of = {v.line_no: v for v in verdicts}
    drafts: list[LineResultDraft] = []
    for group in groups:
        primary = group.primary.line_no
        step = step_of.get(primary)
        verdict = verdict_of.get(primary)
        for other in group.others:
            if step is not None:
                status, reason, code = step.target_status, f"merged into line {primary}", None
                trx_id: int | None = step.transaction.customer_trx_id
                balance: Decimal | None = step.balance_before
            elif verdict is not None:
                status, reason, code = (
                    verdict.line_status,
                    f"merged into line {primary}: {verdict.reason}",
                    verdict.error_code,
                )
                trx_id, balance = verdict.customer_trx_id, verdict.balance_before
            else:  # pragma: no cover - every primary has a step or a verdict
                continue
            drafts.append(
                LineResultDraft(
                    line_no=other.line_no,
                    line_status=status,
                    reason=reason,
                    error_code=code,
                    transaction_number=other.transaction_number.strip(),
                    customer_trx_id=trx_id,
                    stated_amount=other.amount_paid,
                    balance_before=balance,
                    merged_into=primary,
                )
            )
    return drafts


def _header_reconciles(
    groups: Sequence[_Group],
    transactions: Mapping[str, FusionTransaction],
    valid: Sequence[tuple[_Group, FusionTransaction]],
    header_amount: Decimal | None,
    tolerance: Decimal,
) -> bool:
    """True when the stated amounts plus the full balances of amountless lines equal the header."""
    if header_amount is None:
        return False
    valid_ids = {g.primary.line_no: t for g, t in valid}
    expected = _ZERO
    for group in groups:
        transaction = transactions.get(number_key(group.primary.transaction_number))
        credit = _is_credit_memo(group.primary, transaction)
        if group.stated is not None:
            expected += -abs(group.stated) if credit else group.stated
        elif group.primary.line_no in valid_ids:
            expected += valid_ids[group.primary.line_no].balance
    return abs(header_amount - expected) <= max(tolerance, _HALF_CENT)
