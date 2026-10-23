"""Queries over PAYER_ALIAS. Flushes, never commits."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, or_, select, update

from cashapp.data.models.aliases import PayerAlias
from cashapp.data.repository import BaseRepository
from cashapp.domain.paging import Page

_KIND_COLUMNS = {
    "name": PayerAlias.payer_name_norm,
    "bank_account": PayerAlias.payer_bank_account,
    "reference": PayerAlias.reference_pattern,
}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class PayerAliasRepository(BaseRepository[PayerAlias]):
    model = PayerAlias

    async def _active_where(self, *conditions: ColumnElement[bool]) -> list[PayerAlias]:
        stmt = (
            select(PayerAlias)
            .where(PayerAlias.retired_at.is_(None), *conditions)
            .order_by(PayerAlias.id)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def active_by_name(self, name_norm: str) -> list[PayerAlias]:
        return await self._active_where(PayerAlias.payer_name_norm == name_norm)

    async def active_by_bank_account(self, account_norm: str) -> list[PayerAlias]:
        return await self._active_where(PayerAlias.payer_bank_account == account_norm)

    async def active_reference_aliases(self) -> list[PayerAlias]:
        return await self._active_where(PayerAlias.reference_pattern.is_not(None))

    async def active_for_key(self, kind: str, value: str) -> list[PayerAlias]:
        column = _KIND_COLUMNS.get(kind)
        if column is None:
            raise ValueError(f"unknown alias kind {kind!r}")
        return await self._active_where(column == value)

    async def get_many(self, ids: Sequence[int]) -> list[PayerAlias]:
        if not ids:
            return []
        stmt = select(PayerAlias).where(PayerAlias.id.in_(list(ids))).order_by(PayerAlias.id)
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def get_for_update(self, alias_id: int) -> PayerAlias | None:
        stmt = (
            select(PayerAlias)
            .where(PayerAlias.id == alias_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def mark_used(self, ids: Sequence[int], *, at: datetime) -> None:
        if not ids:
            return
        await self.session.execute(
            update(PayerAlias)
            .where(PayerAlias.id.in_(list(ids)))
            .values(uses=PayerAlias.uses + 1, last_used_at=at)
            .execution_options(synchronize_session="fetch")
        )
        await self.session.flush()

    async def search(
        self, *, active: bool | None, q: str | None, offset: int, limit: int
    ) -> Page[PayerAlias]:
        where: list[ColumnElement[bool]] = []
        if active is True:
            where.append(PayerAlias.retired_at.is_(None))
        elif active is False:
            where.append(PayerAlias.retired_at.is_not(None))
        needle = (q or "").strip().lower()
        if needle:
            pattern = f"%{_escape_like(needle)}%"
            where.append(
                or_(
                    *(
                        func.lower(column).like(pattern, escape="\\")
                        for column in (
                            PayerAlias.payer_name_norm,
                            PayerAlias.payer_bank_account,
                            PayerAlias.reference_pattern,
                            PayerAlias.customer_account_number,
                        )
                    )
                )
            )
        return await self.list(
            where=where,
            order_by=[PayerAlias.created_at.desc(), PayerAlias.id.desc()],
            offset=offset,
            limit=limit,
        )
