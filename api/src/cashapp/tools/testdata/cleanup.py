"""Cleanup: list the tagged records a run created and print how to remove them by hand.

This module only reads. It never calls a delete, void, reverse or unapply: removal is a person's
decision made in Fusion's own screens, following the steps `render_cleanup_steps` prints.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, cast

from cashapp.integrations.fusion import FusionClient, q_in
from cashapp.integrations.fusion.query import chunked
from cashapp.tools.testdata import payloads
from cashapp.tools.testdata.models import CleanupReport, GeneratedData, TaggedRecord
from cashapp.tools.testdata.tagging import is_tagged, validate_tag

_CHUNK = 25  # Fusion lists 25 rows per page by default

Kind = Literal["INVOICE", "CREDIT_MEMO", "RECEIPT"]

# (resource, number field, id field, status field, fields requested)
_LOOKUPS: dict[Kind, tuple[str, str, str, str, str]] = {
    "INVOICE": (
        payloads.PATH_INVOICES,
        "TransactionNumber",
        "CustomerTransactionId",
        "InvoiceStatus",
        "CustomerTransactionId,TransactionNumber,InvoiceStatus,Comments",
    ),
    "CREDIT_MEMO": (
        payloads.PATH_CREDIT_MEMOS,
        "TransactionNumber",
        "CustomerTransactionId",
        "TransactionStatus",
        "CustomerTransactionId,TransactionNumber,TransactionStatus,Comments",
    ),
    "RECEIPT": (
        payloads.PATH_RECEIPTS,
        "ReceiptNumber",
        "StandardReceiptId",
        "Status",
        "StandardReceiptId,ReceiptNumber,Status,State,Comments",
    ),
}


def _tag_dir(manifest_dir: Path, tag: str) -> Path:
    return manifest_dir / validate_tag(tag)


def load_manifests(manifest_dir: Path, tag: str) -> list[GeneratedData]:
    """Every manifest `generate` wrote for the tag, oldest first."""
    directory = _tag_dir(manifest_dir, tag)
    if not directory.is_dir():
        return []
    return [
        GeneratedData.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("manifest-*.json"))
    ]


def _manifest_numbers(manifests: list[GeneratedData]) -> dict[Kind, dict[str, int | None]]:
    numbers: dict[Kind, dict[str, int | None]] = {"INVOICE": {}, "CREDIT_MEMO": {}, "RECEIPT": {}}
    for manifest in manifests:
        for record in manifest.records:
            if record.kind == "APPLICATION":
                continue
            numbers[record.kind].setdefault(record.number, record.fusion_id)
    return numbers


async def _read_rows(
    fusion: FusionClient, kind: Kind, numbers: list[str]
) -> dict[str, Mapping[str, Any]]:
    resource, number_field, _id_field, _status_field, fields = _LOOKUPS[kind]
    rows: dict[str, Mapping[str, Any]] = {}
    for chunk in chunked(numbers, _CHUNK):
        response = await fusion.rest_get(
            resource, {"q": q_in(number_field, chunk), "fields": fields}
        )
        items = cast("list[Any]", response.get("items") or [])
        for item in items:
            if isinstance(item, dict):
                row = cast("dict[str, Any]", item)
                number = row.get(number_field)
                if isinstance(number, str):
                    rows[number] = row
    return rows


async def cleanup(
    tag: str,
    fusion: FusionClient,
    *,
    manifest_dir: Path,
    guard: Callable[[], None] | None = None,
) -> CleanupReport:
    """List the tagged records of a run (reads only)."""
    tag = validate_tag(tag)
    if guard is not None:
        guard()
    numbers = _manifest_numbers(load_manifests(manifest_dir, tag))
    records: list[TaggedRecord] = []
    for kind in ("INVOICE", "CREDIT_MEMO", "RECEIPT"):
        wanted = numbers[kind]
        if not wanted:
            continue
        _resource, _number_field, id_field, status_field, _fields = _LOOKUPS[kind]
        rows = await _read_rows(fusion, kind, list(wanted))
        for number, manifest_id in wanted.items():
            row = rows.get(number)
            if row is None:
                records.append(
                    TaggedRecord(kind=kind, number=number, fusion_id=manifest_id, found=False)
                )
                continue
            comments = row.get("Comments")
            if not is_tagged(number, comments if isinstance(comments, str) else None, tag):
                continue  # a look-alike that is not ours: never listed
            raw_id = row.get(id_field)
            status = row.get(status_field)
            records.append(
                TaggedRecord(
                    kind=kind,
                    number=number,
                    fusion_id=int(raw_id) if isinstance(raw_id, int | str) else manifest_id,
                    status=str(status) if status is not None else None,
                    found=True,
                )
            )
    return CleanupReport(tag=tag, pod_name=fusion.pod_name, records=records)


def render_cleanup_steps(report: CleanupReport) -> str:
    """Plain-text steps to remove the records by hand in Fusion. Nothing is deleted by the tool."""
    lines = [
        f"Cleanup for tag {report.tag} on pod {report.pod_name}",
        "This tool deletes nothing; follow these steps in Fusion.",
        "",
    ]
    receipts = [r for r in report.records if r.kind == "RECEIPT"]
    transactions = [r for r in report.records if r.kind != "RECEIPT"]
    if receipts:
        lines.append("Receipts (do these first, so no application blocks the transactions):")
        for record in receipts:
            lines.append(
                f"  - {record.number}{_suffix(record)}: unapply any application, then "
                f"Receivables > Manage Receipts > {record.number} > Reverse (reason: test data)"
            )
        lines.append("")
    if transactions:
        lines.append("Invoices and credit memos:")
        for record in transactions:
            label = "credit memo" if record.kind == "CREDIT_MEMO" else "invoice"
            lines.append(
                f"  - {record.number} ({label}){_suffix(record)}: Manage Transactions > "
                f"{record.number} > mark Incomplete, then Delete; if already posted, "
                "Credit the transaction instead"
            )
        lines.append("")
    if not report.records:
        lines.append("No tagged records were found in the manifests.")
    return "\n".join(lines).rstrip() + "\n"


def _suffix(record: TaggedRecord) -> str:
    if not record.found:
        return " [not found in Fusion]"
    return f" [status {record.status}]" if record.status else ""
