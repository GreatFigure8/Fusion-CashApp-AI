"""Response contract for GET /me."""

from pydantic import BaseModel

from cashapp.domain.principal import Permission, Principal, Role


class MeResponse(BaseModel):
    subject: str
    display_name: str
    email: str | None
    groups: list[str]
    roles: list[Role]
    permissions: list[Permission]

    @classmethod
    def from_principal(cls, principal: Principal) -> "MeResponse":
        return cls(
            subject=principal.subject,
            display_name=principal.display_name,
            email=principal.email,
            groups=sorted(principal.groups),
            roles=sorted(principal.roles),
            permissions=sorted(principal.permissions),
        )
