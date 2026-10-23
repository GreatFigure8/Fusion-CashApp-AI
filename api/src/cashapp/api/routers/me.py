"""The signed-in caller's identity, roles and permissions."""

from fastapi import APIRouter

from cashapp.api.schemas.me import MeResponse
from cashapp.auth.deps import PrincipalDep

router = APIRouter(tags=["identity"])


@router.get("/me", response_model=MeResponse)
async def get_me(principal: PrincipalDep) -> MeResponse:
    return MeResponse.from_principal(principal)
