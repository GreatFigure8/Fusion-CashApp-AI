"""Group-to-role mapping changes: guarded against locking everyone out, and audited."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from cashapp.data.repositories.group_roles import GroupRoleRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock
from cashapp.domain.principal import GroupRoleAssignment, Permission, Principal, Role
from cashapp.services.config import (
    ConfigAudit,
    ConfigError,
    ConfigForbidden,
    ConfigValidationError,
    normalize_reason,
)

logger = logging.getLogger(__name__)

GROUP_ROLE_AUDIT_KEY = "access.group_role_map"
MAX_GROUP_NAME_LENGTH = 256


@dataclass(frozen=True, slots=True)
class GroupRoleInput:
    group_name: str
    role: Role


class LastAdminMappingRemoved(ConfigError):  # noqa: N818
    """The replacement would leave no group mapped to ADMIN."""

    def __init__(self) -> None:
        super().__init__("At least one group must stay mapped to the ADMIN role")


def _as_json(mappings: Sequence[GroupRoleInput]) -> JsonValue:
    return [{"group_name": m.group_name, "role": m.role.value} for m in mappings]


class GroupRoleService:
    async def current(self, uow: UnitOfWork) -> list[GroupRoleInput]:
        result: list[GroupRoleInput] = []
        for row in await uow.repo(GroupRoleRepository).all():
            try:
                result.append(GroupRoleInput(row.group_name, Role(row.role)))
            except ValueError:
                logger.warning("Skipping group mapping with unknown role %r", row.role)
        return sorted(result, key=lambda m: (m.group_name, m.role.value))

    async def replace(
        self,
        uow: UnitOfWork,
        mappings: Sequence[GroupRoleInput],
        principal: Principal,
        reason: str,
    ) -> list[GroupRoleInput]:
        """Replace the whole mapping and audit it, in the caller's transaction."""
        if not principal.can(Permission.CONFIG_WRITE):
            raise ConfigForbidden("Missing permission config:write")
        cleaned_reason = normalize_reason(GROUP_ROLE_AUDIT_KEY, reason)
        unique: dict[tuple[str, str], GroupRoleInput] = {}
        for mapping in mappings:
            name = mapping.group_name.strip()
            if not name or len(name) > MAX_GROUP_NAME_LENGTH:
                raise ConfigValidationError(
                    GROUP_ROLE_AUDIT_KEY,
                    [
                        {
                            "loc": ["mappings", "group_name"],
                            "msg": "Group name must be 1 to 256 characters",
                        }
                    ],
                )
            unique[(name, mapping.role.value)] = GroupRoleInput(name, mapping.role)
        ordered = [unique[k] for k in sorted(unique)]
        if not any(m.role is Role.ADMIN for m in ordered):
            raise LastAdminMappingRemoved

        old = await self.current(uow)
        await uow.repo(GroupRoleRepository).replace_all(
            [GroupRoleAssignment(m.group_name, m.role) for m in ordered],
            created_by=principal.subject,
        )
        await ConfigAudit.record(
            uow,
            GROUP_ROLE_AUDIT_KEY,
            _as_json(old),
            _as_json(ordered),
            principal,
            cleaned_reason,
            clock=self._clock,
        )
        return ordered

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock
