import re


class OLTResponseParser:
    """Parse ZTE OLT CLI output into structured data."""

    @staticmethod
    def parse_unregistered_onus(raw: str) -> list[dict]:
        """Parse 'show gpon onu uncfg' output.

        Handles two formats:
          gpon-onu_1/7/2:1   ZXICC9F27071   unknown   (C300/C320 firmware)
          gpon-olt_1/2/1     ZTEGC8FA0001   ...        (alternate firmware)
          1/2/1   1   ZTEGC8FA0001  ZXHN_F680  ...     (TITAN firmware)
        """
        results = []
        # Matches frame/slot/port with optional :onu_id suffix (C300 style)
        pattern = re.compile(
            r"(?:gpon-onu_|gpon-olt_)?(\d+)/(\d+)/(\d+)(?::\d+)?\s+"
            r"(?:(\d+)\s+)?"
            r"([A-Z0-9]{8,16})"
        )
        for line in raw.split("\n"):
            m = pattern.search(line.strip())
            if m:
                results.append({
                    "frame": int(m.group(1)),
                    "slot": int(m.group(2)),
                    "port": int(m.group(3)),
                    "serial_number": m.group(5),
                })
        return results

    @staticmethod
    def parse_onu_status(raw: str) -> dict:
        """Parse 'show gpon onu detail-info' or 'show gpon onu state' output."""
        result = {}
        patterns = {
            "admin_state": re.compile(r"Admin\s+state\s*:\s*(\S+)", re.IGNORECASE),
            "oper_state": re.compile(r"(?:Phase|Run)\s+state\s*:\s*(\S+)", re.IGNORECASE),
            "rx_power": re.compile(r"Rx\s+(?:optical\s+)?power\s*[:\(]\s*([-\d.]+)", re.IGNORECASE),
            "tx_power": re.compile(r"Tx\s+(?:optical\s+)?power\s*[:\(]\s*([-\d.]+)", re.IGNORECASE),
            "distance": re.compile(r"(?:ONU\s+)?[Dd]istance\s*:\s*(\d+)", re.IGNORECASE),
            "last_down_cause": re.compile(r"[Ll]ast\s+down\s+cause\s*:\s*(.+)", re.IGNORECASE),
            "online_duration": re.compile(r"[Oo]nline\s+duration\s*:\s*(.+)", re.IGNORECASE),
        }
        for key, pattern in patterns.items():
            m = pattern.search(raw)
            if m:
                result[key] = m.group(1).strip()
        return result

    @staticmethod
    def parse_service_ports(raw: str) -> list[dict]:
        """Parse 'show service-port' output."""
        results = []
        # Typical format: ID  VLAN  Type  Port  ...
        pattern = re.compile(
            r"(\d+)\s+"       # service port id
            r"(\d+)\s+"       # vlan
            r"(\S+)\s+"       # type (gpon)
            r"(\S+)\s+"       # port info
        )
        for line in raw.split("\n"):
            m = pattern.search(line.strip())
            if m:
                results.append({
                    "service_port_id": int(m.group(1)),
                    "vlan": int(m.group(2)),
                    "type": m.group(3),
                    "port": m.group(4),
                })
        return results

    @staticmethod
    def parse_next_onu_id(raw: str) -> int | None:
        """Parse output to find next available ONU ID on a port."""
        used_ids = set()
        pattern = re.compile(r"onu\s+(\d+)\s+type", re.IGNORECASE)
        for line in raw.split("\n"):
            m = pattern.search(line)
            if m:
                used_ids.add(int(m.group(1)))
        for i in range(1, 129):
            if i not in used_ids:
                return i
        return None

    @staticmethod
    def parse_onu_id_by_serial(raw: str, serial_number: str) -> int | None:
        """Return the existing ONU ID for a serial if already registered on this port."""
        pattern = re.compile(
            r"onu\s+(\d+)\s+type\s+\S+\s+sn\s+(\S+)", re.IGNORECASE
        )
        for line in raw.split("\n"):
            m = pattern.search(line)
            if m and m.group(2).upper() == serial_number.upper():
                return int(m.group(1))
        return None

    @staticmethod
    def parse_port_onu_states(raw: str) -> dict[int, str]:
        """Parse 'show gpon onu state gpon-olt_F/S/P' — returns {onu_id: oper_state}.

        Handles two common formats:
          1   enable  working  pass  success  match  ...
          gpon-onu_1/7/2:3   enable  working  ...
        """
        result: dict[int, str] = {}
        # Format 1: leading integer ONU ID
        pat1 = re.compile(r"^\s*(\d+)\s+\S+\s+(\S+)", re.IGNORECASE)
        # Format 2: gpon-onu path prefix
        pat2 = re.compile(r"gpon-onu_\d+/\d+/\d+:(\d+)\s+\S+\s+(\S+)", re.IGNORECASE)
        for line in raw.split("\n"):
            m = pat2.search(line) or pat1.match(line)
            if m:
                try:
                    onu_id = int(m.group(1))
                    oper   = m.group(2).lower()
                    # Skip header/separator rows
                    if oper not in ("state", "enable", "disable", "---", "oper"):
                        result[onu_id] = oper
                    elif oper in ("enable", "disable"):
                        pass  # admin state column — real oper state is next
                except (ValueError, IndexError):
                    pass
        return result

    @staticmethod
    def parse_port_onu_rx(raw: str) -> dict[int, float]:
        """Parse 'show gpon onu optical-info gpon-olt_F/S/P' — returns {onu_id: rx_dBm}."""
        result: dict[int, float] = {}
        # Typical: "1   -20.50   2.00   ..."  or  "gpon-onu_1/7/2:1  -20.50 ..."
        pat1 = re.compile(r"^\s*(\d+)\s+([-\d.]+)", re.IGNORECASE)
        pat2 = re.compile(r"gpon-onu_\d+/\d+/\d+:(\d+)\s+([-\d.]+)", re.IGNORECASE)
        for line in raw.split("\n"):
            m = pat2.search(line) or pat1.match(line)
            if m:
                try:
                    result[int(m.group(1))] = float(m.group(2))
                except (ValueError, IndexError):
                    pass
        return result

    @staticmethod
    def parse_onu_rx_power(raw: str) -> dict:
        """Parse 'show pon power onu-rx gpon-onu_F/S/P:ID' output (ZTE C300/C320).

        Example output:
            Onu                 Rx power
            ------------------------------------
            gpon-onu_1/9/2:1    -18.410(dbm)

        Returns a dict with:
            rx_power — ONU Rx power [string dBm], if present.
        """
        result: dict = {}
        m = re.search(
            r"gpon-onu_\d+/\d+/\d+:\d+\s+([-+]?\d+(?:\.\d+)?)\s*\(dbm\)",
            raw,
            re.IGNORECASE,
        )
        if m:
            result["rx_power"] = m.group(1)
        return result

    @staticmethod
    def parse_wan_info(raw: str) -> dict:
        """Parse 'show gpon remote-onu interface wan' or 'show gpon remote-onu ip-host' output.

        Extracts WAN connection status, IP address, mask, gateway, DNS, and PPPoE state.
        """
        result = {}
        patterns = {
            "wan_status": re.compile(r"(?:WAN|Connection)\s+(?:status|state)\s*:\s*(\S+)", re.IGNORECASE),
            "ip_address": re.compile(r"IP\s+address\s*:\s*([\d.]+)", re.IGNORECASE),
            "subnet_mask": re.compile(r"(?:Subnet\s+)?[Mm]ask\s*:\s*([\d.]+)", re.IGNORECASE),
            "gateway": re.compile(r"(?:Default\s+)?[Gg]ateway\s*:\s*([\d.]+)", re.IGNORECASE),
            "dns1": re.compile(r"(?:Primary\s+)?DNS\s*(?:1|server)?\s*:\s*([\d.]+)", re.IGNORECASE),
            "dns2": re.compile(r"(?:Secondary\s+)?DNS\s*2?\s*:\s*([\d.]+)", re.IGNORECASE),
            "mac_address": re.compile(r"MAC\s+address\s*:\s*([0-9a-fA-F:.-]+)", re.IGNORECASE),
            "pppoe_status": re.compile(r"PPPoE?\s+(?:status|state)\s*:\s*(\S+)", re.IGNORECASE),
            "connection_mode": re.compile(r"(?:Connection|Mode)\s*:\s*(PPPoE|DHCP|Static|Bridge)", re.IGNORECASE),
            "vlan_id": re.compile(r"VLAN\s+(?:ID|id)\s*:\s*(\d+)", re.IGNORECASE),
            "ipv6_address": re.compile(r"IPv6\s+address\s*:\s*(\S+)", re.IGNORECASE),
        }
        for key, pattern in patterns.items():
            m = pattern.search(raw)
            if m:
                result[key] = m.group(1).strip()
        # Derive internet status
        ip = result.get("ip_address")
        if ip and ip != "0.0.0.0":
            result["has_internet"] = True
        else:
            result["has_internet"] = False
        return result

    @staticmethod
    def is_error_output(raw: str) -> tuple[bool, str | None]:
        """Check if CLI output contains error patterns."""
        error_patterns = [
            r"% Parameter error",
            r"% Unknown command",
            r"% Invalid input",
            r"Error:",
            r"% Incomplete command",
            r"Command is not found",
        ]
        for pattern in error_patterns:
            m = re.search(pattern, raw)
            if m:
                return True, m.group(0)
        return False, None
