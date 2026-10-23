"""Repositories for the runtime configuration store and its change log."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from cashapp.data.models.config import ConfigChange, ConfigSetting
from cashapp.data.repository import BaseRepository
from cashapp.domain.paging import Page


class DuplicateConfigKeyError(Exception):
    """A concurrent writer inserted the same first-time key."""


class ConfigSettingRepository(BaseRepository[ConfigSetting]):
    model = ConfigSetting

    async def all(self) -> list[ConfigSetting]:
        result = await self.session.execute(select(ConfigSetting).order_by(ConfigSetting.key))
        return list(result.scalars().all())

    async def get_for_update(self, key: str) -> ConfigSetting | None:
        """Lock the row for the rest of the transaction (locks nothing if it does not exist)."""
        stmt = (
            select(ConfigSetting)
            .where(ConfigSetting.key == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def insert_new(self, setting: ConfigSetting) -> ConfigSetting:
        """Insert a first-time key; a primary-key clash raises DuplicateConfigKeyError.

        The insert runs in a savepoint so the caller's transaction stays usable.
        """
        try:
            async with self.session.begin_nested():
                self.session.add(setting)
                await self.session.flush()
        except IntegrityError as exc:
            raise DuplicateConfigKeyError(setting.key) from exc
        return setting


class ConfigChangeRepository(BaseRepository[ConfigChange]):
    model = ConfigChange

    async def history(self, key: str, offset: int = 0, limit: int = 50) -> Page[ConfigChange]:
        """Change rows for one key, newest first."""
        return await self.list(
            where=[ConfigChange.key == key],
            order_by=[ConfigChange.changed_at.desc(), ConfigChange.id.desc()],
            offset=offset,
            limit=limit,
        )

    async def history_all(self, offset: int = 0, limit: int = 50) -> Page[ConfigChange]:
        """Change rows across every key, newest first."""
        return await self.list(
            order_by=[ConfigChange.changed_at.desc(), ConfigChange.id.desc()],
            offset=offset,
            limit=limit,
        )

    async def latest_by_key(self, keys: Sequence[str]) -> dict[str, ConfigChange]:
        """The most recent change row for each of `keys` that has one."""
        if not keys:
            return {}
        newest = (
            select(func.max(ConfigChange.id))
            .where(ConfigChange.key.in_(list(keys)))
            .group_by(ConfigChange.key)
        )
        result = await self.session.execute(select(ConfigChange).where(ConfigChange.id.in_(newest)))
        return {row.key: row for row in result.scalars().all()}
