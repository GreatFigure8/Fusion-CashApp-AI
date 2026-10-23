"""API contracts for the flow monitor: the summary, its tiles, stage tables and stream frames."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, Field

from cashapp.api.schemas.locks import LockInfoOut
from cashapp.data.models.work_item import WorkItem
from cashapp.domain.money import CurrencyCode, MoneyStr
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import PaymentStatus
from cashapp.services.flow_query import (
    BacklogData,
    FlowSummaryData,
    FlowTile,
    ItemChangedData,
    KpiData,
    PollerData,
    TileData,
)
from cashapp.services.locking import LockInfo


class AppliedMoneyOut(BaseModel):
    currency: CurrencyCode
    amount: MoneyStr


class FlowKpisOut(BaseModel):
    in_today: int
    auto_applied_pct: float | None
    applied_by_currency: list[AppliedMoneyOut]
    needs_person: int

    @classmethod
    def from_data(cls, data: KpiData) -> Self:
        return cls(
            in_today=data.in_today,
            auto_applied_pct=data.auto_applied_pct,
            applied_by_currency=[
                AppliedMoneyOut(currency=m.currency, amount=m.amount)
                for m in data.applied_by_currency
            ],
            needs_person=data.needs_person,
        )


class AwaitingBucketsOut(BaseModel):
    """Awaiting-receipt items by whole days waited."""

    d0_2: Annotated[int, Field(alias="0-2d")]
    d3_7: Annotated[int, Field(alias="3-7d")]
    d8_30: Annotated[int, Field(alias="8-30d")]
    d30_plus: Annotated[int, Field(alias=">30d")]

    model_config = {"populate_by_name": True}


class FlowTileOut(BaseModel):
    stage: FlowTile
    in_queue: int
    in_progress: int
    errors: int
    throughput_per_min: Annotated[list[int], Field(min_length=60, max_length=60)]
    p95_dwell_s: float | None
    awaiting_buckets: AwaitingBucketsOut | None

    @classmethod
    def from_data(cls, data: TileData) -> Self:
        buckets = data.awaiting_buckets
        return cls(
            stage=data.tile,
            in_queue=data.in_queue,
            in_progress=data.in_progress,
            errors=data.errors,
            throughput_per_min=list(data.throughput_per_min),
            p95_dwell_s=data.p95_dwell_s,
            awaiting_buckets=None
            if buckets is None
            else AwaitingBucketsOut.model_validate(dict(buckets)),
        )


class PollerOut(BaseModel):
    name: str
    last_cycle_at: datetime | None

    @classmethod
    def from_data(cls, data: PollerData) -> Self:
        return cls(name=data.name, last_cycle_at=data.last_cycle_at)


class BacklogProgressOut(BaseModel):
    id: int
    name: str
    processed: int
    total: int
    eta_minutes: int | None
    status: str

    @classmethod
    def from_data(cls, data: BacklogData) -> Self:
        return cls(
            id=data.id,
            name=data.name,
            processed=data.processed,
            total=data.total,
            eta_minutes=data.eta_minutes,
            status=data.status,
        )


class FlowSummaryOut(BaseModel):
    kpis: FlowKpisOut
    stages: list[FlowTileOut]
    pollers: list[PollerOut]
    cohere_utilisation_pct: float | None
    backlog: list[BacklogProgressOut]
    generated_at: datetime

    @classmethod
    def from_data(cls, data: FlowSummaryData) -> Self:
        return cls(
            kpis=FlowKpisOut.from_data(data.kpis),
            stages=[FlowTileOut.from_data(t) for t in data.stages],
            pollers=[PollerOut.from_data(p) for p in data.pollers],
            cohere_utilisation_pct=data.cohere_utilisation_pct,
            backlog=[BacklogProgressOut.from_data(b) for b in data.backlog],
            generated_at=data.generated_at,
        )


class ItemChangedOut(BaseModel):
    id: int
    stage: Stage
    state: ItemState
    lock: LockInfoOut | None
    payment_status: PaymentStatus | None
    updated_at: datetime

    @classmethod
    def from_data(cls, data: ItemChangedData) -> Self:
        return cls(
            id=data.id,
            stage=data.stage,
            state=data.state,
            lock=LockInfoOut.from_info(data.lock),
            payment_status=data.payment_status,
            updated_at=data.updated_at,
        )


class FlowStreamFrameOut(BaseModel):
    """Documents the two SSE event payloads (``summary`` and ``item_changed``) for OpenAPI."""

    summary: FlowSummaryOut | None = None
    item_changed: ItemChangedOut | None = None


class StageItemOut(BaseModel):
    id: int
    payer_name: str | None
    amount: MoneyStr | None
    currency: CurrencyCode | None
    received_at: datetime
    attempts: int
    stage: Stage
    state: ItemState
    payment_status: PaymentStatus | None
    lock: LockInfoOut | None

    @classmethod
    def from_data(cls, item: WorkItem, lock: LockInfo | None) -> Self:
        return cls(
            id=item.id,
            payer_name=item.payer_name,
            amount=item.payment_amount,
            currency=item.currency,
            received_at=item.created_at,
            attempts=item.attempts,
            stage=item.stage,
            state=item.state,
            payment_status=item.payment_status,
            lock=LockInfoOut.from_info(lock),
        )


class StageItemsOut(BaseModel):
    items: list[StageItemOut]
    total: int
    page: int
    page_size: int

    @classmethod
    def from_data(
        cls, rows: list[tuple[WorkItem, LockInfo | None]], *, total: int, page: int, page_size: int
    ) -> Self:
        return cls(
            items=[StageItemOut.from_data(item, lock) for item, lock in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
