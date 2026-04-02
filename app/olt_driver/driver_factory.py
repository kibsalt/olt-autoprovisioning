import asyncio

import structlog

from app.config import settings
from app.models.olt import OLT, OLTPlatform
from app.olt_driver.base import BaseOLTDriver
from app.olt_driver.ssh_client import OLTSSHClient
from app.olt_driver.titan_driver import TITANDriver
from app.olt_driver.zxan_driver import ZXANDriver
from app.utils.crypto import decrypt

logger = structlog.get_logger()


class OLTDriverPool:
    """Application-scoped pool mapping olt_id -> connected driver instance."""

    def __init__(self):
        self._drivers: dict[int, BaseOLTDriver] = {}
        self._lock = asyncio.Lock()

    async def get_driver(self, olt: OLT) -> BaseOLTDriver:
        async with self._lock:
            if olt.id in self._drivers:
                driver = self._drivers[olt.id]
                connected = driver.ssh.is_connected if hasattr(driver, "ssh") else True
                if connected:
                    return driver
                # Stale/broken connection — remove and reconnect below
                logger.info("driver_pool_stale", olt_id=olt.id, olt_name=olt.name)
                await self._remove_driver(olt.id)

            ssh = OLTSSHClient(
                host=olt.host,
                port=olt.ssh_port,
                username=decrypt(olt.ssh_username),
                password=decrypt(olt.ssh_password),
                enable_password=decrypt(olt.enable_password) if olt.enable_password else None,
                connect_timeout=settings.ssh_connect_timeout,
                command_timeout=settings.ssh_command_timeout,
            )

            driver_cls = TITANDriver if olt.platform == OLTPlatform.TITAN else ZXANDriver
            driver = driver_cls(ssh)
            await driver.connect()
            self._drivers[olt.id] = driver
            logger.info(
                "driver_pool_connected",
                olt_id=olt.id,
                olt_name=olt.name,
                platform=olt.platform.value,
            )
            return driver

    async def release_driver(self, olt_id: int) -> None:
        async with self._lock:
            await self._remove_driver(olt_id)

    async def _remove_driver(self, olt_id: int) -> None:
        if olt_id in self._drivers:
            try:
                await self._drivers[olt_id].disconnect()
            except Exception:
                logger.warning("driver_disconnect_error", olt_id=olt_id, exc_info=True)
            del self._drivers[olt_id]

    async def close_all(self) -> None:
        async with self._lock:
            for olt_id in list(self._drivers.keys()):
                await self._remove_driver(olt_id)
            logger.info("driver_pool_closed")
