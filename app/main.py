import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.middleware import RequestContextMiddleware
from app.api.router import api_router, portal_router
from app.api.v1.auth import router as auth_router
from app.config import settings
from app.db.session import engine
from app.dependencies import verify_api_key
from app.olt_driver.driver_factory import OLTDriverPool
from app.olt_driver.exceptions import (
    OLTCommandError,
    OLTConnectionError,
    OLTTimeoutError,
    ONUNotFoundError,
)
from app.services.alarm_poller import run_alarm_poller

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
        if settings.debug
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(10 if settings.debug else 20),
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.driver_pool = OLTDriverPool()
    poller_task = asyncio.create_task(run_alarm_poller(app.state.driver_pool))
    logger.info("app_started", debug=settings.debug)
    yield
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    await app.state.driver_pool.close_all()
    await engine.dispose()
    logger.info("app_stopped")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)

# ── Machine-to-machine API (X-API-Key required) ────────────────────────────
app.include_router(
    api_router,
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)

# ── BSS provisioning (X-API-Key required) ──────────────────────────────────
from app.api.bss.provision import router as bss_router
app.include_router(
    bss_router,
    dependencies=[Depends(verify_api_key)],
)

# ── Auth endpoints (no X-API-Key — JWT only) ───────────────────────────────
app.include_router(auth_router)

# ── Portal JWT endpoints (no X-API-Key — JWT auth handled per-endpoint) ───
app.include_router(portal_router, prefix="/api/v1")


# ── Error Handlers ─────────────────────────────────────────────────────────


@app.exception_handler(OLTConnectionError)
async def olt_connection_error_handler(request: Request, exc: OLTConnectionError):
    logger.error("olt_connection_error", error=str(exc))
    return JSONResponse(
        status_code=502,
        content={"success": False, "error": {"code": "OLT_CONNECTION_ERROR", "message": str(exc)}},
    )


@app.exception_handler(OLTCommandError)
async def olt_command_error_handler(request: Request, exc: OLTCommandError):
    logger.error("olt_command_error", error=str(exc), command=exc.command)
    return JSONResponse(
        status_code=422,
        content={"success": False, "error": {"code": "OLT_COMMAND_ERROR", "message": str(exc)}},
    )


@app.exception_handler(OLTTimeoutError)
async def olt_timeout_error_handler(request: Request, exc: OLTTimeoutError):
    logger.error("olt_timeout", error=str(exc))
    return JSONResponse(
        status_code=504,
        content={"success": False, "error": {"code": "OLT_TIMEOUT", "message": str(exc)}},
    )


@app.exception_handler(ONUNotFoundError)
async def onu_not_found_error_handler(request: Request, exc: ONUNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"success": False, "error": {"code": "ONU_NOT_FOUND", "message": str(exc)}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), exc_type=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": exc.errors(),
            },
        },
    )


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# ── BSS Portal (static HTML) ─────────────────────────────────────────────────
_DOCS_DIR = Path(__file__).parent.parent / "docs"
if _DOCS_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_DOCS_DIR)), name="static")

    @app.get("/portal", include_in_schema=False)
    async def bss_portal():
        return FileResponse(str(_DOCS_DIR / "bss-portal.html"))
