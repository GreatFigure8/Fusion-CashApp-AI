"""Request and response schemas for stored secrets. No schema carries a secret value out."""

from datetime import datetime

from pydantic import BaseModel, SecretStr

from cashapp.api.schemas.config import Reason


class SecretOut(BaseModel):
    name: str
    version: int
    updated_at: datetime
    updated_by: str


class SecretUpdate(BaseModel):
    value: SecretStr
    reason: Reason
