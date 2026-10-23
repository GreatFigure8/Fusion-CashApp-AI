"""Queries over REPORT_EXPORT."""

from cashapp.data.models.report_export import ReportExport
from cashapp.data.repository import BaseRepository


class ReportExportRepository(BaseRepository[ReportExport]):
    model = ReportExport

    async def recent(self, limit: int) -> list[ReportExport]:
        """The latest exports, newest first."""
        page = await self.list(
            order_by=(ReportExport.at.desc(), ReportExport.id.desc()), offset=0, limit=limit
        )
        return page.items
