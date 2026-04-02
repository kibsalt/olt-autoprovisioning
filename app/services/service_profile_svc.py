from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_profile import ServiceProfile
from app.schemas.service_profile import ServiceProfileCreate, ServiceProfileUpdate


async def list_service_profiles(db: AsyncSession) -> list[ServiceProfile]:
    result = await db.execute(select(ServiceProfile).order_by(ServiceProfile.name))
    return result.scalars().all()


async def get_profile_or_404(db: AsyncSession, profile_id: int) -> ServiceProfile:
    result = await db.execute(
        select(ServiceProfile).where(ServiceProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service profile not found"
        )
    return profile


async def create_service_profile(
    db: AsyncSession, data: ServiceProfileCreate
) -> ServiceProfile:
    profile = ServiceProfile(**data.model_dump())
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile


async def update_service_profile(
    db: AsyncSession, profile_id: int, data: ServiceProfileUpdate
) -> ServiceProfile:
    profile = await get_profile_or_404(db, profile_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    await db.flush()
    await db.refresh(profile)
    return profile


async def delete_service_profile(db: AsyncSession, profile_id: int) -> None:
    profile = await get_profile_or_404(db, profile_id)
    await db.delete(profile)
    await db.flush()
