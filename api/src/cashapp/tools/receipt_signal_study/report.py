"""Aggregate-only output: signals.csv, signals.json, run.json. Rows are keyed by signal name."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cashapp.tools.receipt_signal_study.models import SignalStat, StudyResult

CSV_COLUMNS: tuple[str, ...] = (
    "signal",
    "present",
    "cases",
    "presence_rate",
    "precision",
    "ambiguous_rate",
    "miss_rate",
    "circular",
    "skipped_reason",
)
CSV_NAME = "signals.csv"
JSON_NAME = "signals.json"
RUN_NAME = "run.json"


def _row(stat: SignalStat) -> dict[str, Any]:
    row = asdict(stat)
    row["signal"] = stat.signal.value
    return row


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_report(result: StudyResult, out_dir: Path) -> list[Path]:
    """Write the three output files; returns their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [_row(s) for s in result.stats]

    csv_path = out_dir / CSV_NAME
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            writer.writerow([_csv_cell(row[c]) for c in CSV_COLUMNS])

    json_path = out_dir / JSON_NAME
    json_path.write_text(
        json.dumps(
            {
                "signals": rows,
                "date_distance": {k: dict(v) for k, v in result.date_distance.items()},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    run_path = out_dir / RUN_NAME
    run_path.write_text(
        json.dumps(
            {
                "pod": result.pod,
                "from": result.date_from.isoformat(),
                "to": result.date_to.isoformat(),
                "case_source": result.case_source,
                "receipts": result.receipts,
                "pool": result.pool,
                "cases": result.cases,
                "date_window_days": result.date_window_days,
                "tolerances": {k: f"{v:.2f}" for k, v in result.tolerances.items()},
                "skipped_signals": {
                    s.signal.value: s.skipped_reason for s in result.stats if s.skipped_reason
                },
                "provisional": result.provisional,
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return [csv_path, json_path, run_path]
