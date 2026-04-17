"""Driver for ZTE ZXAN platform (C300, C320)."""

import re

import structlog

from app.olt_driver.base import BaseOLTDriver, CommandResult, ONUIdentifier
from app.olt_driver.response_parser import OLTResponseParser
from app.olt_driver.ssh_client import OLTSSHClient

logger = structlog.get_logger()


def _parse_optical_info_detail(raw: str) -> dict:
    """Parse 'show gpon onu optical-info' for temp/voltage/rx (legacy format)."""
    d: dict = {}
    patterns = {
        "rx_power":     re.compile(r"Rx\s+(?:optical\s+)?power\s*[:\(]\s*([-\d.]+)", re.I),
        "olt_rx_power": re.compile(r"OLT\s+Rx\s+(?:optical\s+)?power\s*[:\(]\s*([-\d.]+)", re.I),
        "temperature":  re.compile(r"[Tt]emperature\s*[:\(]\s*([-\d.]+)", re.I),
        "voltage":      re.compile(r"[Vv]oltage\s*[:\(]\s*([-\d.]+)", re.I),
    }
    for key, pattern in patterns.items():
        m = pattern.search(raw)
        if m:
            d[key] = m.group(1)
    return d


class ZXANDriver(BaseOLTDriver):

    def __init__(self, ssh_client: OLTSSHClient, model: str = "C300"):
        self.ssh = ssh_client
        self.parser = OLTResponseParser()
        self.model = model.upper()

    async def connect(self) -> None:
        await self.ssh.connect()

    async def disconnect(self) -> None:
        await self.ssh.disconnect()

    async def discover_unregistered_onus(
        self, frame: int, slot: int, port: int
    ) -> list[dict]:
        raw = await self.ssh.execute(
            f"show gpon onu uncfg gpon-olt_{frame}/{slot}/{port}"
        )
        return self.parser.parse_unregistered_onus(raw)

    async def authorize_onu(
        self,
        onu: ONUIdentifier,
        serial_number: str,
        onu_type: str,
        description: str | None = None,
    ) -> CommandResult:
        """Register ONU and set description + SN-bind in a single config session.

        Batching all three sub-steps (register on gpon-olt, set description,
        set sn-bind) into one execute_config_mode call cuts Telnet round-trips
        from 15 to 8 and avoids repeated configure-terminal / end overhead.
        """
        gpon_olt = f"gpon-olt_{onu.frame}/{onu.slot}/{onu.port}"
        gpon_onu = f"gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"

        commands: list[str] = [
            f"interface {gpon_olt}",
            f"onu {onu.onu_id} type {onu_type} sn {serial_number}",
            "exit",
        ]
        # Only enter gpon-onu context if we need to set a description
        # sn-bind is omitted: it triggers live PLOAM negotiation which blocks
        # the Telnet session for several seconds while the OLT waits for the ONU
        # to respond. The ONU is already locked to the serial via the sn field above.
        if description:
            commands += [
                f"interface {gpon_onu}",
                f"description {description.strip().replace(' ', '_')}",
                "exit",
            ]

        try:
            results = await self.ssh.execute_config_mode(commands)
        except Exception as exc:
            logger.warning(
                "authorize_onu_config_error",
                platform="ZXAN",
                serial=serial_number,
                error=str(exc)[:200],
            )
            raise

        logger.info(
            "onu_authorized",
            platform="ZXAN",
            serial=serial_number,
            location=f"{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
        )
        return CommandResult(success=True, raw_output="\n".join(results))

    async def remove_onu(self, onu: ONUIdentifier) -> CommandResult:
        commands = [
            f"interface gpon-olt_{onu.frame}/{onu.slot}/{onu.port}",
            f"no onu {onu.onu_id}",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        raw = "\n".join(results)
        return CommandResult(success=True, raw_output=raw)

    async def create_service_port(
        self,
        service_port_id: int,
        onu: ONUIdentifier,
        vlan_tag: int,
        gem_port: int,
        service_type: str,
        svlan: int | None = None,
    ) -> CommandResult:
        # C300/C320: service-port inside gpon-onu context using vport
        sp_cmd = f"service-port {service_port_id} vport 1 user-vlan {vlan_tag} vlan {vlan_tag}"
        if svlan and svlan != vlan_tag:
            sp_cmd += f" svlan {svlan}"
        commands = [
            f"interface gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            "switchport mode hybrid vport 1",
            sp_cmd,
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def get_port_onu_states(
        self, frame: int, slot: int, port: int
    ) -> dict[int, str]:
        """One SSH call → {onu_id: oper_state} for all ONUs on a port."""
        raw = await self.ssh.execute(
            f"show gpon onu state gpon-olt_{frame}/{slot}/{port}"
        )
        return self.parser.parse_port_onu_states(raw)

    async def get_port_onu_rx(
        self, frame: int, slot: int, port: int,
        onu_ids: list[int] | None = None,
    ) -> dict[int, float]:
        """Return {onu_id: rx_power_dBm} for all ONUs on a port.

        Strategy (C300/C320):
          1. 'show pon power onu-rx gpon-olt_F/S/P'  — bulk ONU Rx (preferred)
          2. Per-ONU 'show pon power attenuation gpon-onu_F/S/P:ID' — reliable fallback
             (same command used by portal optical display; ONU Rx from down line)
        """
        # 1. Bulk attempt — one SSH call covers all ONUs on the port
        try:
            raw = await self.ssh.execute(
                f"show pon power onu-rx gpon-olt_{frame}/{slot}/{port}"
            )
            result = self.parser.parse_port_onu_rx(raw)
            if result:
                logger.debug(
                    "rx_bulk_ok",
                    port=f"{frame}/{slot}/{port}",
                    count=len(result),
                )
                return result
        except Exception:
            pass

        # 2. Per-ONU attenuation — confirmed working on C300
        result: dict[int, float] = {}
        if onu_ids:
            logger.debug(
                "rx_per_onu_fallback",
                port=f"{frame}/{slot}/{port}",
                onu_count=len(onu_ids),
            )
            for oid in onu_ids:
                try:
                    raw = await self.ssh.execute(
                        f"show pon power attenuation gpon-onu_{frame}/{slot}/{port}:{oid}"
                    )
                    parsed = self.parser.parse_pon_power_attenuation(raw)
                    rx = parsed.get("rx_power")
                    if rx is not None:
                        result[oid] = float(rx)
                except Exception:
                    continue
        return result

    async def get_onu_optical(
        self, onu: ONUIdentifier
    ) -> dict:
        """Fetch rich optical data for one ONU.

        Merges 'show pon power attenuation' (C300 primary source for Rx/OLT Rx
        + attenuation) with 'show gpon onu optical-info' (temperature/voltage
        when available).
        """
        path = f"gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"
        merged: dict = {}

        try:
            raw = await self.ssh.execute(f"show pon power attenuation {path}")
            merged.update(self.parser.parse_pon_power_attenuation(raw))
        except Exception:
            pass

        # Still try older optical-info for temp/voltage (and Rx fallback)
        try:
            raw = await self.ssh.execute(f"show gpon onu optical-info {path}")
            old = _parse_optical_info_detail(raw)
            # Only fill gaps — attenuation output is authoritative
            for k, v in old.items():
                merged.setdefault(k, v)
        except Exception:
            pass

        return merged

    async def configure_dba_profile(
        self, profile_id: int, assured_kbps: int
    ) -> CommandResult:
        """Configure a DBA profile for T-CONT type 3 (assured + best-effort)."""
        cmd = (
            f"gpon dba-profile add profile-id {profile_id} "
            f"type 3 assured-bandwidth {assured_kbps}"
        )
        try:
            result = await self.ssh.execute_config_mode([cmd])
            return CommandResult(success=True, raw_output="\n".join(result))
        except Exception:
            # Profile may already exist — treat as non-fatal
            return CommandResult(success=True, raw_output="dba-profile may already exist")

    async def delete_service_port(
        self, service_port_id: int, onu: ONUIdentifier | None = None
    ) -> CommandResult:
        # C300/C320: no service-port must be inside the interface gpon-onu context
        if onu is not None:
            commands = [
                f"interface gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
                f"no service-port {service_port_id}",
                "exit",
            ]
        else:
            commands = [f"no service-port {service_port_id}"]
        results = await self.ssh.execute_config_mode(commands)
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
            f"interface gpon-olt_{onu.frame}/{onu.slot}/{onu.port}",
            f"onu {onu.onu_id} {state}",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def get_onu_status(self, onu: ONUIdentifier) -> CommandResult:
        raw = await self.ssh.execute(
            f"show gpon onu detail-info gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"
        )
        parsed = self.parser.parse_onu_status(raw)
        return CommandResult(success=True, raw_output=raw, parsed=parsed)

    async def get_onu_wan_info(self, onu: ONUIdentifier) -> CommandResult:
        """Query ONU WAN port status and IP assignment via remote-onu commands."""
        path = f"gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"
        combined = ""
        # Try ip-host info first
        try:
            raw = await self.ssh.execute(f"show gpon remote-onu ip-host {path}")
            combined += raw + "\n"
        except Exception:
            pass
        # Try WAN interface info
        try:
            raw = await self.ssh.execute(f"show gpon remote-onu interface wan {path}")
            combined += raw + "\n"
        except Exception:
            pass
        parsed = self.parser.parse_wan_info(combined)
        return CommandResult(success=True, raw_output=combined, parsed=parsed)

    async def configure_tcont(
        self, onu: ONUIdentifier, tcont_id: int, dba_profile_id: int | str
    ) -> CommandResult:
        """Configure T-CONT on C300/C320."""
        profile_name = str(dba_profile_id)
        commands = [
            f"interface gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            f"tcont {tcont_id} name {profile_name} profile {profile_name}",
            f"tcont {tcont_id} gap mode2",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def configure_gemport(
        self, onu: ONUIdentifier, gem_port: int, tcont_id: int,
        profile_name: str | None = None,
    ) -> CommandResult:
        """Configure GEM port on C300/C320."""
        name_part = f" name {profile_name}" if profile_name else ""
        commands = [
            f"interface gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            f"gemport {gem_port}{name_part} tcont {tcont_id} queue 1",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        return CommandResult(success=True, raw_output="\n".join(results))

    async def configure_tcont_gemport_serviceport(
        self,
        onu: ONUIdentifier,
        tcont_id: int,
        dba_profile_id: int | str,
        gem_port: int,
        service_port_id: int,
        vlan_tag: int,
        svlan: int | None = None,
    ) -> CommandResult:
        """Batch T-CONT + GEM port + service-port into one config session.

        Replaces three separate execute_config_mode calls (6 extra round-trips
        for configure-terminal/end) with a single session — cuts OLT round-trips
        from 11 to 7.
        """
        profile_name = str(dba_profile_id)
        gpon_onu = f"gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"

        sp_cmd = f"service-port {service_port_id} vport 1 user-vlan {vlan_tag} vlan {vlan_tag}"
        if svlan and svlan != vlan_tag:
            sp_cmd += f" svlan {svlan}"

        commands = [
            f"interface {gpon_onu}",
            # T-CONT
            f"tcont {tcont_id} name {profile_name} profile {profile_name}",
            f"tcont {tcont_id} gap mode2",
            # GEM port
            f"gemport {gem_port} name {profile_name} tcont {tcont_id} queue 1",
            # Service port
            "switchport mode hybrid vport 1",
            sp_cmd,
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
        logger.info(
            "onu_tcont_gem_sp_configured",
            platform="ZXAN",
            location=f"{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            profile=profile_name,
            vlan=vlan_tag,
        )
        return CommandResult(success=True, raw_output="\n".join(results))

    async def _get_stale_flow_vlans(self, onu_path: str, target_vlan: int) -> list[int]:
        """Return flow 1 VLANs currently on the ONU that are not the target VLAN."""
        import re
        try:
            raw = await self.ssh.execute(f"show onu running config {onu_path}")
            return [
                int(m.group(1))
                for m in re.finditer(r"flow 1 pri \d+ vlan (\d+)", raw)
                if int(m.group(1)) != target_vlan
            ]
        except Exception:
            return []

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
        """Push full OMCI profile via pon-onu-mng context.

        C300 and C320 share most commands but differ in:
        - C320 adds: voip protocol sip, interface pon rx-optical-thresh
        - C320 security-mgmt 2: no 'mode forward' prefix
        - C300 security-mgmt 2: includes 'mode forward'
        """
        path = f"gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"
        is_c320 = self.model == "C320"

        # Remove stale flow/vlan-filter VLANs that differ from the target to
        # prevent duplicate VLAN accumulation across re-provisioning runs.
        # Uses specific 'no flow 1 pri 0 vlan X' rather than 'no flow 1' so
        # that the flow entry itself survives and can be updated while the ONU
        # is offline (blanket 'no flow 1' requires an active OMCI channel to
        # re-create and breaks offline ONUs).
        stale_vlans = await self._get_stale_flow_vlans(path, vlan_id)
        purge_commands: list[str] = []
        if stale_vlans:
            purge_commands.append(f"pon-onu-mng {path}")
            for v in stale_vlans:
                purge_commands.append(f"no flow 1 pri 0 vlan {v}")
                purge_commands.append(f"no vlan-filter iphost 1 pri 0 vlan {v}")
            purge_commands.append("exit")
            try:
                await self.ssh.execute_config_mode(purge_commands, cmd_timeout=10.0)
            except Exception as exc:
                logger.warning("omci_purge_failed", onu=path, error=str(exc)[:200])

        commands = [f"pon-onu-mng {path}"]

        if is_c320:
            commands += [
                "voip protocol sip",
                f"interface pon pon_0/1 rx-optical-thresh lower -24.0 upper ont-internal-policy",
            ]

        commands += [
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
            "vlan-filter-mode iphost 1 tag-filter vlan-filter untag-filter discard",
            f"vlan-filter iphost 1 pri 0 vlan {vlan_id}",
            "firewall enable level low anti-hack disable",
            "tr069-mgmt 1 state unlock",
            f"tr069-mgmt 1 acs {acs_url} validate basic username {acs_username} password {acs_password}",
            "security-mgmt 1 state enable mode forward protocol web",
        ]

        if is_c320:
            commands.append("security-mgmt 2 state enable ingress-type lan protocol web")
        else:
            commands.append("security-mgmt 2 state enable mode forward ingress-type lan protocol web")

        commands += [
            "security-mgmt 3 state enable ingress-type lan protocol telnet",
            "security-mgmt 4 state enable protocol telnet",
            "exit",
        ]

        results = await self.ssh.execute_config_mode(commands, cmd_timeout=10.0)
        logger.info(
            "omci_configured",
            platform="ZXAN",
            model=self.model,
            onu=path,
            vlan=vlan_id,
            pppoe=bool(pppoe_username),
        )
        return CommandResult(success=True, raw_output="\n".join(results))

    async def configure_acs(
        self,
        onu: ONUIdentifier,
        acs_url: str,
        acs_username: str,
        acs_password: str,
    ) -> CommandResult:
        """Delegate to configure_omci for standalone ACS-only updates."""
        return await self.configure_omci(
            onu,
            vlan_id=0,
            acs_url=acs_url,
            acs_username=acs_username,
            acs_password=acs_password,
        )

    async def configure_wifi(
        self,
        onu: ONUIdentifier,
        ssid_2g: str,
        ssid_5g: str,
        password: str,
    ) -> CommandResult:
        """Push WiFi SSID and WPA2-PSK credentials to the ONU via pon-onu-mng.

        Uses the OLT CLI WiFi management context:
            pon-onu-mng gpon-onu_F/S/P:ID
              ssid ctrl wifi_0/1 name <ssid_2g>          ← 2.4 GHz
              ssid auth wpa wifi_0/1 wpa2-psk encrypt aes key <password>
              ssid ctrl wifi_1/1 name <ssid_5g>          ← 5 GHz
              ssid auth wpa wifi_1/1 wpa2-psk encrypt aes key <password>
            exit

        After config mode exits (execute_config_mode sends 'end'), a
        'write' is sent to persist the ONU running config on the OLT.

        Non-fatal — some ONUs / firmware versions may not support the ssid
        commands over OMCI; errors are logged as warnings.
        """
        path = f"gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"

        commands = [
            f"pon-onu-mng {path}",
            # 2.4 GHz
            f"ssid ctrl wifi_0/1 name {ssid_2g}",
            f"ssid auth wpa wifi_0/1 wpa2-psk encrypt aes key {password}",
            # 5 GHz
            f"ssid ctrl wifi_1/1 name {ssid_5g}",
            f"ssid auth wpa wifi_1/1 wpa2-psk encrypt aes key {password}",
            "exit",   # back to configure terminal context
        ]

        results = await self.ssh.execute_config_mode(commands, cmd_timeout=10.0)

        # Persist to OLT NVRAM — run outside config mode (execute_config_mode
        # already sent 'end' to return to enable mode)
        try:
            await self.ssh.execute("write", timeout=15.0)
        except Exception as exc:
            logger.warning("wifi_olt_write_failed", onu=path, error=str(exc)[:200])

        logger.info(
            "wifi_olt_configured",
            platform="ZXAN",
            onu=path,
            ssid_2g=ssid_2g,
            ssid_5g=ssid_5g,
        )
        return CommandResult(success=True, raw_output="\n".join(results))
