"""Operations reports: the daily summary and the partially paid invoices report."""

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.schemas.reports import (
    DailySummaryResponse,
    EmailRequest,
    EmailResponse,
    GenerateRequest,
    PartiallyPaidResponse,
)
from cashapp.auth.deps import require_permission
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.principal import Permission, Principal
from cashapp.services.reports.export import (
    ExportFormat,
    daily_summary_file,
    partially_paid_file,
)
from cashapp.services.reports.partially_paid import partially_paid
from cashapp.services.reports.service import (
    FutureReportDate,
    NoRecipients,
    ReportEmailFailed,
    ReportService,
)

router = APIRouter(prefix="/reports", tags=["reports"], responses=ERROR_RESPONSES)

ReportsDep = Annotated[Principal, Depends(require_permission(Permission.REPORTS_READ))]

MAX_RANGE_DAYS = 366

ReportFormat = Literal["json", "csv", "xlsx"]


def get_clock() -> Clock:
    """The clock reports use for 'yesterday' and 'not in the future'. Override in tests."""
    return SystemClock()


ClockDep = Annotated[Clock, Depends(get_clock)]


def _yesterday(clock: Clock) -> dt.date:
    return clock.now().date() - dt.timedelta(days=1)


def _file(name: str, content: bytes, content_type: str) -> Response:
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _future(exc: FutureReportDate) -> ApiError:
    return ApiError(422, "invalid_date", str(exc))


@router.get("/daily-summary", response_model=DailySummaryResponse)
async def get_daily_summary(
    _: ReportsDep,
    uow_factory: UowFactoryDep,
    runtime: RuntimeConfigDep,
    clock: ClockDep,
    date: dt.date | None = None,
    format: ReportFormat = "json",
) -> DailySummaryResponse | Response:
    day = date or _yesterday(clock)
    try:
        async with uow_factory() as uow:
            summary, info = await ReportService(clock=clock).get_daily(uow, day)
    except FutureReportDate as exc:
        raise _future(exc) from exc
    if format != "json":
        export_format: ExportFormat = "csv" if format == "csv" else "xlsx"
        return _file(*daily_summary_file(summary, export_format))
    cutover = (await runtime.snapshot()).reports().daily_summary_cutover
    return DailySummaryResponse.of(summary, info, cutover)


@router.post("/daily-summary/generate", response_model=DailySummaryResponse)
async def generate_daily_summary(
    body: GenerateRequest,
    principal: ReportsDep,
    uow_factory: UowFactoryDep,
    runtime: RuntimeConfigDep,
    clock: ClockDep,
) -> DailySummaryResponse:
    try:
        async with uow_factory() as uow:
            summary, info = await ReportService(clock=clock).generate_daily(
                uow, body.date, principal
            )
            await uow.commit()
    except FutureReportDate as exc:
        raise _future(exc) from exc
    cutover = (await runtime.snapshot()).reports().daily_summary_cutover
    return DailySummaryResponse.of(summary, info, cutover)


@router.post("/daily-summary/email", response_model=EmailResponse)
async def email_daily_summary(
    body: EmailRequest,
    principal: ReportsDep,
    uow_factory: UowFactoryDep,
    runtime: RuntimeConfigDep,
    clock: ClockDep,
) -> EmailResponse:
    config = await runtime.snapshot()
    try:
        async with uow_factory() as uow:
            info = await ReportService(clock=clock).email_daily(
                uow, body.date, body.recipients, principal, config
            )
            await uow.commit()
    except FutureReportDate as exc:
        raise _future(exc) from exc
    except NoRecipients as exc:
        raise ApiError(
            422, "no_recipients", "No recipients were given and none are configured."
        ) from exc
    except ReportEmailFailed as exc:
        raise ApiError(
            502,
            "report_email_failed",
            "The report could not be emailed.",
            details=[{"reason": exc.reason}],
        ) from exc
    if info.emailed_at is None:  # unreachable: a successful send always stamps the run
        raise ApiError(500, "internal_error", "The email was not recorded.")
    return EmailResponse(
        date=body.date, emailed_to=list(info.emailed_to), emailed_at=info.emailed_at
    )


@router.get("/partially-paid", response_model=PartiallyPaidResponse)
async def get_partially_paid(
    _: ReportsDep,
    uow_factory: UowFactoryDep,
    clock: ClockDep,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: dt.date | None = None,
    format: ReportFormat = "json",
) -> PartiallyPaidResponse | Response:
    first = from_ or _yesterday(clock)
    last = to or _yesterday(clock)
    if first > last:
        raise ApiError(422, "invalid_range", "'from' must not be after 'to'")
    if (last - first).days + 1 > MAX_RANGE_DAYS:
        raise ApiError(
            422, "invalid_range", f"The range must not be longer than {MAX_RANGE_DAYS} days"
        )
    if last > clock.now().date():
        raise ApiError(422, "invalid_date", f"{last.isoformat()} is in the future")
    async with uow_factory() as uow:
        rows, truncated = await partially_paid(uow, first, last)
    if format != "json":
        export_format: ExportFormat = "csv" if format == "csv" else "xlsx"
        return _file(*partially_paid_file(rows, first, last, export_format))
    return PartiallyPaidResponse.of(first, last, rows, truncated)
