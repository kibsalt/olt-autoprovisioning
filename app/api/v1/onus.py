from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.olt_driver.driver_factory import OLTDriverPool
from app.schemas.common import APIResponse, PaginatedResponse
from app.schemas.onu import (
    ONUCreate, ONUResponse, ONUStatusResponse, ONUUpdate,
    PPPoEUpdate, UnregisteredONU, WiFiUpdate,
)
from app.services import onu_service

router = APIRouter()


def _get_driver_pool(request: Request) -> OLTDriverPool:
    return request.app.state.driver_pool


@router.get("/olts/{olt_id}/onus", response_model=PaginatedResponse[ONUResponse])
async def list_onus(
    olt_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    onus, total = await onu_service.list_onus(db, olt_id, page, page_size)
    return PaginatedResponse(
        data=[ONUResponse.model_validate(o) for o in onus],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/olts/{olt_id}/onus/unregistered",
    response_model=APIResponse[list[UnregisteredONU]],
)
async def discover_unregistered_onus(
    olt_id: int,
    frame: int = Query(1),
    slot: int = Query(1),
    port: int = Query(1),
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    onus = await onu_service.discover_unregistered(
        db, driver_pool, olt_id, frame, slot, port
    )
    return APIResponse(
        success=True,
        data=[UnregisteredONU(**o) for o in onus],
    )


@router.post(
    "/olts/{olt_id}/onus",
    response_model=APIResponse[ONUResponse],
    status_code=201,
)
async def provision_onu(
    olt_id: int,
    data: ONUCreate,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    onu = await onu_service.provision_onu(db, driver_pool, olt_id, data)
    return APIResponse(success=True, data=ONUResponse.model_validate(onu))


@router.get("/olts/{olt_id}/onus/{onu_id}", response_model=APIResponse[ONUResponse])
async def get_onu(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
):
    onu = await onu_service.get_onu_or_404(db, onu_id)
    return APIResponse(success=True, data=ONUResponse.model_validate(onu))


@router.put("/olts/{olt_id}/onus/{onu_id}", response_model=APIResponse[ONUResponse])
async def update_onu(
    olt_id: int,
    onu_id: int,
    data: ONUUpdate,
    db: AsyncSession = Depends(get_db),
):
    onu = await onu_service.get_onu_or_404(db, onu_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(onu, key, value)
    await db.flush()
    await db.refresh(onu)
    return APIResponse(success=True, data=ONUResponse.model_validate(onu))


@router.delete("/olts/{olt_id}/onus/{onu_id}", status_code=204)
async def remove_onu(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    await onu_service.remove_onu(db, driver_pool, olt_id, onu_id)


@router.get("/onus", response_model=APIResponse[list[ONUResponse]])
async def find_onus_by_customer(
    customer_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    onus = await onu_service.find_onu_by_customer(db, customer_id)
    return APIResponse(
        success=True,
        data=[ONUResponse.model_validate(o) for o in onus],
    )


@router.get("/olts/{olt_id}/onus/{onu_id}/olt-config", response_model=APIResponse[dict])
async def get_onu_olt_config(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    """Retrieve live ONU config from OLT: interface running-config, pon-onu-mng, status, optical, WAN."""
    result = await onu_service.get_olt_config(db, driver_pool, olt_id, onu_id)
    return APIResponse(success=True, data=result)


@router.post("/olts/{olt_id}/onus/{onu_id}/reprovision", response_model=APIResponse[dict])
async def reprovision_onu(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    """Re-push all OLT config (tcont, gemport, service-port, OMCI) for an existing ONU.
    Use when an ONU was offline during provisioning or needs a full config restore."""
    result = await onu_service.reprovision_onu(db, driver_pool, olt_id, onu_id)
    return APIResponse(success=True, data=result)


@router.put("/olts/{olt_id}/onus/{onu_id}/pppoe", response_model=APIResponse[dict])
async def update_pppoe_credentials(
    olt_id: int,
    onu_id: int,
    data: PPPoEUpdate,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    """Push PPPoE username/password and optionally VLAN to the ONU via OLT CLI."""
    result = await onu_service.update_pppoe(
        db, driver_pool, olt_id, onu_id,
        data.pppoe_username, data.pppoe_password, data.service_vlan,
    )
    return APIResponse(success=True, data=result)


@router.put("/olts/{olt_id}/onus/{onu_id}/wifi", response_model=APIResponse[dict])
async def update_wifi_credentials(
    olt_id: int,
    onu_id: int,
    data: WiFiUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Push WiFi SSID and password to the ONU via ACS (TR-069)."""
    result = await onu_service.update_wifi(
        db, olt_id, onu_id, data.ssid_2g, data.ssid_5g, data.password
    )
    return APIResponse(success=True, data=result)
