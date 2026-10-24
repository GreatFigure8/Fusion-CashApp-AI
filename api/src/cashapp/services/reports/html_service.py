"""Preview, export and re-download of HTML progress reports.

Nothing here touches ``Request`` or ``Response``. ``export`` flushes its log row and the caller
commits, so a render that fails never leaves a row behind. It imports no SQLAlchemy.
"""

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Final

from cashapp.data.models.report_export import ReportExport
from cashapp.data.repositories.report_exports import ReportExportRepository
from cashapp.domain.clock import Clock
from cashapp.domain.principal import Principal
from cashapp.domain.reports import SECTION_ORDER, HtmlReportKind, ReportSection, ReportWindow
from cashapp.services.config import ConfigSnapshot, RuntimeConfig
from cashapp.services.exceptions_query import ExceptionsQueryService
from cashapp.services.metrics.service import MetricsService
from cashapp.services.reports.html_export import HtmlReportRenderer, RenderedReport

if TYPE_CHECKING:
    from cashapp.data.uow import UnitOfWork

logger = logging.getLogger(__name__)

RENDER_TIMEOUT_S: Final = 20.0


class NothingToReport(Exception):  # noqa: N818 - pinned name
    """The window holds no completed item and no throughput, so there is nothing to export."""


class ExportNotFound(Exception):  # noqa: N818 - pinned name
    """No export row has this id."""


@dataclass(frozen=True, slots=True)
class ReportExportInfo:
    id: int
    kind: HtmlReportKind
    window: ReportWindow
    sections: tuple[ReportSection, ...]
    filename: str
    bytes: int
    actor: str
    actor_name: str
    at: datetime


def make_html_report_service(
    config: RuntimeConfig | ConfigSnapshot, clock: Clock
) -> "HtmlReportService":
    """The one wiring of the report service; the router and the chat tool both call it."""
    renderer = HtmlReportRenderer(
        metrics_factory=lambda uow: MetricsService(uow, clock=clock, config=config),
        exceptions=ExceptionsQueryService(config, clock),
        clock=clock,
    )
    return HtmlReportService(renderer)


def export_info(row: ReportExport) -> ReportExportInfo:
    return ReportExportInfo(
        id=row.id,
        kind=row.kind,
        window=ReportWindow(row.window),
        sections=tuple(ReportSection(name) for name in row.sections),
        filename=row.filename,
        bytes=row.bytes,
        actor=row.actor,
        actor_name=row.actor_name,
        at=row.at,
    )


def ordered(sections: frozenset[ReportSection]) -> tuple[ReportSection, ...]:
    """The sections in document order, which is also the order stored on the log row."""
    return tuple(section for section in SECTION_ORDER if section in sections)


class ReportFailed(Exception):  # noqa: N818 - pinned name
    """The figures could not be read or the document could not be rendered. Nothing was written."""


class HtmlReportService:
    def __init__(self, renderer: HtmlReportRenderer) -> None:
        self._renderer = renderer

    async def _render(
        self,
        uow: "UnitOfWork",
        principal: Principal,
        kind: HtmlReportKind,
        window: ReportWindow,
        sections: frozenset[ReportSection],
    ) -> RenderedReport:
        """One render path for preview, export and re-download, bounded by a timeout."""
        try:
            async with asyncio.timeout(RENDER_TIMEOUT_S):
                return await self._renderer.render(uow, principal, kind, window, sections)
        except Exception as exc:  # aggregate or database failure: report it, never half-write
            logger.exception("HTML report render failed (%s, %s)", kind, window)
            raise ReportFailed(type(exc).__name__) from exc

    async def preview(
        self,
        uow: "UnitOfWork",
        principal: Principal,
        kind: HtmlReportKind,
        window: ReportWindow,
        sections: frozenset[ReportSection],
    ) -> RenderedReport:
        return await self._render(uow, principal, kind, window, sections)

    async def export(
        self,
        uow: "UnitOfWork",
        principal: Principal,
        kind: HtmlReportKind,
        window: ReportWindow,
        sections: frozenset[ReportSection],
    ) -> tuple[RenderedReport, ReportExportInfo]:
        """Render, then log. Raises ``NothingToReport`` before anything is written."""
        report = await self._render(uow, principal, kind, window, sections)
        if not report.has_data:
            raise NothingToReport("No item finished in this window.")
        row = await uow.repo(ReportExportRepository).add(
            ReportExport(
                kind=kind,
                window=window.value,
                sections=[section.value for section in ordered(sections)],
                filename=report.filename,
                bytes=report.bytes,
                actor=principal.subject,
                actor_name=principal.display_name,
                at=report.generated_at,
            )
        )
        return report, export_info(row)

    async def recent(self, uow: "UnitOfWork", limit: int) -> list[ReportExportInfo]:
        rows = await uow.repo(ReportExportRepository).recent(limit)
        return [export_info(row) for row in rows]

    async def redownload(
        self, uow: "UnitOfWork", principal: Principal, export_id: int
    ) -> RenderedReport:
        """Re-render the stored kind, window and sections now, under the stored filename."""
        row = await uow.repo(ReportExportRepository).get(export_id)
        if row is None:
            raise ExportNotFound(str(export_id))
        info = export_info(row)
        report = await self._render(
            uow, principal, info.kind, info.window, frozenset(info.sections)
        )
        return replace(report, filename=info.filename)
