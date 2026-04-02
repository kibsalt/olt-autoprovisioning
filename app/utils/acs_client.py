"""GenieACS REST client for pushing TR-069 parameters to ONUs."""
import asyncio
import json
from functools import partial

import requests
import structlog

logger = structlog.get_logger()

# TR-098 PPPoE paths
_PPPOE_USERNAME = (
    "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1"
    ".WANPPPConnection.1.Username"
)
_PPPOE_PASSWORD = (
    "InternetGatewayDevice.WANDevice.1.WANConnectionDevice.1"
    ".WANPPPConnection.1.Password"
)

# TR-181 WiFi paths (Device data model)
_WIFI_SSID_2G = "Device.WiFi.SSID.1.SSID"
_WIFI_SSID_5G = "Device.WiFi.SSID.2.SSID"
_WIFI_KEY_2G  = "Device.WiFi.AccessPoint.1.Security.KeyPassphrase"
_WIFI_KEY_5G  = "Device.WiFi.AccessPoint.2.Security.KeyPassphrase"
_WIFI_CHAN_2G = "Device.WiFi.Radio.1.Channel"
_WIFI_CHAN_5G = "Device.WiFi.Radio.2.Channel"


def _post_sync(url: str, payload: dict, timeout: float, headers: dict) -> requests.Response:
    return requests.post(url, json=payload, timeout=timeout, headers=headers)


def _get_sync(url: str, timeout: float, headers: dict) -> requests.Response:
    return requests.get(url, timeout=timeout, headers=headers)


class ACSClient:
    """Northbound client for GenieACS management API (default port 7557)."""

    def __init__(self, management_url: str, timeout: float = 30.0, api_key: str | None = None):
        self.management_url = management_url.rstrip("/")
        self.timeout = timeout
        self._headers = {"x-api-key": api_key} if api_key else {}

    def _device_id(self, serial_number: str) -> str:
        return serial_number

    async def _push_task(
        self,
        device_id: str,
        param_values: list[tuple[str, str, str]],
    ) -> bool:
        url = f"{self.management_url}/devices/{device_id}/tasks?connection_request"
        payload = {
            "name": "setParameterValues",
            "parameterValues": [list(pv) for pv in param_values],
        }
        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(
                None, partial(_post_sync, url, payload, self.timeout, self._headers)
            )
            if resp.status_code not in (200, 202):
                logger.error(
                    "acs_task_http_error",
                    device_id=device_id,
                    status=resp.status_code,
                    body=resp.text[:256],
                )
                return False
            logger.info(
                "acs_task_pushed",
                device_id=device_id,
                params=[pv[0] for pv in param_values],
            )
            return True
        except Exception as exc:
            logger.error("acs_task_error", device_id=device_id, error=str(exc))
            return False

    async def configure_pppoe(
        self, serial_number: str, username: str, password: str
    ) -> bool:
        device_id = self._device_id(serial_number)
        params = [
            (_PPPOE_USERNAME, username, "xsd:string"),
            (_PPPOE_PASSWORD, password, "xsd:string"),
        ]
        return await self._push_task(device_id, params)

    async def configure_wifi(
        self,
        serial_number: str,
        ssid_2g: str,
        ssid_5g: str,
        password: str,
    ) -> bool:
        device_id = self._device_id(serial_number)
        params = [
            (_WIFI_SSID_2G, ssid_2g,  "xsd:string"),
            (_WIFI_SSID_5G, ssid_5g,  "xsd:string"),
            (_WIFI_KEY_2G,  password, "xsd:string"),
            (_WIFI_KEY_5G,  password, "xsd:string"),
            (_WIFI_CHAN_2G, "0",       "xsd:unsignedInt"),
            (_WIFI_CHAN_5G, "0",       "xsd:unsignedInt"),
        ]
        return await self._push_task(device_id, params)

    async def wait_for_inform(
        self,
        serial_number: str,
        timeout: float = 120.0,
        interval: float = 5.0,
    ) -> bool:
        """Poll GenieACS until the device shows a recent lastInform timestamp."""
        device_id = self._device_id(serial_number)
        url = (
            f"{self.management_url}/devices"
            f'?query={{"_id":"{device_id}"}}&projection=_lastInform'
        )
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                resp = await loop.run_in_executor(
                    None, partial(_get_sync, url, 10.0, self._headers)
                )
                if resp.status_code == 200:
                    devices = resp.json()
                    if devices and devices[0].get("_lastInform"):
                        logger.info("acs_inform_received", device_id=device_id)
                        return True
            except Exception as exc:
                logger.debug("acs_inform_poll_error", device_id=device_id, error=str(exc))
            await asyncio.sleep(interval)
        logger.warning("acs_inform_timeout", device_id=device_id, timeout=timeout)
        return False
