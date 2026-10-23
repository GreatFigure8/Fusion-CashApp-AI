"""Fixture files for a plan: the remittance CSV, a gold JSON for s24 and a fake ledger.

Only the CSV is ever copied to a drop folder, so the pipeline's FolderSource never ingests the JSON.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from cashapp.domain.extraction import ExtractedLine
from cashapp.domain.money import to_money
from cashapp.integrations.fusion.models import TransactionKind
from cashapp.tools.testdata.models import GeneratedData, PlannedTransaction, ScenarioPlan
from cashapp.tools.testdata.tagging import tag_marker

GOLD_SCHEMA = "cashapp-testdata-gold@1"
_FIRST_TRX_ID = 100001
_FIRST_RECEIPT_ID = 500001
_FIRST_APPLICATION_ID = 900001


@dataclass(frozen=True, slots=True)
class FixturePaths:
    plan: Path
    remittance_csv: Path
    gold: Path
    fusion: Path
    dropped_csv: Path | None


def _money_cell(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _line_row(line: ExtractedLine) -> list[str]:
    return [
        line.transaction_number,
        _money_cell(line.gross_amount),
        _money_cell(line.discount_claimed),
        _money_cell(line.deduction),
        _money_cell(line.amount_paid),
    ]


def render_remittance_csv(plan: ScenarioPlan) -> str:
    """A remittance-advice CSV: a header block, then a table of the lines being paid."""
    remittance = plan.remittance
    payment_amount = remittance.payment_amount.value
    payment_date = remittance.payment_date.value
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Payer", remittance.payer_name.value or ""])
    writer.writerow(["Remittance reference", remittance.remittance_reference.value or ""])
    writer.writerow(["Payment date", payment_date.isoformat() if payment_date else ""])
    writer.writerow(["Payment amount", _money_cell(payment_amount)])
    writer.writerow(["Currency", remittance.currency.value or ""])
    writer.writerow([])
    writer.writerow(["Invoice number", "Gross amount", "Discount", "Deduction", "Amount paid"])
    for line in remittance.lines:
        writer.writerow(_line_row(line))
    return buffer.getvalue()


def _transaction_rows(plan: ScenarioPlan) -> tuple[list[dict[str, Any]], dict[str, int]]:
    applied: dict[str, Decimal] = {}
    for application in plan.pre_applications:
        applied[application.transaction_number] = (
            applied.get(application.transaction_number, Decimal("0.00")) + application.amount
        )
    ids: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    entries: list[tuple[PlannedTransaction, TransactionKind]] = [
        *((t, TransactionKind.INVOICE) for t in plan.invoices),
        *((t, TransactionKind.CREDIT_MEMO) for t in plan.credit_memos),
    ]
    for offset, (txn, kind) in enumerate(entries):
        trx_id = _FIRST_TRX_ID + offset
        ids[txn.number] = trx_id
        balance = to_money(txn.amount - applied.get(txn.number, Decimal("0.00")))
        rows.append(
            {
                "customer_trx_id": trx_id,
                "number": txn.number,
                "kind": kind.value,
                "balance": f"{balance:.2f}",
                "original_amount": f"{txn.amount:.2f}",
                "currency": txn.currency,
                "status": "Open",
                "bill_to_customer_number": plan.customer_account,
                "bill_to_site": None,
                "business_unit": None,
                "payment_terms": txn.terms,
            }
        )
    return rows, ids


def plan_to_fake_json(plan: ScenarioPlan) -> dict[str, Any]:
    """The post-generation Fusion state, in the shape `FakeFusionClient.from_json` loads."""
    transactions, trx_ids = _transaction_rows(plan)
    receipt_ids: dict[str, int] = {}
    receipts: list[dict[str, Any]] = []
    for offset, receipt in enumerate(plan.receipts):
        receipt_id = _FIRST_RECEIPT_ID + offset
        receipt_ids[receipt.number] = receipt_id
        used = sum(
            (a.amount for a in plan.pre_applications if a.receipt_number == receipt.number),
            Decimal("0.00"),
        )
        unapplied = to_money(receipt.amount - used)
        receipts.append(
            {
                "receipt_id": receipt_id,
                "receipt_number": receipt.number,
                "amount": f"{receipt.amount:.2f}",
                "unapplied_amount": f"{unapplied:.2f}",
                "currency": receipt.currency,
                "customer_account_number": plan.customer_account,
                "receipt_date": receipt.receipt_date.isoformat(),
                "creation_date": datetime.combine(
                    receipt.receipt_date, time.min, tzinfo=UTC
                ).isoformat(),
                "status": "UNAPP" if unapplied == receipt.amount else "APP",
                "state": "CLEARED",
                "remittance_references": list(receipt.references),
                "comments": tag_marker(plan.tag),
            }
        )
    applications = [
        {
            "application_id": _FIRST_APPLICATION_ID + offset,
            "receipt_id": receipt_ids[a.receipt_number],
            "customer_trx_id": trx_ids[a.transaction_number],
            "amount_applied": f"{a.amount:.2f}",
            "apply_date": plan.params.as_of.isoformat(),
            "status": "APP",
        }
        for offset, a in enumerate(plan.pre_applications)
    ]
    return {
        "customers": [
            {
                "account_number": plan.customer_account,
                "name": plan.remittance.payer_name.value or "",
                "currency_codes": [plan.params.currency],
                "sites": [],
            }
        ],
        "transactions": transactions,
        "receipts": receipts,
        "applications": applications,
        "relationships": [],
    }


def _write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def write_fixtures(
    plan: ScenarioPlan, out_dir: Path, *, drop_folder: Path | None = None
) -> FixturePaths:
    directory = out_dir / plan.tag
    directory.mkdir(parents=True, exist_ok=True)
    stem = plan.scenario.value
    plan_path = directory / f"{stem}.plan.json"
    csv_path = directory / f"{stem}.remittance.csv"
    gold_path = directory / f"{stem}.gold.json"
    fusion_path = directory / f"{stem}.fusion.json"

    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    csv_path.write_text(render_remittance_csv(plan), encoding="utf-8", newline="")
    _write_json(
        gold_path,
        {
            "schema": GOLD_SCHEMA,
            "artifact": csv_path.name,
            "extraction": json.loads(plan.remittance.model_dump_json()),
            "expected": json.loads(plan.expected.model_dump_json()),
        },
    )
    _write_json(fusion_path, plan_to_fake_json(plan))

    dropped: Path | None = None
    if drop_folder is not None:
        drop_folder.mkdir(parents=True, exist_ok=True)
        dropped = drop_folder / f"CATD-{plan.tag}-{stem}.csv"
        shutil.copyfile(csv_path, dropped)
    return FixturePaths(
        plan=plan_path,
        remittance_csv=csv_path,
        gold=gold_path,
        fusion=fusion_path,
        dropped_csv=dropped,
    )


def write_manifest(data: GeneratedData, out_dir: Path) -> Path:
    """Record what a run created so `cleanup` can find it later."""
    directory = out_dir / data.tag
    directory.mkdir(parents=True, exist_ok=True)
    stamp = data.created_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"manifest-{data.scenario.value}-{stamp}.json"
    path.write_text(data.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    return path
