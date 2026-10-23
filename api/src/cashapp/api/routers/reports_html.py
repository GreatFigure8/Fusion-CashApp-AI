"""HTML progress reports: a live preview, a download, and the log of what was exported."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.routers.reports import ClockDep, ReportsDep
from cashapp.api.schemas.reports import (
    HtmlExportRequest,
    ReportExportOut,
    ReportExportsResponse,
)
from cashapp.domain.reports import HtmlReportKind, ReportSection, ReportWindow
from cashapp.services.reports.html_export import RenderedReport
from cashapp.services.reports.html_service import (
    ExportNotFound,
    NothingToReport,
    ReportFailed,
    make_html_report_service,
)

router = APIRouter(prefix="/reports/html", tags=["reports"], responses=ERROR_RESPONSES)

DEFAULT_EXPORTS_LIMIT = 10
MAX_EXPORTS_LIMIT = 50

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"
    ),
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
}


def _html(report: RenderedReport, *, attachment: bool) -> Response:
    headers = {**_SECURITY_HEADERS, "X-Report-Has-Data": "true" if report.has_data else "false"}
    if attachment:
        headers["Content-Disposition"] = f'attachment; filename="{report.filename}"'
    return Response(content=report.html, media_type="text/html; charset=utf-8", headers=headers)


def _failed() -> ApiError:
    return ApiError(503, "report_failed", "The export didn't finish. No file was created.")


@router.get("/preview", response_class=Response, responses={200: {"content": {"text/html": {}}}})
async def preview_html_report(
    principal: ReportsDep,
    uow_factory: UowFactoryDep,
    runtime: RuntimeConfigDep,
    clock: ClockDep,
    kind: HtmlReportKind,
    window: ReportWindow,
    sections: Annotated[list[ReportSection], Query(min_length=1, max_length=len(ReportSection))],
) -> Response:
    service = make_html_report_service(runtime, clock)
    try:
        async with uow_factory() as uow:
            report = await service.preview(uow, principal, kind, window, frozenset(sections))
    except ReportFailed as exc:
        raise _failed() from exc
    return _html(report, attachment=False)


@router.post("/export", response_class=Response, responses={200: {"content": {"text/html": {}}}})
async def export_html_report(
    body: HtmlExportRequest,
    principal: ReportsDep,
    uow_factory: UowFactoryDep,
    runtime: RuntimeConfigDep,
    clock: ClockDep,
) -> Response:
    service = make_html_report_service(runtime, clock)
    try:
        async with uow_factory() as uow:
            report, _ = await service.export(
                uow, principal, body.kind, body.window, frozenset(body.sections)
            )
            await uow.commit()
    except NothingToReport as exc:
        raise ApiError(
            422, "nothing_to_report", "No item finished in this window. Nothing to export."
        ) from exc
    except ReportFailed as exc:
        raise _failed() from exc
    return _html(report, attachment=True)


@router.get("/exports", response_model=ReportExportsResponse)
async def list_html_exports(
    _: ReportsDep,
    uow_factory: UowFactoryDep,
    runtime: RuntimeConfigDep,
    clock: ClockDep,
    limit: Annotated[int, Query(ge=1, le=MAX_EXPORTS_LIMIT)] = DEFAULT_EXPORTS_LIMIT,
) -> ReportExportsResponse:
    service = make_html_report_service(runtime, clock)
    async with uow_factory() as uow:
        infos = await service.recent(uow, limit)
    return ReportExportsResponse(data=[ReportExportOut.of(info) for info in infos])


@router.get(
    "/exports/{export_id}/file",
    response_class=Response,
    responses={200: {"content": {"text/html": {}}}},
)
async def download_html_export(
    export_id: int,
    principal: ReportsDep,
    uow_factory: UowFactoryDep,
    runtime: RuntimeConfigDep,
    clock: ClockDep,
) -> Response:
    service = make_html_report_service(runtime, clock)
    try:
        async with uow_factory() as uow:
            report = await service.redownload(uow, principal, export_id)
    except ExportNotFound as exc:
        raise ApiError(404, "not_found", "That export does not exist.") from exc
    except ReportFailed as exc:
        raise _failed() from exc
    return _html(report, attachment=True)
