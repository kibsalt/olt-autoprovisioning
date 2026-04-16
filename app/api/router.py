from fastapi import APIRouter

from app.api.v1 import alarms, bandwidth, olts, onus, operations, services, vlans
from app.api.v1 import admin_users, technician

# Machine-to-machine API routes (X-API-Key protected)
api_router = APIRouter()
api_router.include_router(olts.router, prefix="/olts", tags=["OLTs"])
api_router.include_router(onus.router, tags=["ONUs"])
api_router.include_router(services.router, tags=["Service Profiles"])
api_router.include_router(vlans.router, prefix="/vlans", tags=["VLANs"])
api_router.include_router(bandwidth.router, prefix="/bandwidth-profiles", tags=["Bandwidth Profiles"])
api_router.include_router(operations.router, tags=["Operations"])
api_router.include_router(alarms.router, tags=["Alarms"])

# Portal-facing JWT routes (no X-API-Key) — auth, admin, technician
portal_router = APIRouter()
portal_router.include_router(admin_users.router, tags=["Admin"])
portal_router.include_router(technician.router, tags=["Technician"])
