from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ONUIdentifier:
    frame: int
    slot: int
    port: int
    onu_id: int

    @property
    def gpon_onu_path(self) -> str:
        return f"gpon-onu_{self.frame}/{self.slot}/{self.port}:{self.onu_id}"

    @property
    def gpon_olt_path(self) -> str:
        return f"gpon-olt_{self.frame}/{self.slot}/{self.port}"


@dataclass
class CommandResult:
    success: bool
    raw_output: str
    parsed: dict | None = None
    error_message: str | None = None


class BaseOLTDriver(ABC):

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def discover_unregistered_onus(
        self, frame: int, slot: int, port: int
    ) -> list[dict]: ...

    @abstractmethod
    async def authorize_onu(
        self,
        onu: ONUIdentifier,
        serial_number: str,
        onu_type: str,
        description: str | None = None,
    ) -> CommandResult: ...

    @abstractmethod
    async def remove_onu(self, onu: ONUIdentifier) -> CommandResult: ...

    @abstractmethod
    async def create_service_port(
        self,
        service_port_id: int,
        onu: ONUIdentifier,
        vlan_tag: int,
        gem_port: int,
        service_type: str,
    ) -> CommandResult: ...

    @abstractmethod
    async def delete_service_port(self, service_port_id: int) -> CommandResult: ...

    @abstractmethod
    async def configure_traffic_table(
        self,
        index: int,
        cir: int,
        pir: int,
        cbs: int,
        pbs: int,
        direction: str,
    ) -> CommandResult: ...

    @abstractmethod
    async def set_onu_admin_state(
        self, onu: ONUIdentifier, enabled: bool
    ) -> CommandResult: ...

    @abstractmethod
    async def get_onu_status(self, onu: ONUIdentifier) -> CommandResult: ...

    @abstractmethod
    async def configure_tcont(
        self, onu: ONUIdentifier, tcont_id: int, dba_profile_id: int
    ) -> CommandResult: ...

    @abstractmethod
    async def configure_gemport(
        self, onu: ONUIdentifier, gem_port: int, tcont_id: int
    ) -> CommandResult: ...

    @abstractmethod
    async def configure_omci(
        self,
        onu: ONUIdentifier,
        vlan_id: int,
        acs_url: str,
        acs_username: str,
        acs_password: str,
        pppoe_username: str | None = None,
        pppoe_password: str | None = None,
    ) -> CommandResult:
        """Push full OMCI profile: flow/VLAN, PPPoE credentials, ACS endpoint, security."""
        ...

    @abstractmethod
    async def configure_wifi(
        self,
        onu: ONUIdentifier,
        ssid_2g: str,
        ssid_5g: str,
        password: str,
    ) -> CommandResult: ...

    @abstractmethod
    async def configure_dba_profile(
        self, profile_id: int, assured_kbps: int
    ) -> CommandResult: ...
