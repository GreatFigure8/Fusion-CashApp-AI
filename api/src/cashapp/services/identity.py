"""Turn validated token claims into a Principal. No framework imports."""

from cashapp.auth.tokens import Claims
from cashapp.data.repositories.group_roles import GroupRoleRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.principal import Principal


async def resolve_principal(uow: UnitOfWork, claims: Claims, *, groups_claim: str) -> Principal:
    """Claims -> groups -> roles (from the database mapping) -> Principal."""
    groups = claims.groups(groups_claim)
    roles = await uow.repo(GroupRoleRepository).roles_for_groups(groups)
    return Principal.from_roles(
        subject=claims.subject,
        display_name=claims.display_name,
        email=claims.email,
        groups=groups,
        roles=roles,
    )
