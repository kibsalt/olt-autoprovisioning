import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = structlog.get_logger()


async def create_audit_log(
    db: AsyncSession,
    api_key_id: str,
    action: str,
    resource_type: str,
    ip_address: str,
    response_status: int,
    resource_id: int | None = None,
    olt_id: int | None = None,
    request_body: dict | None = None,
    olt_commands: list | None = None,
    olt_responses: list | None = None,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> AuditLog:
    log = AuditLog(
        api_key_id=api_key_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        olt_id=olt_id,
        request_body=request_body,
        response_status=response_status,
        olt_commands=olt_commands,
        olt_responses=olt_responses,
        error_message=error_message,
        duration_ms=duration_ms,
        ip_address=ip_address,
    )
    db.add(log)
    await db.flush()
    logger.info(
        "audit_log_created",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    return log
