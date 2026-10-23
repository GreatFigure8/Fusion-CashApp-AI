"""Queries over CUSTOMER_RESOLUTION. Flushes, never commits."""

from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import select

from cashapp.data.models.customer_resolution import CustomerResolutionRow
from cashapp.data.repository import BaseRepository
from cashapp.domain.customer import (
    CurrencySource,
    CustomerResolution,
    finding_from_json,
    finding_to_json,
    transaction_from_json,
    transaction_to_json,
)
from cashapp.domain.status import InfoFlag

_IN_CHUNK = 500  # Oracle allows at most 1000 items in an IN list


def _to_domain(row: CustomerResolutionRow) -> CustomerResolution:
    return CustomerResolution(
        anchor_customer_number=row.anchor_customer_number,
        related_customer_numbers=tuple(row.related_customer_numbers),
        method=row.method,
        alias_ids=tuple(int(i) for i in row.alias_ids),
        transactions=[transaction_from_json(t) for t in row.transactions],
        currency=row.currency,
        flags={InfoFlag(f) for f in row.flags},
        anchor_line_no=row.anchor_line_no,
        currency_source=cast("CurrencySource | None", row.currency_source),
        line_findings=tuple(finding_from_json(f) for f in row.line_findings),
    )


class CustomerResolutionRepository(BaseRepository[CustomerResolutionRow]):
    model = CustomerResolutionRow

    async def add_resolution(
        self, item_id: int, resolution: CustomerResolution, *, now: datetime
    ) -> CustomerResolutionRow:
        return await self.add(
            CustomerResolutionRow(
                work_item_id=item_id,
                anchor_customer_number=resolution.anchor_customer_number,
                related_customer_numbers=list(resolution.related_customer_numbers),
                method=resolution.method,
                alias_ids=list(resolution.alias_ids),
                currency=resolution.currency,
                transactions=[transaction_to_json(t) for t in resolution.transactions],
                flags=sorted(f.value for f in resolution.flags),
                line_findings=[finding_to_json(f) for f in resolution.line_findings],
                anchor_line_no=resolution.anchor_line_no,
                currency_source=resolution.currency_source,
                created_at=now,
            )
        )

    async def latest_row_for(self, item_id: int) -> CustomerResolutionRow | None:
        stmt = (
            select(CustomerResolutionRow)
            .where(CustomerResolutionRow.work_item_id == item_id)
            .order_by(CustomerResolutionRow.created_at.desc(), CustomerResolutionRow.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def latest_for(self, item_id: int) -> CustomerResolution | None:
        """The accessor later stations use."""
        row = await self.latest_row_for(item_id)
        return _to_domain(row) if row is not None else None

    async def latest_for_items(self, item_ids: Sequence[int]) -> dict[int, CustomerResolution]:
        """The newest resolution per item, in chunks (no SQL JSON predicates)."""
        newest: dict[int, CustomerResolutionRow] = {}
        for start in range(0, len(item_ids), _IN_CHUNK):
            chunk = list(item_ids[start : start + _IN_CHUNK])
            stmt = (
                select(CustomerResolutionRow)
                .where(CustomerResolutionRow.work_item_id.in_(chunk))
                .order_by(CustomerResolutionRow.created_at, CustomerResolutionRow.id)
            )
            for row in (await self.session.execute(stmt)).scalars():
                newest[row.work_item_id] = row  # ascending order: the last row per item wins
        return {item_id: _to_domain(row) for item_id, row in newest.items()}
