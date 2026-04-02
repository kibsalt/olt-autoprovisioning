from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.olt import OLT, MODEL_TO_PLATFORM, OLTStatus
from app.schemas.olt import OLTCreate, OLTUpdate
from app.utils.crypto import encrypt


async def get_olt_or_404(db: AsyncSession, olt_id: int) -> OLT:
    result = await db.execute(select(OLT).where(OLT.id == olt_id))
    olt = result.scalar_one_or_none()
    if not olt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OLT not found")
    return olt


async def list_olts(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    status_filter: OLTStatus | None = None,
    model_filter: str | None = None,
) -> tuple[list[OLT], int]:
    query = select(OLT)
    if status_filter:
        query = query.where(OLT.status == status_filter)
    if model_filter:
        query = query.where(OLT.model == model_filter)

    count_result = await db.execute(
        select(OLT.id).where(query.whereclause) if query.whereclause is not None
        else select(OLT.id)
    )
    total = len(count_result.all())

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total


async def create_olt(db: AsyncSession, data: OLTCreate) -> OLT:
    platform = MODEL_TO_PLATFORM[data.model]
    olt = OLT(
        name=data.name,
        host=data.host,
        ssh_port=data.ssh_port,
        model=data.model,
        platform=platform,
        software_version=data.software_version,
        location=data.location,
        description=data.description,
        ssh_username=encrypt(data.ssh_username),
        ssh_password=encrypt(data.ssh_password),
        enable_password=encrypt(data.enable_password) if data.enable_password else None,
    )
    db.add(olt)
    await db.flush()
    await db.refresh(olt)
    return olt


async def update_olt(db: AsyncSession, olt_id: int, data: OLTUpdate) -> OLT:
    olt = await get_olt_or_404(db, olt_id)
    update_data = data.model_dump(exclude_unset=True)

    if "ssh_username" in update_data and update_data["ssh_username"]:
        update_data["ssh_username"] = encrypt(update_data["ssh_username"])
    if "ssh_password" in update_data and update_data["ssh_password"]:
        update_data["ssh_password"] = encrypt(update_data["ssh_password"])
    if "enable_password" in update_data and update_data["enable_password"]:
        update_data["enable_password"] = encrypt(update_data["enable_password"])

    for key, value in update_data.items():
        setattr(olt, key, value)

    await db.flush()
    await db.refresh(olt)
    return olt


async def delete_olt(db: AsyncSession, olt_id: int) -> None:
    olt = await get_olt_or_404(db, olt_id)
    olt.status = OLTStatus.DECOMMISSIONED
    await db.flush()
