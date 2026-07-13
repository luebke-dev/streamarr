"""Computing provider status API."""

from fastapi import APIRouter
from pydantic import BaseModel

from streamarr.api.dependencies import CurrentSuperuser
from streamarr.utils.environment import get_computing_provider_domain

router = APIRouter()


class ComputingStatus(BaseModel):
    provider: str
    detected: bool = True


@router.get("/status", response_model=ComputingStatus)
async def get_computing_status(current_user: CurrentSuperuser):
    """Get the detected computing provider status."""
    provider = get_computing_provider_domain()
    return ComputingStatus(provider=provider)
