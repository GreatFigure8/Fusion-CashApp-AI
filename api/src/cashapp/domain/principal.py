"""Who is acting, and what they may do. Pure: no I/O, no framework imports."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Self


class Role(StrEnum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    REVERSER = "REVERSER"
    VIEWER = "VIEWER"


class Permission(StrEnum):
    ITEMS_READ = "items:read"
    ITEMS_WORK = "items:work"
    APPLY_REVERSE = "apply:reverse"
    CLASSIFICATION_OVERRIDE = "classification:override"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    REPORTS_READ = "reports:read"
    BACKLOG_RUN = "backlog:run"
    CHAT_USE = "chat:use"


ROLE_PERMISSIONS: Final[Mapping[Role, frozenset[Permission]]] = MappingProxyType(
    {
        Role.ADMIN: frozenset(Permission),
        Role.OPERATOR: frozenset(
            {
                Permission.ITEMS_READ,
                Permission.ITEMS_WORK,
                Permission.CLASSIFICATION_OVERRIDE,
                Permission.REPORTS_READ,
                Permission.CHAT_USE,
                Permission.CONFIG_READ,
            }
        ),
        Role.REVERSER: frozenset({Permission.APPLY_REVERSE}),
        Role.VIEWER: frozenset(
            {Permission.ITEMS_READ, Permission.REPORTS_READ, Permission.CONFIG_READ}
        ),
    }
)


def permissions_for(roles: Iterable[Role]) -> frozenset[Permission]:
    """The union of the permissions of every given role."""
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    display_name: str
    email: str | None
    groups: frozenset[str]
    roles: frozenset[Role]
    permissions: frozenset[Permission]
    is_system: bool = False

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    @classmethod
    def from_roles(
        cls,
        *,
        subject: str,
        display_name: str,
        email: str | None,
        groups: Iterable[str],
        roles: Iterable[Role],
    ) -> Self:
        role_set = frozenset(roles)
        return cls(
            subject=subject,
            display_name=display_name,
            email=email,
            groups=frozenset(groups),
            roles=role_set,
            permissions=permissions_for(role_set),
        )


@dataclass(frozen=True, slots=True)
class GroupRoleAssignment:
    group_name: str
    role: Role


SYSTEM_PRINCIPAL: Final[Principal] = Principal(
    subject="system:pipeline",
    display_name="Pipeline",
    email=None,
    groups=frozenset(),
    roles=frozenset(),
    permissions=frozenset(Permission) - {Permission.APPLY_REVERSE, Permission.CONFIG_WRITE},
    is_system=True,
)
