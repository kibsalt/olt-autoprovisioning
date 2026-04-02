from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bandwidth_profile import BandwidthProfile
from app.schemas.bandwidth_profile import BandwidthProfileCreate, BandwidthProfileUpdate


async def list_bandwidth_profiles(db: AsyncSession) -> list[BandwidthProfile]:
    result = await db.execute(select(BandwidthProfile).order_by(BandwidthProfile.name))
    return result.scalars().all()


async def get_profile_or_404(db: AsyncSession, profile_id: int) -> BandwidthProfile:
    result = await db.execute(
        select(BandwidthProfile).where(BandwidthProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bandwidth profile not found"
        )
    return profile


async def create_bandwidth_profile(
    db: AsyncSession, data: BandwidthProfileCreate
) -> BandwidthProfile:
    profile = BandwidthProfile(**data.model_dump())
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile


async def update_bandwidth_profile(
    db: AsyncSession, profile_id: int, data: BandwidthProfileUpdate
) -> BandwidthProfile:
    profile = await get_profile_or_404(db, profile_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    await db.flush()
    await db.refresh(profile)
    return profile


async def delete_bandwidth_profile(db: AsyncSession, profile_id: int) -> None:
    profile = await get_profile_or_404(db, profile_id)
    await db.delete(profile)
    await db.flush()
