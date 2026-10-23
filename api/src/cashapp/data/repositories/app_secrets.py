"""Repository for secrets stored encrypted in the database."""

from sqlalchemy import select

from cashapp.data.models.app_secret import AppSecret
from cashapp.data.repository import BaseRepository


class AppSecretRepository(BaseRepository[AppSecret]):
    model = AppSecret

    async def by_name(self, name: str) -> AppSecret | None:
        return await self.session.get(AppSecret, name)

    async def by_name_for_update(self, name: str) -> AppSecret | None:
        stmt = (
            select(AppSecret)
            .where(AppSecret.name == name)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def all(self) -> list[AppSecret]:
        result = await self.session.execute(select(AppSecret).order_by(AppSecret.name))
        return list(result.scalars().all())
