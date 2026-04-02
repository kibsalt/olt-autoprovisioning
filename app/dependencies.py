from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.db.session import get_db_session

API_KEY_HEADER = APIKeyHeader(name="X-API-Key")


def get_settings() -> Settings:
    return settings


async def verify_api_key(
    api_key: str = Security(API_KEY_HEADER),
) -> str:
    if api_key not in settings.api_key_list:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return api_key


async def get_db(
    session: AsyncSession = Depends(get_db_session),
) -> AsyncSession:
    return session
