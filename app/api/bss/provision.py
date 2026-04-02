"""BSS-facing flat provisioning router.

Endpoints follow the ZTE OLT API spec:
  POST   /provision
  DELETE /provision/{customer_id}
  PUT    /provision/{customer_id}/suspend
  PUT    /provision/{customer_id}/activate
  PUT    /provision/{customer_id}/package
  GET    /onu/{olt_id}/unconfigured
  GET    /onu/{olt_id}/find/{sn}
"""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.olt_driver.driver_factory import OLTDriverPool
from app.schemas.common import APIResponse
from app.schemas.onu import UnregisteredONU
from app.schemas.provision import (
    PackageUpdateRequest,
    ProvisionRequest,
    ProvisionResponse,
)
from app.services import provision_service
from app.services.provision_service import get_olt_by_name

router = APIRouter(tags=["BSS Provisioning"])


def _pool(request: Request) -> OLTDriverPool:
    return request.app.state.driver_pool


@router.post("/provision", response_model=APIResponse[ProvisionResponse], status_code=201)
async def provision_onu(
    data: ProvisionRequest,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_pool),
):
    """Full 14-step ONU provisioning: authorize -> T-CONT -> GEM -> service-port
    -> ACS endpoint -> TR-069 Inform wait -> WiFi push -> notifications."""
    result = await provision_service.bss_provision(db, driver_pool, data)
    return APIResponse(success=True, data=result)


@router.delete("/provision/{customer_id}", status_code=204)
async def deprovision_onu(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_pool),
):
    """Remove all ONU configuration from OLT and database."""
    await provision_service.bss_deprovision(db, driver_pool, customer_id)


@router.put("/provision/{customer_id}/suspend", response_model=APIResponse[dict])
async def suspend_onu(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_pool),
):
    """Suspend ONU — admin-state disable (no traffic)."""
    result = await provision_service.bss_suspend(db, driver_pool, customer_id)
    return APIResponse(success=True, data=result)


@router.put("/provision/{customer_id}/activate", response_model=APIResponse[dict])
async def activate_onu(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_pool),
):
    """Activate ONU — admin-state enable."""
    result = await provision_service.bss_activate(db, driver_pool, customer_id)
    return APIResponse(success=True, data=result)


@router.put("/provision/{customer_id}/package", response_model=APIResponse[dict])
async def change_package(
    customer_id: str,
    data: PackageUpdateRequest,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_pool),
):
    """Update bandwidth package — reconfigures T-CONT profile on OLT."""
    result = await provision_service.bss_change_package(
        db, driver_pool, customer_id, data.package_id
    )
    return APIResponse(success=True, data=result)


@router.get(
    "/onu/{olt_id}/unconfigured",
    response_model=APIResponse[list[UnregisteredONU]],
)
async def list_unconfigured_onus(
    olt_id: str,
    frame: int = Query(1),
    slot: int = Query(7),
    port: int = Query(2),
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_pool),
):
    """List unconfigured ONUs on a specific PON port. olt_id is the OLT name."""
    olt = await get_olt_by_name(db, olt_id)
    driver = await driver_pool.get_driver(olt)
    onus = await driver.discover_unregistered_onus(frame, slot, port)
    return APIResponse(
        success=True,
        data=[UnregisteredONU(**o) for o in onus],
    )


@router.get(
    "/onu/{olt_id}/find/{sn}",
    response_model=APIResponse[UnregisteredONU],
)
async def find_onu_by_serial(
    olt_id: str,
    sn: str,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_pool),
):
    """Find an unconfigured ONU by serial number across all known PON ports."""
    from fastapi import HTTPException
    olt = await get_olt_by_name(db, olt_id)
    driver = await driver_pool.get_driver(olt)
    scan_ports = [(1, s, p) for s in [7, 9] for p in range(16)]
    for frame, slot, port in scan_ports:
        try:
            onus = await driver.discover_unregistered_onus(frame, slot, port)
            for onu in onus:
                if onu.get("serial_number", "").upper() == sn.upper():
                    return APIResponse(success=True, data=UnregisteredONU(**onu))
        except Exception:
            continue
    raise HTTPException(
        status_code=404,
        detail=f"ONU {sn} not found as unconfigured on {olt_id}",
    )
