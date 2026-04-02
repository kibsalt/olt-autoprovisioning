from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.olt_driver.driver_factory import OLTDriverPool
from app.schemas.common import APIResponse
from app.schemas.service_profile import (
    ApplyServiceRequest,
    ServiceProfileCreate,
    ServiceProfileResponse,
    ServiceProfileUpdate,
)
from app.services import onu_service, service_profile_svc

router = APIRouter()


def _get_driver_pool(request: Request) -> OLTDriverPool:
    return request.app.state.driver_pool


@router.get("/service-profiles", response_model=APIResponse[list[ServiceProfileResponse]])
async def list_profiles(db: AsyncSession = Depends(get_db)):
    profiles = await service_profile_svc.list_service_profiles(db)
    return APIResponse(
        success=True,
        data=[ServiceProfileResponse.model_validate(p) for p in profiles],
    )


@router.post(
    "/service-profiles",
    response_model=APIResponse[ServiceProfileResponse],
    status_code=201,
)
async def create_profile(
    data: ServiceProfileCreate,
    db: AsyncSession = Depends(get_db),
):
    profile = await service_profile_svc.create_service_profile(db, data)
    return APIResponse(success=True, data=ServiceProfileResponse.model_validate(profile))


@router.get(
    "/service-profiles/{profile_id}",
    response_model=APIResponse[ServiceProfileResponse],
)
async def get_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
):
    profile = await service_profile_svc.get_profile_or_404(db, profile_id)
    return APIResponse(success=True, data=ServiceProfileResponse.model_validate(profile))


@router.put(
    "/service-profiles/{profile_id}",
    response_model=APIResponse[ServiceProfileResponse],
)
async def update_profile(
    profile_id: int,
    data: ServiceProfileUpdate,
    db: AsyncSession = Depends(get_db),
):
    profile = await service_profile_svc.update_service_profile(db, profile_id, data)
    return APIResponse(success=True, data=ServiceProfileResponse.model_validate(profile))


@router.delete("/service-profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
):
    await service_profile_svc.delete_service_profile(db, profile_id)


@router.post("/olts/{olt_id}/onus/{onu_id}/services", status_code=201)
async def apply_service_to_onu(
    olt_id: int,
    onu_id: int,
    data: ApplyServiceRequest,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    from app.services.olt_service import get_olt_or_404

    olt = await get_olt_or_404(db, olt_id)
    onu = await onu_service.get_onu_or_404(db, onu_id)
    driver = await driver_pool.get_driver(olt)
    svc = await onu_service.apply_service_to_onu(
        db, driver, onu, data.service_profile_id, data.vlan_id
    )
    return APIResponse(success=True, data={"id": svc.id, "status": svc.status.value})


@router.delete("/olts/{olt_id}/onus/{onu_id}/services/{service_id}", status_code=204)
async def remove_service_from_onu(
    olt_id: int,
    onu_id: int,
    service_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    from sqlalchemy import select
    from app.models.onu import ONUService
    from app.services.olt_service import get_olt_or_404

    olt = await get_olt_or_404(db, olt_id)
    result = await db.execute(
        select(ONUService).where(ONUService.id == service_id)
    )
    svc = result.scalar_one_or_none()
    if not svc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Service not found")

    if svc.service_port_id:
        driver = await driver_pool.get_driver(olt)
        await driver.delete_service_port(svc.service_port_id)

    await db.delete(svc)
    await db.flush()
