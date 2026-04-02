from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.onu import AdminState
from app.olt_driver.driver_factory import OLTDriverPool
from app.schemas.common import APIResponse
from app.schemas.onu import ONUStatusResponse
from app.schemas.operations import OperationResponse
from app.services import onu_service

router = APIRouter()


def _get_driver_pool(request: Request) -> OLTDriverPool:
    return request.app.state.driver_pool


@router.post(
    "/olts/{olt_id}/onus/{onu_id}/enable",
    response_model=APIResponse[OperationResponse],
)
async def enable_onu(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    onu = await onu_service.get_onu_or_404(db, onu_id)
    prev = onu.admin_state.value
    onu = await onu_service.set_onu_state(db, driver_pool, olt_id, onu_id, AdminState.ENABLED)
    return APIResponse(
        success=True,
        data=OperationResponse(
            success=True,
            message="ONU enabled",
            onu_id=onu.id,
            previous_state=prev,
            new_state=onu.admin_state.value,
        ),
    )


@router.post(
    "/olts/{olt_id}/onus/{onu_id}/disable",
    response_model=APIResponse[OperationResponse],
)
async def disable_onu(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    onu = await onu_service.get_onu_or_404(db, onu_id)
    prev = onu.admin_state.value
    onu = await onu_service.set_onu_state(db, driver_pool, olt_id, onu_id, AdminState.DISABLED)
    return APIResponse(
        success=True,
        data=OperationResponse(
            success=True,
            message="ONU disabled",
            onu_id=onu.id,
            previous_state=prev,
            new_state=onu.admin_state.value,
        ),
    )


@router.post(
    "/olts/{olt_id}/onus/{onu_id}/suspend",
    response_model=APIResponse[OperationResponse],
)
async def suspend_onu(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    onu = await onu_service.get_onu_or_404(db, onu_id)
    prev = onu.admin_state.value
    onu = await onu_service.set_onu_state(db, driver_pool, olt_id, onu_id, AdminState.SUSPENDED)
    return APIResponse(
        success=True,
        data=OperationResponse(
            success=True,
            message="ONU suspended",
            onu_id=onu.id,
            previous_state=prev,
            new_state=onu.admin_state.value,
        ),
    )


@router.get(
    "/olts/{olt_id}/onus/{onu_id}/status",
    response_model=APIResponse[ONUStatusResponse],
)
async def get_onu_live_status(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    status_data = await onu_service.get_live_status(db, driver_pool, olt_id, onu_id)
    return APIResponse(success=True, data=ONUStatusResponse(**status_data))


@router.get("/olts/{olt_id}/onus/{onu_id}/olt-config")
async def get_onu_olt_config(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    """Retrieve the ONU interface and pon-onu-mng running config from the OLT."""
    config_data = await onu_service.get_olt_config(db, driver_pool, olt_id, onu_id)
    return APIResponse(success=True, data=config_data)


@router.get("/olts/{olt_id}/onus/{onu_id}/wan")
async def get_onu_wan_info(
    olt_id: int,
    onu_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    """Query ONU WAN port status, IP address, and internet connectivity."""
    wan_data = await onu_service.get_wan_info(db, driver_pool, olt_id, onu_id)
    return APIResponse(success=True, data=wan_data)
