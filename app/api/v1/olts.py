from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_api_key
from app.models.olt import OLTStatus
from app.olt_driver.driver_factory import OLTDriverPool
from app.schemas.common import APIResponse, PaginatedResponse
from app.schemas.olt import OLTCreate, OLTHealthResponse, OLTResponse, OLTUpdate
from app.services import olt_service

router = APIRouter()


def _get_driver_pool(request: Request) -> OLTDriverPool:
    return request.app.state.driver_pool


@router.get("", response_model=PaginatedResponse[OLTResponse])
async def list_olts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: OLTStatus | None = None,
    model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    olts, total = await olt_service.list_olts(db, page, page_size, status, model)
    return PaginatedResponse(
        data=[OLTResponse.model_validate(o) for o in olts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=APIResponse[OLTResponse], status_code=201)
async def create_olt(
    data: OLTCreate,
    db: AsyncSession = Depends(get_db),
):
    olt = await olt_service.create_olt(db, data)
    return APIResponse(success=True, data=OLTResponse.model_validate(olt))


@router.get("/{olt_id}", response_model=APIResponse[OLTResponse])
async def get_olt(
    olt_id: int,
    db: AsyncSession = Depends(get_db),
):
    olt = await olt_service.get_olt_or_404(db, olt_id)
    return APIResponse(success=True, data=OLTResponse.model_validate(olt))


@router.put("/{olt_id}", response_model=APIResponse[OLTResponse])
async def update_olt(
    olt_id: int,
    data: OLTUpdate,
    db: AsyncSession = Depends(get_db),
):
    olt = await olt_service.update_olt(db, olt_id, data)
    return APIResponse(success=True, data=OLTResponse.model_validate(olt))


@router.delete("/{olt_id}", status_code=204)
async def delete_olt(
    olt_id: int,
    db: AsyncSession = Depends(get_db),
):
    await olt_service.delete_olt(db, olt_id)


@router.get("/{olt_id}/health", response_model=APIResponse[OLTHealthResponse])
async def check_olt_health(
    olt_id: int,
    db: AsyncSession = Depends(get_db),
    driver_pool: OLTDriverPool = Depends(_get_driver_pool),
):
    olt = await olt_service.get_olt_or_404(db, olt_id)
    try:
        driver = await driver_pool.get_driver(olt)
        # Simple connectivity test (show version is ambiguous on some ZTE models)
        raw = await driver.ssh.execute("show clock")
        health = OLTHealthResponse(
            olt_id=olt.id,
            name=olt.name,
            host=olt.host,
            reachable=True,
            software_version=raw[:100] if raw else None,
        )
    except Exception as e:
        health = OLTHealthResponse(
            olt_id=olt.id,
            name=olt.name,
            host=olt.host,
            reachable=False,
            error=str(e),
        )
    return APIResponse(success=True, data=health)
