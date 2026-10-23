"""Queries over GROUP_ROLE_MAPPING. Flushes, never commits."""

import logging
from collections.abc import Iterable, Sequence

from sqlalchemy import delete, select

from cashapp.data.models.group_role import GroupRoleMapping
from cashapp.data.repository import BaseRepository
from cashapp.domain.principal import GroupRoleAssignment, Role

logger = logging.getLogger(__name__)


class GroupRoleRepository(BaseRepository[GroupRoleMapping]):
    model = GroupRoleMapping

    async def roles_for_groups(self, groups: Iterable[str]) -> frozenset[Role]:
        """Roles granted to any of the groups (exact, case-sensitive match)."""
        names = set(groups)
        if not names:
            return frozenset()
        result = await self.session.scalars(
            select(GroupRoleMapping.role).where(GroupRoleMapping.group_name.in_(names)).distinct()
        )
        roles: set[Role] = set()
        for value in result:
            try:
                roles.add(Role(value))
            except ValueError:
                logger.warning("unknown role value in GROUP_ROLE_MAPPING", extra={"role": value})
        return frozenset(roles)

    async def all(self) -> list[GroupRoleMapping]:
        result = await self.session.scalars(
            select(GroupRoleMapping).order_by(GroupRoleMapping.group_name, GroupRoleMapping.role)
        )
        return list(result)

    async def replace_all(
        self, mappings: Sequence[GroupRoleAssignment], *, created_by: str
    ) -> None:
        """Delete every row and insert the deduplicated set. The last-ADMIN rule is s28's."""
        await self.session.execute(delete(GroupRoleMapping))
        unique = dict.fromkeys((m.group_name, m.role) for m in mappings)
        self.session.add_all(
            GroupRoleMapping(group_name=group, role=role.value, created_by=created_by)
            for group, role in unique
        )
        await self.session.flush()
