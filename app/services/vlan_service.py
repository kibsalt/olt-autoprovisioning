from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vlan import VLAN
from app.schemas.vlan import VLANCreate, VLANUpdate


async def list_vlans(db: AsyncSession) -> list[VLAN]:
    result = await db.execute(select(VLAN).order_by(VLAN.vlan_tag))
    return result.scalars().all()


async def get_vlan_or_404(db: AsyncSession, vlan_id: int) -> VLAN:
    result = await db.execute(select(VLAN).where(VLAN.id == vlan_id))
    vlan = result.scalar_one_or_none()
    if not vlan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN not found")
    return vlan


async def create_vlan(db: AsyncSession, data: VLANCreate) -> VLAN:
    vlan = VLAN(**data.model_dump())
    db.add(vlan)
    await db.flush()
    await db.refresh(vlan)
    return vlan


async def update_vlan(db: AsyncSession, vlan_id: int, data: VLANUpdate) -> VLAN:
    vlan = await get_vlan_or_404(db, vlan_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(vlan, key, value)
    await db.flush()
    await db.refresh(vlan)
    return vlan


async def delete_vlan(db: AsyncSession, vlan_id: int) -> None:
    vlan = await get_vlan_or_404(db, vlan_id)
    await db.delete(vlan)
    await db.flush()
