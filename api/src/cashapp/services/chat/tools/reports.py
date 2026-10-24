"""Chat tool ``reports.export``: build the HTML progress report and hand back a file card.

It calls the same ``HtmlReportService.export`` as the router, so the log row and the document are
identical whichever way the export was asked for.
"""

from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field

from cashapp.domain.principal import Permission
from cashapp.domain.reports import DEFAULT_SECTIONS, HtmlReportKind, ReportSection, ReportWindow
from cashapp.services.chat.tools.cards import ExportCard
from cashapp.services.chat.tools.registry import ToolContext, ToolError, ToolGroup, ToolSpec
from cashapp.services.config import RuntimeConfig
from cashapp.services.reports.html_service import (
    NothingToReport,
    ReportFailed,
    make_html_report_service,
    ordered,
)


class ReportsExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: HtmlReportKind = Field(
        default=HtmlReportKind.PROGRESS_SUMMARY,
        description="Which report: PROGRESS_SUMMARY, EXCEPTIONS_AGING or MODEL_EFFICIENCY.",
    )
    window: ReportWindow = Field(
        default=ReportWindow.D7, description="The period: 7d, 30d or mtd (month to date)."
    )
    sections: list[ReportSection] | None = Field(
        default=None,
        min_length=1,
        description="Sections to include. Leave out to use the report kind's defaults.",
    )


def preview_href(
    kind: HtmlReportKind, window: ReportWindow, sections: tuple[ReportSection, ...]
) -> str:
    """The Reports page URL that pre-fills the builder with this report."""
    query = urlencode(
        [("kind", kind.value), ("window", window.value), *(("sections", s.value) for s in sections)]
    )
    return f"/reports?{query}"


async def export_report(ctx: ToolContext, args: ReportsExportInput) -> ExportCard:
    sections = frozenset(args.sections) if args.sections else DEFAULT_SECTIONS[args.kind]
    config = await ctx.services.get(RuntimeConfig)
    service = make_html_report_service(config, ctx.clock)
    try:
        async with ctx.uow_factory() as uow:
            report, info = await service.export(
                uow, ctx.principal, args.kind, args.window, sections
            )
            await uow.commit()
    except NothingToReport as exc:
        raise ToolError(
            "NOTHING_TO_REPORT",
            "No item finished in this window, so there is nothing to export.",
            422,
        ) from exc
    except ReportFailed as exc:
        raise ToolError(
            "REPORT_FAILED", "The export didn't finish. No file was created.", 503
        ) from exc
    return ExportCard(
        filename=report.filename,
        size_bytes=report.bytes,
        self_contained=True,
        preview_href=preview_href(args.kind, args.window, ordered(sections)),
        download_href=f"/api/reports/html/exports/{info.id}",
    )


TOOLS: list[ToolSpec[Any, Any]] = [
    ToolSpec(
        name="reports.export",
        group=ToolGroup.REPORTS,
        description=(
            "Build a cash application progress report as one self-contained HTML file and log "
            "the export. Returns the file name, its size and links to preview and download it."
        ),
        input_model=ReportsExportInput,
        output_model=ExportCard,
        permission=Permission.REPORTS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Export HTML report",
        handler=export_report,
        preview=None,
        card=lambda out: out,
    )
]
