"""Request and response schemas for the configuration and access-mapping endpoints."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, JsonValue, StringConstraints

from cashapp.domain.principal import Role

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class ConfigEntry(BaseModel):
    key: str
    group: str
    description: str
    value: JsonValue
    default: JsonValue
    version: int
    updated_by: str | None
    updated_by_name: str | None
    updated_at: datetime | None
    admin_only_write: bool


class ConfigUpdate(BaseModel):
    value: JsonValue
    reason: Reason
    expected_version: Annotated[int, Field(ge=0, strict=True)]


class ConfigChangeOut(BaseModel):
    id: int
    key: str
    old_value: JsonValue
    new_value: JsonValue
    changed_by: str
    changed_by_name: str
    changed_at: datetime
    reason: str


class ConfigChangePage(BaseModel):
    items: list[ConfigChangeOut]
    total: int
    offset: int
    limit: int


class GroupRoleMappingModel(BaseModel):
    group_name: GroupName
    role: Role


class GroupRolesResponse(BaseModel):
    mappings: list[GroupRoleMappingModel]
    updated_by: str | None
    updated_at: datetime | None


class GroupRolesUpdate(BaseModel):
    mappings: list[GroupRoleMappingModel]
    reason: Reason
