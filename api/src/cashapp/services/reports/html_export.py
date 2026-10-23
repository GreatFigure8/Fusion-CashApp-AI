"""Render a self-contained HTML progress report: one document, inline CSS, no scripts.

The preview and the export are the same bytes from the same call, so what a person sees is what
they email. Everything untrusted (payer names, references) reaches the page only through Jinja2
autoescape: there is no ``|safe`` and no ``Markup`` here or in the template.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Final

from jinja2 import Environment, PackageLoader, StrictUndefined

from cashapp.domain.clock import Clock
from cashapp.domain.principal import Principal
from cashapp.domain.reports import (
    HtmlReportKind,
    ReportSection,
    ReportWindow,
    report_filename,
)
from cashapp.services.exceptions_query import ExceptionsQueryService
from cashapp.services.metrics.models import ThroughputPoint
from cashapp.services.metrics.service import MetricsService
from cashapp.services.reports.html_figures import ReportFigures, gather_figures

if TYPE_CHECKING:
    from cashapp.data.uow import UnitOfWork

TEMPLATE: Final = "progress_report.html.j2"
TITLE: Final = "Cash application progress"
SVG_WIDTH: Final = 400
SVG_HEIGHT: Final = 100
_PAD: Final = 6
_DASH: Final = "\N{EM DASH}"
_EN_DASH: Final = "\N{EN DASH}"
_ONE_DP: Final = Decimal("0.1")
_HUNDRED: Final = Decimal(100)

_ENV: Final = Environment(
    loader=PackageLoader("cashapp.services.reports", "templates"),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True, slots=True)
class RenderedReport:
    filename: str
    html: str
    bytes: int
    generated_at: datetime
    has_data: bool


def throughput_path(
    points: Sequence[ThroughputPoint], width: int = SVG_WIDTH, height: int = SVG_HEIGHT
) -> str:
    """An SVG path of items applied per bucket. A flat baseline for no points or all zeros."""
    base = height - _PAD
    peak = max((point.applied for point in points), default=0)
    if len(points) < 2 or peak == 0:
        return f"M0 {base} L{width} {base}"
    span = base - _PAD
    step = width / (len(points) - 1)
    coords = [
        f"{index * step:.1f} {base - span * point.applied / peak:.1f}"
        for index, point in enumerate(points)
    ]
    return "M" + " L".join(coords)


def format_range(start: datetime, end: datetime) -> str:
    """A range such as ``16 - 23 October 2026``; month and year repeat only where they differ."""
    dash = _EN_DASH
    if start.date() == end.date():
        return f"{end.day} {end:%B %Y}"
    if start.year != end.year:
        return f"{start.day} {start:%B %Y} {dash} {end.day} {end:%B %Y}"
    if start.month != end.month:
        return f"{start.day} {start:%B} {dash} {end.day} {end:%B %Y}"
    return f"{start.day} {dash} {end.day} {end:%B %Y}"


def as_of_stamp(moment: datetime) -> str:
    return f"As of {moment.astimezone(UTC):%H:%M} UTC"


def generated_stamp(moment: datetime) -> str:
    utc = moment.astimezone(UTC)
    return f"Generated {utc.day} {utc:%b %Y}, {utc:%H:%M} UTC"


def format_money(currency: str, amount: Decimal) -> str:
    """``USD 1,234.00``: 2 dp half-up, always with its currency."""
    return f"{currency} {amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def format_rate(rate: float | None) -> str:
    """A 0..1 rate as ``96.8%``; an unmeasured rate is a dash, never 0%."""
    if rate is None:
        return _DASH
    return f"{(Decimal(str(rate)) * _HUNDRED).quantize(_ONE_DP, rounding=ROUND_HALF_UP)}%"


def format_share(share: Decimal | None) -> str:
    if share is None:
        return _DASH
    return f"{(share * _HUNDRED).quantize(_ONE_DP, rounding=ROUND_HALF_UP)}%"


def _accuracy(accuracy: float | None, n: int) -> str:
    if accuracy is None or n == 0:
        return _DASH
    return f"{format_rate(accuracy)} · n {n}"


def _footnotes(figures: ReportFigures) -> list[str]:
    """Always present. Names only measured values; says plainly what was not measured."""
    notes: list[str] = []
    caveats = figures.caveats
    if ReportSection.MODEL_EFFICIENCY in figures.sections:
        if caveats.accuracy_n > 0:
            notes.append(
                f"Accuracy appears only for the {caveats.accuracy_n} items people corrected."
            )
        else:
            notes.append(
                "No items were corrected by people in this window, so accuracy is not shown."
            )
        if caveats.model_calls == 0:
            notes.append("No model calls in this window.")
        elif caveats.cost_unknown_share is None:
            notes.append("Model cost was not recorded for any call in this window.")
        else:
            share = format_share(caveats.cost_unknown_share)
            notes.append(f"Model cost excludes {share} of calls with no recorded cost.")
    else:
        notes.append("Money is shown per currency and is never summed across currencies.")
    notes.append("Rates show a dash where nothing could be measured.")
    return notes


def _view(figures: ReportFigures, generated_at: datetime) -> dict[str, Any]:
    summary = figures.summary
    awaiting = summary.awaiting_receipt
    peak = max((point.applied for point in figures.throughput), default=0)
    days = len(figures.throughput)
    return {
        "title": TITLE,
        "range_text": format_range(figures.start, figures.end),
        "generated_text": generated_stamp(generated_at),
        "as_of_text": as_of_stamp(figures.as_of),
        "as_of_value": f"{figures.as_of.astimezone(UTC):%H:%M} UTC",
        "sections": {section.value for section in figures.sections},
        "tiles": [
            {
                "label": "Receipts matched",
                "value": str(summary.receipts_matched),
                "note": "In this window",
            },
            {
                "label": "Automation rate",
                "value": format_rate(summary.automation_rate),
                "note": "No human touch" if summary.automation_rate is not None else "Not measured",
            },
            {
                "label": "Open exceptions",
                "value": str(summary.open_exceptions.total),
                "note": "Now",
            },
            {
                "label": "Awaiting receipt",
                "value": str(awaiting.count),
                "note": "Now"
                if awaiting.oldest_age_days is None
                else f"Oldest {awaiting.oldest_age_days}d of {awaiting.aging_limit_days}d",
            },
        ],
        "money_rows": [
            {
                "currency": row.currency,
                "applied": format_money(row.currency, row.amount),
                "receipts": str(row.receipts),
                "residual": format_money(row.currency, row.residual),
            }
            for row in figures.money
        ],
        "svg_path": throughput_path(figures.throughput),
        "svg_label": f"Items applied per day, {days} days, peak {peak} a day",
        "svg_width": SVG_WIDTH,
        "svg_height": SVG_HEIGHT,
        "svg_base": SVG_HEIGHT - _PAD,
        "peak": peak,
        "reason_rows": [
            {
                "code": row.error_code.value,
                "count": str(row.count),
                "fixed": format_rate(row.rate),
            }
            for row in figures.exceptions_by_reason
        ],
        "aging_rows": [{"label": row.label, "count": str(row.count)} for row in figures.aging],
        "show_aging": figures.kind is HtmlReportKind.EXCEPTIONS_AGING,
        "oldest_rows": [
            {
                "item": f"#{row.item_id}",
                "payer": row.payer if row.payer else _DASH,
                "amount": _DASH
                if row.amount is None or row.currency is None
                else format_money(row.currency, row.amount),
                "age": f"{row.age_days}d",
            }
            for row in figures.oldest_exceptions
        ],
        "model_rows": [
            {
                "role": row.role.value,
                "model": row.model_id,
                "calls": str(row.calls),
                "cost": "cluster" if row.cost_usd is None else format_money("USD", row.cost_usd),
                "cost_unknown": format_rate(row.cost_unknown_share),
                "agreement": format_rate(row.agreement_rate),
                "correction": format_rate(row.human_correction_rate),
                "accuracy": _accuracy(row.accuracy, row.accuracy_n),
            }
            for row in figures.models
        ],
        "footnotes": _footnotes(figures),
    }


def render_document(figures: ReportFigures, generated_at: datetime) -> str:
    """Pure: the same figures always give the same document."""
    return _ENV.get_template(TEMPLATE).render(**_view(figures, generated_at))


class HtmlReportRenderer:
    def __init__(
        self,
        *,
        metrics_factory: "Callable[[UnitOfWork], MetricsService]",
        exceptions: ExceptionsQueryService,
        clock: Clock,
    ) -> None:
        self._metrics_factory = metrics_factory
        self._exceptions = exceptions
        self._clock = clock

    async def render(
        self,
        uow: "UnitOfWork",
        principal: Principal,
        kind: HtmlReportKind,
        window: ReportWindow,
        sections: frozenset[ReportSection],
    ) -> RenderedReport:
        now = self._clock.now()
        figures = await gather_figures(
            uow,
            self._metrics_factory(uow),
            self._exceptions,
            principal,
            kind,
            window,
            sections,
            now,
        )
        html = render_document(figures, now)
        return RenderedReport(
            filename=report_filename(kind, window, now.astimezone(UTC).date()),
            html=html,
            bytes=len(html.encode("utf-8")),
            generated_at=now,
            has_data=figures.has_data,
        )
