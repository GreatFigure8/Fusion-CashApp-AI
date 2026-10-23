"""Operations reports: the daily summary and the partially paid invoices report.

The intake-cycle hook is registered from ``cashapp.pollers.intake.hooks``, not here: this package is
not a role package, so importing it must have no side effects.
"""

from cashapp.services.reports.daily_summary import daily_summary
from cashapp.services.reports.html_export import HtmlReportRenderer, RenderedReport
from cashapp.services.reports.html_service import (
    ExportNotFound,
    HtmlReportService,
    NothingToReport,
    ReportExportInfo,
    ReportFailed,
    make_html_report_service,
)
from cashapp.services.reports.models import (
    AgingBucketCount,
    CurrencyAmount,
    DailySummary,
    ErrorCodeCount,
    PartiallyPaidRow,
    ReportRunInfo,
)
from cashapp.services.reports.partially_paid import partially_paid
from cashapp.services.reports.service import (
    FutureReportDate,
    NoRecipients,
    ReportEmailFailed,
    ReportService,
)

__all__ = [
    "AgingBucketCount",
    "CurrencyAmount",
    "DailySummary",
    "ErrorCodeCount",
    "ExportNotFound",
    "FutureReportDate",
    "HtmlReportRenderer",
    "HtmlReportService",
    "NoRecipients",
    "NothingToReport",
    "PartiallyPaidRow",
    "RenderedReport",
    "ReportEmailFailed",
    "ReportExportInfo",
    "ReportFailed",
    "ReportRunInfo",
    "ReportService",
    "daily_summary",
    "make_html_report_service",
    "partially_paid",
]
