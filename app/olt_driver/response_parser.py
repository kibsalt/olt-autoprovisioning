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
        # Serial can be upper or lower case — normalise to upper
        pattern = re.compile(
            r"(?:gpon-onu_|gpon-olt_)?(\d+)/(\d+)/(\d+)(?::\d+)?\s+"
            r"(?:(\d+)\s+)?"
            r"([A-Za-z0-9]{8,16})"
        )
        for line in raw.split("\n"):
            m = pattern.search(line.strip())
            if m:
                results.append({
                    "frame": int(m.group(1)),
                    "slot": int(m.group(2)),
                    "port": int(m.group(3)),
                    "serial_number": m.group(5).upper(),
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

        ZTE C300 format (5 columns):
          gpon-onu_1/9/2:1  enable  disable  unknown  OffLine
          gpon-onu_1/9/2:3  enable  enable   operation  working
          columns: ONU | Admin State | OMCC State | O7 State | Phase State

        Older format (leading integer, 2 columns):
          1   enable  working  pass  success  match  ...
        """
        result: dict[int, str] = {}
        # Format 1: gpon-onu path prefix — capture Phase State (5th column)
        pat1 = re.compile(
            r"gpon-onu_\d+/\d+/\d+:(\d+)\s+\S+\s+\S+\s+\S+\s+(\S+)",
            re.IGNORECASE,
        )
        # Format 2: leading integer ONU ID — capture 2nd token (oper state in older firmware)
        pat2 = re.compile(r"^\s*(\d+)\s+\S+\s+(\S+)", re.IGNORECASE)
        for line in raw.split("\n"):
            m = pat1.search(line) or pat2.match(line)
            if m:
                try:
                    onu_id = int(m.group(1))
                    oper   = m.group(2).lower()
                    if oper not in ("state", "enable", "disable", "---", "oper", "phase"):
                        result[onu_id] = oper
                except (ValueError, IndexError):
                    pass
        return result

    @staticmethod
    def parse_port_onu_rx(raw: str) -> dict[int, float]:
        """Parse Rx power output — returns {onu_id: rx_dBm}.

        Handles multiple ZTE output formats:
          C300 'show pon power onu-rx':
            gpon-onu_1/9/2:1    -18.410(dbm)
          Older 'show gpon onu optical-info':
            1   -20.50   2.00   ...
            gpon-onu_1/7/2:1  -20.50 ...
        """
        result: dict[int, float] = {}
        # gpon-onu_F/S/P:ONU_ID  VALUE(dbm)  — C300 'show pon power onu-rx'
        pat_pon = re.compile(
            r"gpon-onu_\d+/\d+/\d+:(\d+)\s+([-\d.]+)\s*(?:\(dbm\))?",
            re.IGNORECASE,
        )
        # Leading integer ONU ID — older 'show gpon onu optical-info'
        pat_old = re.compile(r"^\s*(\d+)\s+([-\d.]+)", re.IGNORECASE)
        for line in raw.split("\n"):
            m = pat_pon.search(line) or pat_old.match(line)
            if m:
                try:
                    result[int(m.group(1))] = float(m.group(2))
                except (ValueError, IndexError):
                    pass
        return result

    @staticmethod
    def parse_pon_power_attenuation(raw: str) -> dict:
        """Parse 'show pon power attenuation gpon-onu_F/S/P:ID' output.

        Expected format (ZTE C300):
                   OLT                  ONU              Attenuation
          --------------------------------------------------------------------------
           up      Rx :-13.955(dbm)      Tx:2.317(dbm)        16.272(dB)
           down    Tx :6.093(dbm)        Rx:-14.318(dbm)      20.411(dB)

        Returns dict with:
          - rx_power        : ONU Rx (downstream, from OLT)
          - olt_rx_power    : OLT Rx (upstream, from ONU)
          - attenuation_up  : upstream attenuation in dB
          - attenuation_down: downstream attenuation in dB
        """
        result: dict = {}
        # Upstream: OLT Rx, ONU Tx, attenuation
        up_pat = re.compile(
            r"up\s+Rx\s*:\s*([-\d.]+)\s*\(dbm\)\s+Tx\s*:\s*([-\d.]+)\s*\(dbm\)\s+([-\d.]+)\s*\(dB\)",
            re.IGNORECASE,
        )
        # Downstream: OLT Tx, ONU Rx, attenuation
        down_pat = re.compile(
            r"down\s+Tx\s*:\s*([-\d.]+)\s*\(dbm\)\s+Rx\s*:\s*([-\d.]+)\s*\(dbm\)\s+([-\d.]+)\s*\(dB\)",
            re.IGNORECASE,
        )
        m_up = up_pat.search(raw)
        if m_up:
            result["olt_rx_power"] = m_up.group(1)
            result["attenuation_up"] = m_up.group(3)
        m_down = down_pat.search(raw)
        if m_down:
            result["rx_power"] = m_down.group(2)
            result["attenuation_down"] = m_down.group(3)
        return result

    @staticmethod
    def parse_port_pon_power_attenuation(raw: str) -> dict[int, float]:
        """Parse bulk 'show pon power attenuation gpon-olt_F/S/P' (if supported).

        Returns {onu_id: rx_dBm} — ONU downstream Rx only.
        Format per-ONU block may include the onu path header 'gpon-onu_F/S/P:ID'
        followed by up/down lines. Extract ONU Rx (down direction).
        """
        result: dict[int, float] = {}
        # Split by ONU path headers
        blocks = re.split(r"(gpon-onu_\d+/\d+/\d+:\d+)", raw)
        # blocks = ['pre', 'gpon-onu_1/9/2:1', 'block1', 'gpon-onu_1/9/2:2', 'block2', ...]
        for i in range(1, len(blocks) - 1, 2):
            path = blocks[i]
            body = blocks[i + 1]
            onu_id_m = re.search(r":(\d+)$", path)
            if not onu_id_m:
                continue
            down_m = re.search(
                r"down\s+Tx\s*:\s*[-\d.]+\s*\(dbm\)\s+Rx\s*:\s*([-\d.]+)",
                body,
                re.IGNORECASE,
            )
            if down_m:
                try:
                    result[int(onu_id_m.group(1))] = float(down_m.group(1))
                except ValueError:
                    pass
        return result

    @staticmethod
    def parse_wan_info(raw: str) -> dict:
        """Parse 'show gpon remote-onu interface wan' or 'show gpon remote-onu ip-host' output.

        Extracts WAN connection status, IP address, mask, gateway, DNS, and PPPoE state.
        ZTE ip-host has two sets: static config (IP addres:) and live PPPoE (Current IP address:).
        We prefer the 'Current' values when present.
        """
        result = {}
        patterns = {
            "wan_status": re.compile(r"(?:WAN|Connection)\s+(?:status|state)\s*:\s*(\S+)", re.IGNORECASE),
            "ip_address": re.compile(r"IP\s+addres(?:s)?\s*:\s*([\d.]+)", re.IGNORECASE),
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

        # ZTE ip-host: prefer "Current" values (live PPPoE/DHCP) over static config
        current_patterns = {
            "ip_address":  re.compile(r"Current\s+IP\s+address\s*:\s*([\d.]+)", re.IGNORECASE),
            "subnet_mask": re.compile(r"Current\s+mask\s*:\s*([\d.]+)", re.IGNORECASE),
            "gateway":     re.compile(r"Current\s+gateway\s*:\s*([\d.]+)", re.IGNORECASE),
            "dns1":        re.compile(r"Current\s+primary\s+DNS\s*:\s*([\d.]+)", re.IGNORECASE),
            "dns2":        re.compile(r"Current\s+second\s+DNS\s*:\s*([\d.]+)", re.IGNORECASE),
        }
        for key, pattern in current_patterns.items():
            m = pattern.search(raw)
            if m:
                val = m.group(1).strip()
                if val != "0.0.0.0":
                    result[key] = val

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
