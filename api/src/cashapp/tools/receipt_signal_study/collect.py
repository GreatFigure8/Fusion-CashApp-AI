"""Read side of the study: receipts, applications, statement lines, relationships, cases.

Everything goes through the `FusionClient` read methods (the caller passes a `read_only` client).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from cashapp.domain.money import to_money
from cashapp.domain.status import APPLIED_LINE_STATUSES
from cashapp.integrations.fusion import (
    FusionApplication,
    FusionClient,
    FusionReceipt,
    FusionTransaction,
)
from cashapp.integrations.fusion.xmlutil import child_text, iter_local, safe_fromstring
from cashapp.tools.receipt_signal_study.models import (
    StatementSignals,
    StudyCase,
    StudyReceipt,
)
from cashapp.tools.receipt_signal_study.signals import (
    hash_account,
    name_tokens,
    normalise_reference,
    tokenize,
)

PAGE_SIZE = 500
APPLICATION_CONCURRENCY = 4
LOOKUP_CHUNK = 50
ACTIVE_APPLICATION = "APP"
_MAX_EMPTY_PAGES = 1000


async def collect_receipts(
    client: FusionClient, *, created_from: datetime, created_to: datetime, limit: int
) -> list[FusionReceipt]:
    """Receipts created in `[created_from, created_to)`, paged by creation time and deduped."""
    seen: dict[int, FusionReceipt] = {}
    since = created_from
    for _ in range(_MAX_EMPTY_PAGES):
        page = await client.receipts_created_since(since, limit=PAGE_SIZE)
        added = 0
        for receipt in page:
            if receipt.creation_date >= created_to or len(seen) >= limit:
                return list(seen.values())
            if receipt.receipt_id not in seen:
                seen[receipt.receipt_id] = receipt
                added += 1
        if len(page) < PAGE_SIZE:
            break
        last = page[-1].creation_date
        # A full page of already-seen receipts means one instant holds more than a page; step past.
        since = last if added else last + timedelta(microseconds=1)
    return list(seen.values())


async def collect_applications(
    client: FusionClient, receipt_ids: Iterable[int]
) -> dict[int, tuple[FusionApplication, ...]]:
    """Active applications per receipt (the right answers). Reads are semaphore-bounded."""
    gate = asyncio.Semaphore(APPLICATION_CONCURRENCY)

    async def one(receipt_id: int) -> tuple[int, tuple[FusionApplication, ...]]:
        async with gate:
            apps = await client.list_receipt_applications(receipt_id)
        return receipt_id, tuple(a for a in apps if a.status == ACTIVE_APPLICATION)

    pairs = await asyncio.gather(*(one(i) for i in receipt_ids))
    return {receipt_id: apps for receipt_id, apps in pairs if apps}


def parse_statement_signals(xml: bytes) -> dict[int, StatementSignals]:
    """Parse the receipt-signals data model rows. The bank account arrives already hashed."""
    refs: dict[int, list[str]] = {}
    addenda: dict[int, list[str]] = {}
    names: dict[int, list[str]] = {}
    hashes: dict[int, list[str]] = {}
    root = safe_fromstring(xml)
    for row in iter_local(root, "G_1"):
        raw_id = child_text(row, "CASH_RECEIPT_ID")
        if raw_id is None or not raw_id.isdigit():
            continue
        receipt_id = int(raw_id)
        for target, tag in (
            (refs, "STATEMENT_LINE_REFERENCE"),
            (addenda, "STATEMENT_LINE_ADDENDA"),
            (names, "STATEMENT_PAYER_NAME"),
        ):
            value = child_text(row, tag)
            if value is not None:
                target.setdefault(receipt_id, []).append(value)
        account_hash = child_text(row, "PAYER_BANK_ACCOUNT_HASH")
        if account_hash is not None:
            hashes.setdefault(receipt_id, []).append(account_hash.lower())
    ids = set(refs) | set(addenda) | set(names) | set(hashes)
    return {
        i: StatementSignals(
            receipt_id=i,
            statement_references=tuple(refs.get(i, ())),
            addenda_texts=tuple(addenda.get(i, ())),
            payer_names=tuple(names.get(i, ())),
            bank_account_hashes=tuple(hashes.get(i, ())),
        )
        for i in ids
    }


async def collect_statement_signals(
    client: FusionClient, report_path: str, *, created_from: datetime, created_to: datetime
) -> dict[int, StatementSignals]:
    xml = await client.run_report(
        report_path,
        {
            "P_DATE_FROM": created_from.date().isoformat(),
            "P_DATE_TO": created_to.date().isoformat(),
        },
    )
    return parse_statement_signals(xml)


async def collect_transactions(
    client: FusionClient, numbers: Iterable[str]
) -> dict[str, FusionTransaction]:
    """Normalised number -> transaction, looked up in batches."""
    unique = sorted(set(numbers))
    found: dict[str, FusionTransaction] = {}
    for start in range(0, len(unique), LOOKUP_CHUNK):
        for txn in await client.find_transactions(unique[start : start + LOOKUP_CHUNK]):
            found[normalise_reference(txn.number)] = txn
    return found


async def collect_relationships(
    client: FusionClient, accounts: Iterable[str]
) -> dict[str, frozenset[str]]:
    """Anchor account -> accounts related to it in either direction."""
    unique = sorted(set(accounts))
    related: dict[str, set[str]] = {}
    for start in range(0, len(unique), LOOKUP_CHUNK):
        for rel in await client.customer_relationships(unique[start : start + LOOKUP_CHUNK]):
            related.setdefault(rel.account_number, set()).add(rel.related_account_number)
    return {k: frozenset(v) for k, v in related.items()}


def build_study_receipts(
    receipts: Iterable[FusionReceipt],
    *,
    applications: Mapping[int, tuple[FusionApplication, ...]],
    statements: Mapping[int, StatementSignals],
    transactions: Mapping[str, FusionTransaction],
) -> dict[int, StudyReceipt]:
    """Resolve each receipt's tokens and referenced transaction ids once."""
    out: dict[int, StudyReceipt] = {}
    for receipt in receipts:
        statement = statements.get(receipt.receipt_id)
        reference_tokens = frozenset(
            normalise_reference(r) for r in receipt.remittance_references if r.strip()
        )
        comment_tokens = tokenize(receipt.comments)
        addenda_tokens: frozenset[str] = frozenset()
        if statement:
            for text in statement.addenda_texts:
                addenda_tokens |= tokenize(text)
        statement_refs = frozenset(
            normalise_reference(r) for r in (statement.statement_references if statement else ())
        )
        everything = reference_tokens | comment_tokens | addenda_tokens | statement_refs
        out[receipt.receipt_id] = StudyReceipt(
            receipt=receipt,
            statement=statement,
            comment_tokens=comment_tokens,
            addenda_tokens=addenda_tokens,
            reference_tokens=reference_tokens,
            statement_reference_tokens=statement_refs,
            payer_name_tokens=frozenset(
                t
                for t in (name_tokens(n) for n in (statement.payer_names if statement else ()))
                if t
            ),
            referenced_transaction_ids=frozenset(
                transactions[t].customer_trx_id for t in everything if t in transactions
            ),
            applications=applications.get(receipt.receipt_id, ()),
        )
    return out


def build_cases_from_fusion(
    study_receipts: Mapping[int, StudyReceipt],
    *,
    date_from: date,
    date_to: date,
    transactions: Mapping[str, FusionTransaction],
) -> list[StudyCase]:
    """One case per truth-bearing receipt, with the remittance reconstructed from the truth."""
    by_id = {t.customer_trx_id: (n, t) for n, t in transactions.items()}
    cases: list[StudyCase] = []
    for receipt_id in sorted(study_receipts):
        sr = study_receipts[receipt_id]
        r = sr.receipt
        if not sr.applications or not date_from <= r.receipt_date <= date_to:
            continue
        amount = to_money(sum((a.amount_applied for a in sr.applications), Decimal("0")))
        if amount <= 0:
            continue
        ids = frozenset(a.customer_trx_id for a in sr.applications)
        resolved = [by_id[a.customer_trx_id] for a in sr.applications if a.customer_trx_id in by_id]
        statement = sr.statement
        names = sorted(tuple(sorted(n)) for n in sr.payer_name_tokens)
        cases.append(
            StudyCase(
                case_id=len(cases) + 1,
                truth_receipt_id=receipt_id,
                currency=r.currency,
                amount=amount,
                payment_date=r.receipt_date,
                anchor_account=next(
                    (t.bill_to_customer_number for _, t in resolved if t.bill_to_customer_number),
                    None,
                ),
                invoice_numbers=frozenset(n for n, _ in resolved),
                invoice_ids=ids,
                reference_tokens=sr.reference_tokens,
                payer_name_tokens=frozenset(names[0]) if names else frozenset(),
                bank_account_hashes=frozenset(statement.bank_account_hashes)
                if statement
                else frozenset(),
            )
        )
    return cases


def _value(extraction: Mapping[str, Any], key: str) -> Any:
    field = extraction.get(key)
    return cast("Mapping[str, Any]", field).get("value") if isinstance(field, dict) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(cast("dict[str, Any]", json.loads(line)))
    return rows


def prior_numbers(prior_dir: Path) -> set[str]:
    """Every invoice number the prior messages name (for the transaction lookup)."""
    numbers: set[str] = set()
    for row in _read_jsonl(prior_dir / "day" / "messages.jsonl"):
        extraction = cast("dict[str, Any]", row.get("extraction") or {})
        for line in cast("list[dict[str, Any]]", extraction.get("lines", [])):
            number = str(line.get("transaction_number") or "").strip()
            if number:
                numbers.add(number)
    return numbers


def build_cases_from_prior(
    prior_dir: Path,
    study_receipts: Mapping[int, StudyReceipt],
    *,
    transactions: Mapping[str, FusionTransaction],
) -> list[StudyCase]:
    """One case per prior message with applied lines; truth = the receipt covering those lines."""
    applied_values = {s.value for s in APPLIED_LINE_STATUSES}
    cases: list[StudyCase] = []
    for row in _read_jsonl(prior_dir / "day" / "messages.jsonl"):
        outcome = cast("dict[str, Any]", row.get("outcome") or {})
        extraction = cast("dict[str, Any]", row.get("extraction") or {})
        if not any(
            ol.get("line_status") in applied_values
            for ol in cast("list[dict[str, Any]]", outcome.get("lines", []))
        ):
            continue
        try:
            amount = to_money(str(_value(extraction, "payment_amount")))
            paid_on = date.fromisoformat(str(_value(extraction, "payment_date"))[:10])
        except (InvalidOperation, ValueError, TypeError):
            continue
        numbers = [
            normalise_reference(str(line.get("transaction_number")))
            for line in cast("list[dict[str, Any]]", extraction.get("lines", []))
            if str(line.get("transaction_number") or "").strip()
        ]
        resolved = [transactions[n] for n in numbers if n in transactions]
        ids = frozenset(t.customer_trx_id for t in resolved)
        truth = _truth_receipt(study_receipts, ids)
        if truth is None:
            continue
        reference = _value(extraction, "remittance_reference")
        account = _value(extraction, "payer_bank_account")
        currency = _value(extraction, "currency") or _value(extraction, "currency_raw")
        cases.append(
            StudyCase(
                case_id=len(cases) + 1,
                truth_receipt_id=truth,
                currency=str(currency or study_receipts[truth].receipt.currency).upper(),
                amount=amount,
                payment_date=paid_on,
                anchor_account=next((t.bill_to_customer_number for t in resolved), None),
                invoice_numbers=frozenset(numbers),
                invoice_ids=ids,
                reference_tokens=frozenset({normalise_reference(str(reference))})
                if reference
                else frozenset(),
                payer_name_tokens=name_tokens(cast("str | None", _value(extraction, "payer_name"))),
                bank_account_hashes=frozenset({hash_account(str(account))})
                if account
                else frozenset(),
            )
        )
    return cases


def _truth_receipt(
    study_receipts: Mapping[int, StudyReceipt], invoice_ids: frozenset[int]
) -> int | None:
    best: tuple[int, int] | None = None  # (overlap, receipt_id)
    for receipt_id, sr in study_receipts.items():
        overlap = len(invoice_ids & {a.customer_trx_id for a in sr.applications})
        if overlap and (best is None or (overlap, -receipt_id) > (best[0], -best[1])):
            best = (overlap, receipt_id)
    return best[1] if best else None


def references_of(receipts: Iterable[FusionReceipt]) -> set[str]:
    return {r for receipt in receipts for r in receipt.remittance_references if r.strip()}


def utc_midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def accounts_of(cases: Sequence[StudyCase]) -> set[str]:
    return {c.anchor_account for c in cases if c.anchor_account}
