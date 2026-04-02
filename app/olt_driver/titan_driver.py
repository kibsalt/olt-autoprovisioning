"""Driver for ZTE TITAN platform (C600, C620, C650)."""

import structlog

from app.olt_driver.base import BaseOLTDriver, CommandResult, ONUIdentifier
from app.olt_driver.response_parser import OLTResponseParser
from app.olt_driver.ssh_client import OLTSSHClient

logger = structlog.get_logger()


class TITANDriver(BaseOLTDriver):

    def __init__(self, ssh_client: OLTSSHClient):
        self.ssh = ssh_client
        self.parser = OLTResponseParser()

    async def connect(self) -> None:
        await self.ssh.connect()

    async def disconnect(self) -> None:
        await self.ssh.disconnect()

    async def discover_unregistered_onus(
        self, frame: int, slot: int, port: int
    ) -> list[dict]:
        raw = await self.ssh.execute(
            f"show gpon onu uncfg gpon_olt-{frame}/{slot}/{port}"
        )
        return self.parser.parse_unregistered_onus(raw)

    async def authorize_onu(
        self,
        onu: ONUIdentifier,
        serial_number: str,
        onu_type: str,
        description: str | None = None,
    ) -> CommandResult:
        commands = [
            f"interface gpon_olt-{onu.frame}/{onu.slot}/{onu.port}",
            f"onu {onu.onu_id} type {onu_type} sn {serial_number}",
        ]
        if description:
            commands.append(f"onu {onu.onu_id} description {description}")
        commands.append("exit")

        results = await self.ssh.execute_config_mode(commands)
        raw = "\n".join(results)
        logger.info(
            "onu_authorized",
            platform="TITAN",
            serial=serial_number,
            location=f"{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
        )
        return CommandResult(success=True, raw_output=raw)

    async def remove_onu(self, onu: ONUIdentifier) -> CommandResult:
        commands = [
            f"interface gpon_olt-{onu.frame}/{onu.slot}/{onu.port}",
            f"no onu {onu.onu_id}",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def create_service_port(
        self,
        service_port_id: int,
        onu: ONUIdentifier,
        vlan_tag: int,
        gem_port: int,
        service_type: str,
    ) -> CommandResult:
        cmd = (
            f"service-port {service_port_id} "
            f"gpon {onu.frame}/{onu.slot}/{onu.port} "
            f"onu {onu.onu_id} gemport {gem_port} "
            f"match vlan {vlan_tag} action vlan {vlan_tag}"
        )
        results = await self.ssh.execute_config_mode([cmd])
        return CommandResult(success=True, raw_output="\n".join(results))

    async def delete_service_port(self, service_port_id: int) -> CommandResult:
        results = await self.ssh.execute_config_mode(
            [f"no service-port {service_port_id}"]
        )
        return CommandResult(success=True, raw_output="\n".join(results))

    async def configure_traffic_table(
        self, index: int, cir: int, pir: int, cbs: int, pbs: int, direction: str
    ) -> CommandResult:
        cmd = (
            f"traffic-table ip index {index} "
            f"cir {cir} pir {pir} cbs {cbs} pbs {pbs} "
            f"priority 0 priority-policy local-Setting"
        )
        results = await self.ssh.execute_config_mode([cmd])
        return CommandResult(success=True, raw_output="\n".join(results))

    async def set_onu_admin_state(
        self, onu: ONUIdentifier, enabled: bool
    ) -> CommandResult:
        state = "enable" if enabled else "disable"
        commands = [
            f"interface gpon_olt-{onu.frame}/{onu.slot}/{onu.port}",
            f"onu {onu.onu_id} {state}",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def get_onu_status(self, onu: ONUIdentifier) -> CommandResult:
        raw = await self.ssh.execute(
            f"show gpon onu detail-info gpon_onu-{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"
        )
        parsed = self.parser.parse_onu_status(raw)
        return CommandResult(success=True, raw_output=raw, parsed=parsed)

    async def get_onu_wan_info(self, onu: ONUIdentifier) -> CommandResult:
        path = f"gpon_onu-{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"
        combined = ""
        try:
            raw = await self.ssh.execute(f"show gpon remote-onu ip-host {path}")
            combined += raw + "\n"
        except Exception:
            pass
        try:
            raw = await self.ssh.execute(f"show gpon remote-onu interface wan {path}")
            combined += raw + "\n"
        except Exception:
            pass
        parsed = self.parser.parse_wan_info(combined)
        return CommandResult(success=True, raw_output=combined, parsed=parsed)

    async def configure_tcont(
        self, onu: ONUIdentifier, tcont_id: int, dba_profile_id: int
    ) -> CommandResult:
        commands = [
            f"interface gpon_onu-{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            f"tcont {tcont_id} profile {dba_profile_id}",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def configure_gemport(
        self, onu: ONUIdentifier, gem_port: int, tcont_id: int
    ) -> CommandResult:
        commands = [
            f"interface gpon_onu-{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            f"gemport {gem_port} tcont {tcont_id}",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

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
        """Push full OMCI profile via pon-onu-mng context (TITAN C600/C620/C650)."""
        path = f"gpon_onu-{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"
        commands = [
            f"pon-onu-mng {path}",
            "flow mode 1 tag-filter vlan-filter untag-filter discard",
            f"flow 1 pri 0 vlan {vlan_id}",
            "gemport 1 flow 1 dot1p-list 0",
            "switchport-bind switch_0/1 iphost 1",
        ]
        if pppoe_username and pppoe_password:
            commands.append(
                f"pppoe 1 nat enable user {pppoe_username} password {pppoe_password}"
            )
        commands += [
            f"vlan-filter-mode iphost 1 tag-filter vlan-filter untag-filter discard",
            f"vlan-filter iphost 1 pri 0 vlan {vlan_id}",
            "firewall enable level low anti-hack disable",
            "tr069-mgmt 1 state unlock",
            f"tr069-mgmt 1 acs {acs_url} validate basic username {acs_username} password {acs_password}",
            "security-mgmt 1 state enable mode forward protocol web",
            "security-mgmt 2 state enable ingress-type lan protocol web",
            "security-mgmt 3 state enable ingress-type lan protocol telnet",
            "security-mgmt 4 state enable protocol telnet",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def configure_acs(
        self,
        onu: ONUIdentifier,
        acs_url: str,
        acs_username: str,
        acs_password: str,
    ) -> CommandResult:
        commands = [
            f"interface gpon_onu-{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            f"wan-ip 1 mode tr069 vlan-id 0 host 1",
            f"tr069-serv-url {acs_url}",
            f"tr069-username {acs_username}",
            f"tr069-password {acs_password}",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def configure_wifi(
        self,
        onu: ONUIdentifier,
        ssid_2g: str,
        ssid_5g: str,
        password: str,
    ) -> CommandResult:
        commands = [
            f"interface gpon_onu-{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            # 2.4GHz WiFi (SSID index 1)
            f"wifi ssid 1 name {ssid_2g}",
            f"wifi ssid 1 auth-mode wpa2-psk",
            f"wifi ssid 1 wpa-key {password}",
            f"wifi ssid 1 enable true",
            # 5GHz WiFi (SSID index 5)
            f"wifi ssid 5 name {ssid_5g}",
            f"wifi ssid 5 auth-mode wpa2-psk",
            f"wifi ssid 5 wpa-key {password}",
            f"wifi ssid 5 enable true",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def configure_dba_profile(
        self, profile_id: int, assured_kbps: int
    ) -> CommandResult:
        cmd = (
            f"gpon dba-profile add profile-id {profile_id} "
            f"type 3 assured-bandwidth {assured_kbps}"
        )
        try:
            result = await self.ssh.execute_config_mode([cmd])
            return CommandResult(success=True, raw_output="\n".join(result))
        except Exception:
            return CommandResult(success=True, raw_output="dba-profile may already exist")
