"""``report.json`` (the stable contract) and ``report.md`` (the same numbers for reading)."""

import json
from pathlib import Path

from cashapp.evals.models import (
    AutofixSuiteReport,
    ConfusionMatrix,
    CostSummary,
    EvalReport,
    ExtractionSuiteReport,
    MatchingSuiteReport,
    Ratio,
    SuiteStatus,
)

__all__ = ["render_markdown", "write_report"]

JSON_NAME = "report.json"
MARKDOWN_NAME = "report.md"


def write_report(report: EvalReport, out_dir: Path) -> tuple[Path, Path]:
    """Write both files into ``out_dir``, which the runner created exclusively for this run."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / JSON_NAME
    md_path = out_dir / MARKDOWN_NAME
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.1f}%"


def _ratio(value: Ratio) -> str:
    return f"{_pct(value.rate)} ({value.correct}/{value.total})"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _matrix(matrix: ConfusionMatrix, corner: str) -> list[str]:
    rows = [
        [name, *(str(n) for n in counts)]
        for name, counts in zip(matrix.rows, matrix.counts, strict=True)
        if any(counts)
    ]
    if not rows:
        return ["No cases."]
    used = [i for i in range(len(matrix.cols)) if any(c[i] for c in matrix.counts)]
    pruned = [[row[0], *(row[1 + i] for i in used)] for row in rows]
    return _table([corner, *(matrix.cols[i] for i in used)], pruned)


def _banner(reason: str | None) -> list[str]:
    return [
        "",
        f"**NOT EVALUATED**: {reason or 'no cases'}. Nothing was measured; this is not a pass.",
    ]


def _cost(cost: CostSummary) -> list[str]:
    lines = [
        "## Cost",
        "",
        f"Mode: {cost.mode}. Calls: {cost.calls}. Tokens in/out: {cost.input_tokens}/"
        f"{cost.output_tokens}. Spent: ${cost.spent_usd}. "
        f"Recorded usage: ${cost.recorded_usage_usd}.",
        "",
    ]
    rows = [
        [role, str(c.calls), str(c.input_tokens), str(c.output_tokens), c.cost_usd or "unpriced"]
        for role, c in cost.by_role.items()
    ]
    if rows:
        lines += _table(["Role", "Calls", "Input tokens", "Output tokens", "USD"], rows)
    else:
        lines.append("No model calls were made.")
    if cost.unknown_price_models:
        lines += ["", "No price for: " + ", ".join(cost.unknown_price_models)]
    return lines


def _extraction(suite: ExtractionSuiteReport) -> list[str]:
    lines = ["## Extraction", ""]
    lines.append(f"Cases: {suite.cases}. Runs per case: {suite.runs}.")
    if suite.status is SuiteStatus.NOT_EVALUATED:
        return [*lines, *_banner(suite.reason)]
    names = ["reader_a", "reader_b", "adjudicated"]
    fields = sorted({f for v in suite.by_variant.values() for f in v.fields})
    rows = [
        [
            f,
            *(
                _ratio(suite.by_variant[n].fields[f]) if f in suite.by_variant[n].fields else "-"
                for n in names
            ),
        ]
        for f in fields
    ]
    rows.append(["fee lines", *(_ratio(suite.by_variant[n].fee_lines) for n in names)])
    rows.append(
        ["line amount (matched)", *(_ratio(suite.by_variant[n].line_amount) for n in names)]
    )
    rows.append(["line kind (matched)", *(_ratio(suite.by_variant[n].line_kind) for n in names)])
    rows.append(["failed variants", *(str(suite.by_variant[n].failures) for n in names)])
    lines += ["", "### Per-field accuracy", "", *_table(["Field", "A", "B", "Adjudicated"], rows)]
    line_rows = [
        [
            n,
            _pct(suite.by_variant[n].lines.precision),
            _pct(suite.by_variant[n].lines.recall),
            _pct(suite.by_variant[n].lines.f1),
            f"{suite.by_variant[n].lines.true_positive}/{suite.by_variant[n].lines.expected}",
        ]
        for n in names
    ]
    lines += [
        "",
        "### Transaction lines",
        "",
        *_table(["Variant", "Precision", "Recall", "F1", "Found/expected"], line_rows),
    ]
    return lines


def _matching(suite: MatchingSuiteReport) -> list[str]:
    lines = ["## Matching", ""]
    lines.append(f"Messages replayed: {suite.messages}. With an AR label: {suite.labelled}.")
    if suite.status is SuiteStatus.NOT_EVALUATED:
        return [*lines, *_banner(suite.reason)]
    lines += [
        "",
        "Agreement with AR's labels (the prior outcomes came from a build with known defects, "
        "so this is agreement, not accuracy): "
        f"{_ratio(suite.label_agreement)}",
        "",
        *_table(
            ["Label", "Agreement"],
            [[label, _ratio(r)] for label, r in suite.agreement_by_label.items()],
        ),
        "",
        "### Label confusion (rows: AR label, columns: new outcome)",
        "",
        *_matrix(suite.label_confusion, "AR label"),
        "",
        f"### Line-status agreement: {_ratio(suite.line_status_agreement)}",
        "",
        *_matrix(suite.line_status_confusion, "prior status"),
    ]
    if suite.skipped:
        lines += ["", "Skipped: " + ", ".join(f"{k}={v}" for k, v in sorted(suite.skipped.items()))]
    return lines


def _autofix(suite: AutofixSuiteReport) -> list[str]:
    lines = ["## Auto-fix", "", f"Cases: {suite.cases}."]
    if suite.status is SuiteStatus.NOT_EVALUATED:
        return [*lines, *_banner(suite.reason)]
    lines += [
        "",
        f"Decision agreement with the expected decision: {_ratio(suite.agreement)}",
        "",
        *_table(
            ["Label", "Agreement"],
            [[label, _ratio(r)] for label, r in suite.agreement_by_label.items()],
        ),
        "",
        "### Confusion (rows: expected, columns: actual)",
        "",
        *_matrix(suite.confusion, "expected"),
        "",
        "Error codes seen: "
        + (", ".join(f"{k}={v}" for k, v in suite.codes_seen.items()) or "none"),
    ]
    if suite.skipped:
        lines += ["", "Skipped: " + ", ".join(f"{k}={v}" for k, v in sorted(suite.skipped.items()))]
    return lines


def render_markdown(report: EvalReport) -> str:
    """The human-readable report, rendered from the same object that becomes ``report.json``."""
    lines = [
        f"# Evaluation run {report.run_id}",
        "",
        f"- Mode: {'replay' if report.replay else 'live'}",
        f"- Suites: {', '.join(s.value for s in report.suites)}",
        f"- Limit: {report.limit if report.limit is not None else 'none'}. Runs: {report.runs}",
        f"- Started: {report.started_at.isoformat()}. Finished: {report.finished_at.isoformat()}",
        f"- cashapp {report.cashapp_version}",
        "- Models: " + ", ".join(f"{k}={v}" for k, v in report.models.items()),
        "- Versions: " + ", ".join(f"{k}={v}" for k, v in report.prompt_versions.items()),
        "- Config overrides: "
        + (json.dumps(report.config_overrides, sort_keys=True, default=str) or "{}"),
        "",
        *_cost(report.cost),
    ]
    for section in (
        _extraction(report.extraction) if report.extraction else None,
        _matching(report.matching) if report.matching else None,
        _autofix(report.autofix) if report.autofix else None,
    ):
        if section is not None:
            lines += ["", *section]
    return "\n".join(lines) + "\n"
