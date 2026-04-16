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
        # Step 1: Register ONU on the PON port
        commands = [
            f"interface gpon-olt_{onu.frame}/{onu.slot}/{onu.port}",
            f"onu {onu.onu_id} type {onu_type} sn {serial_number}",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)

        # Step 2: Set description inside gpon-onu interface context (not gpon-olt)
        if description:
            safe_desc = description.strip().replace(" ", "_")
            try:
                await self.ssh.execute_config_mode([
                    f"interface gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
                    f"description {safe_desc}",
                    "exit",
                ])
            except Exception as exc:
                logger.warning(
                    "onu_description_skipped",
                    platform="ZXAN",
                    serial=serial_number,
                    error=str(exc)[:200],
                )

        # Step 3: Enable SN binding — non-fatal; third-party ONUs (e.g. Falba FTTM-F839) reject this
        try:
            await self.ssh.execute_config_mode([
                f"interface gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
                "sn-bind enable sn",
                "exit",
            ])
        except Exception as exc:
            logger.warning(
                "sn_bind_skipped",
                platform="ZXAN",
                serial=serial_number,
                error=str(exc)[:200],
            )

        raw = "\n".join(results)
        logger.info(
            "onu_authorized",
            platform="ZXAN",
            serial=serial_number,
            location=f"{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
        )
        return CommandResult(success=True, raw_output=raw)

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
        """Configure T-CONT on C300/C320.

        dba_profile_id can be a named profile (e.g. 'Fix_10M', 'Faiba-100Mbps')
        or a numeric ID. Named profiles are used as both name and profile reference.
        """
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
        """Configure GEM port on C300/C320.

        If profile_name is given, uses it as the gemport name (matching tcont).
        """
        name_part = f" name {profile_name}" if profile_name else ""
        commands = [
            f"interface gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            f"gemport {gem_port}{name_part} tcont {tcont_id} queue 1",
            "exit",
        ]
        results = await self.ssh.execute_config_mode(commands)
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
        # C300/C320 firmware does not support WiFi CLI commands.
        # WiFi must be configured via ACS/TR-069 after the ONU registers.
        logger.info(
            "wifi_cli_skipped",
            platform="ZXAN",
            onu=f"{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}",
            reason="C300/C320 firmware does not support wifi CLI — use ACS",
        )
        return CommandResult(
            success=True,
            raw_output="WiFi CLI not supported on ZXAN C300/C320 — configure via ACS",
        )
