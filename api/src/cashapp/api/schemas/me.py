"""Response contract for GET /me."""

from pydantic import BaseModel

from cashapp.domain.principal import Permission, Principal, Role
from cashapp.services.ui_context import UiContext
from cashapp.settings import Env


class MeResponse(BaseModel):
    subject: str
    display_name: str
    email: str | None
    groups: list[str]
    roles: list[Role]
    permissions: list[Permission]
    env: Env
    sample_data: bool
    access_request_url: str | None

    @classmethod
    def from_principal(cls, principal: Principal, ui: UiContext) -> "MeResponse":
        return cls(
            subject=principal.subject,
            display_name=principal.display_name,
            email=principal.email,
            groups=sorted(principal.groups),
            roles=sorted(principal.roles),
            permissions=sorted(principal.permissions),
            env=ui.env,
            sample_data=ui.sample_data,
            access_request_url=ui.access_request_url,
        )
