"""Liveness probe. Readiness (database ping) is added by the stories that own a database."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from cashapp import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)
