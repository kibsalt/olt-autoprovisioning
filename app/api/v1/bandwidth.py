from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.bandwidth_profile import (
    BandwidthProfileCreate,
    BandwidthProfileResponse,
    BandwidthProfileUpdate,
)
from app.schemas.common import APIResponse
from app.services import bandwidth_service

router = APIRouter()


@router.get("", response_model=APIResponse[list[BandwidthProfileResponse]])
async def list_profiles(db: AsyncSession = Depends(get_db)):
    profiles = await bandwidth_service.list_bandwidth_profiles(db)
    return APIResponse(
        success=True,
        data=[BandwidthProfileResponse.model_validate(p) for p in profiles],
    )


@router.post(
    "", response_model=APIResponse[BandwidthProfileResponse], status_code=201
)
async def create_profile(
    data: BandwidthProfileCreate, db: AsyncSession = Depends(get_db)
):
    profile = await bandwidth_service.create_bandwidth_profile(db, data)
    return APIResponse(
        success=True, data=BandwidthProfileResponse.model_validate(profile)
    )


@router.get("/{profile_id}", response_model=APIResponse[BandwidthProfileResponse])
async def get_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    profile = await bandwidth_service.get_profile_or_404(db, profile_id)
    return APIResponse(
        success=True, data=BandwidthProfileResponse.model_validate(profile)
    )


@router.put("/{profile_id}", response_model=APIResponse[BandwidthProfileResponse])
async def update_profile(
    profile_id: int,
    data: BandwidthProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    profile = await bandwidth_service.update_bandwidth_profile(db, profile_id, data)
    return APIResponse(
        success=True, data=BandwidthProfileResponse.model_validate(profile)
    )


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    await bandwidth_service.delete_bandwidth_profile(db, profile_id)
