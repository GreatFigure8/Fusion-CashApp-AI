"""LLM usage and cost endpoints: daily totals, one item's calls, Cohere utilisation."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.api.schemas.llm_usage import CohereUtilisationOut, DailyUsageOut, UsageCallOut
from cashapp.auth.deps import require_permission
from cashapp.domain.llm_usage import UsageGroupBy
from cashapp.domain.principal import Permission, Principal
from cashapp.integrations.llm.cluster_metrics import ClusterMetrics, build_cluster_metrics
from cashapp.services.llm_usage.reporting import cohere_utilisation, daily_usage, item_usage

router = APIRouter(prefix="/llm-usage", tags=["llm-usage"], responses=ERROR_RESPONSES)

ReportsDep = Annotated[Principal, Depends(require_permission(Permission.REPORTS_READ))]
ItemsReadDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_READ))]

_DEFAULT_DAYS = 7
_MAX_RANGE_DAYS = 366


async def get_cluster_metrics(runtime: RuntimeSettingsDep) -> ClusterMetrics | None:
    """The cluster metrics source (its keys are hot); tests override this dependency."""
    return await build_cluster_metrics(runtime)


ClusterDep = Annotated[ClusterMetrics | None, Depends(get_cluster_metrics)]


@router.get("/daily", response_model=list[DailyUsageOut])
async def get_daily_usage(
    _: ReportsDep,
    uow_factory: UowFactoryDep,
    from_day: Annotated[date | None, Query(alias="from")] = None,
    to_day: Annotated[date | None, Query(alias="to")] = None,
    group_by: UsageGroupBy = UsageGroupBy.STATION,
) -> list[DailyUsageOut]:
    end = to_day if to_day is not None else datetime.now(UTC).date()
    start = from_day if from_day is not None else end - timedelta(days=_DEFAULT_DAYS - 1)
    if start > end:
        raise ApiError(422, "invalid_range", "'from' must not be after 'to'")
    if (end - start).days >= _MAX_RANGE_DAYS:
        raise ApiError(422, "invalid_range", f"The range may span at most {_MAX_RANGE_DAYS} days")
    async with uow_factory() as uow:
        rows = await daily_usage(uow, from_day=start, to_day=end, group_by=group_by)
    return [DailyUsageOut.of(row) for row in rows]


@router.get("/items/{item_id}", response_model=list[UsageCallOut])
async def get_item_usage(
    item_id: int, _: ReportsDep, uow_factory: UowFactoryDep
) -> list[UsageCallOut]:
    async with uow_factory() as uow:
        if await uow.work_items.get(item_id) is None:
            raise ApiError(404, "work_item_not_found", f"Work item {item_id} not found")
        calls = await item_usage(uow, item_id)
    return [UsageCallOut.of(call) for call in calls]


@router.get("/cohere-utilisation", response_model=CohereUtilisationOut)
async def get_cohere_utilisation(
    _: ItemsReadDep,
    uow_factory: UowFactoryDep,
    cluster: ClusterDep,
    window_minutes: Annotated[int, Query(ge=1, le=1440)] = 60,
) -> CohereUtilisationOut:
    async with uow_factory() as uow:
        result = await cohere_utilisation(uow, window_minutes=window_minutes, cluster=cluster)
    return CohereUtilisationOut.of(result)
