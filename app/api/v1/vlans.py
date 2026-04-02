from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.common import APIResponse
from app.schemas.vlan import VLANCreate, VLANResponse, VLANUpdate
from app.services import vlan_service

router = APIRouter()


@router.get("", response_model=APIResponse[list[VLANResponse]])
async def list_vlans(db: AsyncSession = Depends(get_db)):
    vlans = await vlan_service.list_vlans(db)
    return APIResponse(
        success=True,
        data=[VLANResponse.model_validate(v) for v in vlans],
    )


@router.post("", response_model=APIResponse[VLANResponse], status_code=201)
async def create_vlan(data: VLANCreate, db: AsyncSession = Depends(get_db)):
    vlan = await vlan_service.create_vlan(db, data)
    return APIResponse(success=True, data=VLANResponse.model_validate(vlan))


@router.get("/{vlan_id}", response_model=APIResponse[VLANResponse])
async def get_vlan(vlan_id: int, db: AsyncSession = Depends(get_db)):
    vlan = await vlan_service.get_vlan_or_404(db, vlan_id)
    return APIResponse(success=True, data=VLANResponse.model_validate(vlan))


@router.put("/{vlan_id}", response_model=APIResponse[VLANResponse])
async def update_vlan(
    vlan_id: int, data: VLANUpdate, db: AsyncSession = Depends(get_db)
):
    vlan = await vlan_service.update_vlan(db, vlan_id, data)
    return APIResponse(success=True, data=VLANResponse.model_validate(vlan))


@router.delete("/{vlan_id}", status_code=204)
async def delete_vlan(vlan_id: int, db: AsyncSession = Depends(get_db)):
    await vlan_service.delete_vlan(db, vlan_id)
