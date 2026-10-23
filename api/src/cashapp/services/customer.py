"""Customer resolution: which Fusion account is this remittance for, and who else may have paid.

Pure business logic. It takes the alias lookup and the Fusion client as plain arguments, so the
runner, the eval harness and tests call it the same way, and it never touches the database.

The anchor customer is, in order: a person's choice, the one customer a payer alias points at,
or the bill-to customer of the first remittance line whose transaction Fusion has. Pay-on-behalf
relationships only widen the receipt search. A payer that maps to several accounts is never
auto-assigned.
"""

import logging
from collections import defaultdict
from collections.abc import Sequence

from cashapp.domain.customer import (
    CurrencySource,
    CustomerResolution,
    LineCustomerFinding,
    LineFindingStatus,
    ResolutionMethod,
)
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ExtractedLine, LineKind, RemittanceExtraction
from cashapp.domain.status import InfoFlag, LineStatus
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import FusionCustomer, FusionTransaction, TransactionKind
from cashapp.observability.logging import get_logger
from cashapp.pipeline.errors import StageError
from cashapp.services.aliases import AliasLookup

__all__ = [
    "CustomerResolution",
    "LineCustomerFinding",
    "LineFindingStatus",
    "ResolutionMethod",
    "lookup_lines",
    "resolve_customer",
]

_module_log = get_logger(__name__)

type Log = logging.Logger | logging.LoggerAdapter[logging.Logger]

_LOOKUP_KINDS = frozenset({LineKind.INVOICE, LineKind.CREDIT_MEMO, LineKind.UNKNOWN})


def lookup_lines(extraction: RemittanceExtraction) -> list[ExtractedLine]:
    """The lines worth looking up in Fusion, by ``line_no``. Fees, tariffs and discounts are not."""
    lines = [
        line
        for line in extraction.lines
        if line.kind in _LOOKUP_KINDS and line.transaction_number.strip()
    ]
    return sorted(lines, key=lambda line: line.line_no)


def _fusion_error(exc: FusionError, op: str) -> StageError:
    return StageError(exc.code, {"op": op, "fusion_code": exc.fusion_code})


def _candidates(
    line: ExtractedLine, by_number: dict[str, list[FusionTransaction]]
) -> list[FusionTransaction]:
    """Transactions with the line's number; the line's kind decides between invoice and memo."""
    found = by_number.get(line.transaction_number.strip(), [])
    preferred_kind = {
        LineKind.INVOICE: TransactionKind.INVOICE,
        LineKind.CREDIT_MEMO: TransactionKind.CREDIT_MEMO,
    }.get(line.kind)
    if preferred_kind is None:
        return found
    preferred = [t for t in found if t.kind is preferred_kind]
    return preferred or found


def _bill_tos(candidates: Sequence[FusionTransaction]) -> tuple[str, ...]:
    return tuple(
        sorted({t.bill_to_customer_number for t in candidates if t.bill_to_customer_number})
    )


async def _account(fusion: FusionClient, number: str, op: str) -> FusionCustomer:
    try:
        return await fusion.get_customer_account(number)
    except FusionError as exc:
        raise _fusion_error(exc, op) from exc


async def _related(fusion: FusionClient, anchor: str, log: Log) -> tuple[str, ...]:
    """One hop, both directions. A failure or an empty report is never an error."""
    try:
        relationships = await fusion.customer_relationships([anchor])
    except FusionError as exc:
        log.warning("relationship lookup failed", extra={"error_code": exc.code.value})
        return ()
    related = {r.related_account_number for r in relationships if r.related_account_number}
    related.discard(anchor)
    return tuple(sorted(related))


def _findings(
    lines: Sequence[ExtractedLine],
    by_number: dict[str, list[FusionTransaction]],
    owners: frozenset[str],
) -> tuple[LineCustomerFinding, ...]:
    findings: list[LineCustomerFinding] = []
    for line in lines:
        candidates = _candidates(line, by_number)
        bill_tos = _bill_tos(candidates)
        if not candidates:
            status, candidate_status = (
                LineFindingStatus.NOT_FOUND,
                LineStatus.ALLOCATION_INVOICE_NOT_FOUND,
            )
        elif not bill_tos:
            status, candidate_status = (
                LineFindingStatus.NO_BILL_TO,
                LineStatus.ALLOCATION_CUSTOMER_NOT_FOUND,
            )
        elif owners.intersection(bill_tos):
            status, candidate_status = LineFindingStatus.FOUND, None
        else:
            status, candidate_status = (
                LineFindingStatus.CUSTOMER_MISMATCH,
                LineStatus.ALLOCATION_CUSTOMER_NOT_FOUND,
            )
        findings.append(
            LineCustomerFinding(
                line_no=line.line_no,
                transaction_number=line.transaction_number.strip(),
                status=status,
                candidate_status=candidate_status,
                customer_trx_ids=tuple(t.customer_trx_id for t in candidates),
                bill_to_customer_numbers=bill_tos,
            )
        )
    return tuple(findings)


def _invoice_anchor(
    lines: Sequence[ExtractedLine], by_number: dict[str, list[FusionTransaction]]
) -> tuple[str, int]:
    """The bill-to of the first line (by ``line_no``) whose candidates agree on one account."""
    any_found = False
    for line in lines:
        candidates = _candidates(line, by_number)
        if not candidates:
            continue
        any_found = True
        bill_tos = _bill_tos(candidates)
        if len(bill_tos) == 1:
            return bill_tos[0], line.line_no
    if not any_found:
        raise StageError(ErrorCode.INVOICE_NOT_FOUND, {"lines": len(lines)})
    found_lines = sum(1 for line in lines if _candidates(line, by_number))
    raise StageError(ErrorCode.CUSTOMER_NOT_FOUND, {"found_lines": found_lines})


async def _currency(
    extraction: RemittanceExtraction,
    anchor: str,
    account: FusionCustomer | None,
    transactions: Sequence[FusionTransaction],
    fusion: FusionClient,
) -> tuple[str | None, CurrencySource | None, bool]:
    """(currency, source, resolved_from_customer_flag)."""
    explicit = extraction.currency.value
    if explicit and not extraction.currency_ambiguous:
        return explicit, "extraction", False
    if account is None:
        account = await _account(fusion, anchor, "get_customer_account")
    codes = tuple(dict.fromkeys(code.upper() for code in account.currency_codes if code))
    if len(codes) == 1:
        return codes[0], "customer", True
    if len(codes) > 1:
        raise StageError(ErrorCode.DUAL_CURRENCY, {"currency_count": len(codes)})
    owned = {t.currency.upper() for t in transactions if t.bill_to_customer_number == anchor}
    if len(owned) == 1:
        return next(iter(owned)), "anchor_transactions", True
    raise StageError(ErrorCode.INVALID_CURRENCY, {"reason": "unresolved"})


async def resolve_customer(
    extraction: RemittanceExtraction,
    *,
    aliases: AliasLookup,
    fusion: FusionClient,
    human_customer_number: str | None = None,
    log: Log | None = None,
) -> CustomerResolution:
    """Resolve the anchor customer, related accounts, per-line findings and currency.

    Raises ``StageError`` (never a raw ``FusionError``) when the item cannot be resolved.
    """
    log = log if log is not None else _module_log
    lines = lookup_lines(extraction)
    flags: set[InfoFlag] = set()
    anchor: str | None = None
    method = ResolutionMethod.INVOICE
    alias_ids: tuple[int, ...] = ()
    account: FusionCustomer | None = None

    # 1 and 2: a person's choice, then payer aliases.
    if human_customer_number:
        try:
            account = await fusion.get_customer_account(human_customer_number)
        except FusionError as exc:
            if exc.code is ErrorCode.CUSTOMER_NOT_FOUND:
                raise StageError(ErrorCode.CUSTOMER_NOT_FOUND, {"source": "human_hint"}) from exc
            raise _fusion_error(exc, "get_customer_account") from exc
        anchor, method = human_customer_number, ResolutionMethod.HUMAN
    else:
        references = [
            ref
            for ref in (
                extraction.remittance_reference.value,
                *(line.transaction_number for line in lines),
            )
            if ref
        ]
        match = await aliases.lookup(
            extraction.payer_name.value, extraction.payer_bank_account.value, references
        )
        customers = tuple(dict.fromkeys(match.customer_numbers))
        if len(customers) > 1:
            raise StageError(
                ErrorCode.CUSTOMER_MULTIPLE_ACCOUNTS,
                {"alias_ids": list(match.alias_ids), "customer_count": len(customers)},
            )
        if customers:
            anchor, method = customers[0], ResolutionMethod.ALIAS
            alias_ids = tuple(match.alias_ids)
            flags.add(InfoFlag.ALIAS_USED)

    # 3: one batched lookup, always, so later stations reuse the result.
    transactions: list[FusionTransaction] = []
    unique_numbers = list(dict.fromkeys(line.transaction_number.strip() for line in lines))
    if unique_numbers:
        try:
            transactions = await fusion.find_transactions(unique_numbers)
        except FusionError as exc:
            raise _fusion_error(exc, "find_transactions") from exc
    by_number: dict[str, list[FusionTransaction]] = defaultdict(list)
    for transaction in transactions:
        by_number[transaction.number].append(transaction)

    # 4 and 5: the invoice-path anchor.
    anchor_line_no: int | None = None
    if anchor is None:
        anchor, anchor_line_no = _invoice_anchor(lines, by_number)

    # 6: relationships widen the receipt search.
    related = await _related(fusion, anchor, log)

    # 7: per-line findings. They never fail the item.
    findings = _findings(lines, by_number, frozenset({anchor, *related}))
    if any(f.status is LineFindingStatus.CUSTOMER_MISMATCH for f in findings):
        flags.add(InfoFlag.MULTIPLE_ACCOUNTS_SAME_RECEIPT)

    # 8: currency.
    currency, source, from_customer = await _currency(
        extraction, anchor, account, transactions, fusion
    )
    if from_customer:
        flags.add(InfoFlag.CURRENCY_RESOLVED_FROM_CUSTOMER)

    return CustomerResolution(
        anchor_customer_number=anchor,
        related_customer_numbers=related,
        method=method,
        alias_ids=alias_ids,
        transactions=transactions,
        currency=currency,
        flags=flags,
        anchor_line_no=anchor_line_no,
        currency_source=source,
        line_findings=findings,
    )
