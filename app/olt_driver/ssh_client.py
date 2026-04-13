import asyncio
import re

import structlog

from app.olt_driver.exceptions import OLTCommandError, OLTConnectionError, OLTTimeoutError

logger = structlog.get_logger()

# Match ZTE prompts in all modes:
#   HOSTNAME#                         (privileged EXEC)
#   HOSTNAME>                         (user EXEC)
#   HOSTNAME(config)#                 (global config)
#   HOSTNAME(config-if)#              (interface config)
#   HOSTNAME(gpon-onu-mng F/S/P:ID)#  (GPON ONU mng context)
PROMPT_PATTERN = re.compile(r"[A-Za-z0-9_\-\.]+(?:\([^)]*\))?[#>]\s*$")
PRIV_PROMPT_PATTERN = re.compile(r"[A-Za-z0-9_\-\.]+(?:\([^)]*\))?#\s*$")
ERROR_PATTERNS = [
    r"% Parameter error",
    r"% Unknown command",
    r"% Invalid input",
    r"%Error \d+:",
    r"% Incomplete command",
    r"Command is not found",
]

# Telnet IAC control byte and common option codes
_IAC  = 0xFF
_DONT = 0xFE
_DO   = 0xFD
_WONT = 0xFC
_WILL = 0xFB
_SB   = 0xFA   # subnegotiation begin
_SE   = 0xF0   # subnegotiation end


def _respond_iac(data: bytes) -> bytes:
    """Generate WONT/DONT replies for all incoming DO/WILL Telnet negotiations."""
    resp = bytearray()
    i = 0
    while i < len(data):
        if data[i] == _IAC and i + 2 < len(data):
            cmd, opt = data[i + 1], data[i + 2]
            if cmd == _DO:
                resp += bytes([_IAC, _WONT, opt])
            elif cmd == _WILL:
                resp += bytes([_IAC, _DONT, opt])
            i += 3
        else:
            i += 1
    return bytes(resp)


def _strip_iac(data: bytes) -> bytes:
    """Strip Telnet IAC negotiation sequences and return clean bytes."""
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == _IAC:
            i += 1
            if i >= len(data):
                break
            cmd = data[i]
            if cmd in (_DO, _DONT, _WILL, _WONT):
                i += 2   # skip option byte
            elif cmd == _SB:
                # skip until IAC SE
                while i < len(data) - 1:
                    i += 1
                    if data[i] == _IAC and i + 1 < len(data) and data[i + 1] == _SE:
                        i += 2
                        break
            else:
                i += 1   # IAC IAC or other 2-byte sequence
        else:
            out.append(b)
            i += 1
    return bytes(out)


class OLTSSHClient:
    """Async Telnet client for ZTE OLT CLI interaction.

    Named OLTSSHClient for backwards compatibility — drop-in replacement
    that uses Telnet (port 23) instead of SSH.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        enable_password: str | None = None,
        connect_timeout: float = 10.0,
        command_timeout: float = 30.0,
    ):
        self.host = host
        self.port = port if port != 22 else 23   # default SSH port → Telnet port
        self.username = username
        self.password = password
        self.enable_password = enable_password
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._connected = False

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.connect_timeout,
            )
        except asyncio.TimeoutError as e:
            raise OLTConnectionError(
                f"Telnet connection to {self.host}:{self.port} timed out"
            ) from e
        except OSError as e:
            raise OLTConnectionError(
                f"Failed to connect to {self.host}:{self.port}: {e}"
            ) from e

        try:
            # Login sequence: returns True if already at privileged (#) prompt
            already_privileged = await self._login()

            # Escalate to privileged EXEC if needed
            if self.enable_password and not already_privileged:
                await self._enter_privileged_mode()

            self._connected = True

            # Disable pagination
            try:
                await self.execute("terminal length 0")
            except (OLTCommandError, OLTConnectionError):
                pass

            logger.info("ssh_connected", host=self.host, port=self.port)

        except Exception as e:
            await self.disconnect()
            if isinstance(e, (OLTConnectionError, OLTTimeoutError)):
                raise
            raise OLTConnectionError(
                f"Login failed on {self.host}:{self.port}: {e}"
            ) from e

    async def _login(self) -> bool:
        """Handle Telnet login. Returns True if already at privileged (#) prompt."""
        # Read initial data: may be IAC only, or IAC + banner + Username: all at once
        buf = ""
        try:
            raw = await asyncio.wait_for(self._reader.read(4096), timeout=self.connect_timeout)
            neg_resp = _respond_iac(raw)
            if neg_resp:
                self._writer.write(neg_resp)
            buf = _strip_iac(raw).decode("ascii", errors="replace")
        except asyncio.TimeoutError:
            pass

        # Banner + Username: may arrive after IAC negotiation in a separate packet
        if not any(k in buf for k in ("Username", "username", "login", "Login", ">", "#")):
            buf += await self._read_until_any(
                ["Username", "username", "login", "Login", ">", "#"],
                timeout=self.connect_timeout,
            )

        if not any(k in buf for k in ("Username", "username", "login", "Login", ">", "#")):
            raise OLTConnectionError(f"No login prompt received from {self.host}")

        # Already at a prompt (no auth required)
        if not any(k in buf for k in ("Username", "username", "login", "Login")):
            return bool(PRIV_PROMPT_PATTERN.search(buf))

        self._write(self.username + "\r\n")
        buf = await self._read_until_any(
            ["Password", "password", ">", "#"],
            timeout=self.connect_timeout,
        )

        if any(k in buf for k in ("Password", "password")):
            self._write(self.password + "\r\n")
            buf = await self._read_until_any(
                ["#", ">", "fail", "invalid", "denied", "incorrect"],
                timeout=self.connect_timeout,
            )
            if any(k in buf.lower() for k in ("fail", "invalid", "denied", "incorrect")):
                raise OLTConnectionError(f"Authentication failed on {self.host}")

        return bool(PRIV_PROMPT_PATTERN.search(buf))

    async def disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None
        self._connected = False
        logger.info("ssh_disconnected", host=self.host)

    # ------------------------------------------------------------------
    # Privileged mode
    # ------------------------------------------------------------------

    async def _is_privileged(self) -> bool:
        self._write("\r\n")
        buf = await self._read_until_prompt(timeout=3)
        return bool(PRIV_PROMPT_PATTERN.search(buf))

    async def _enter_privileged_mode(self) -> None:
        self._write("enable\r\n")
        buf = await self._read_until_any(["Password", "#", ">"], timeout=5)
        if "Password" in buf:
            self._write(self.enable_password + "\r\n")
            buf = await self._read_until_any(["#", ">", "Bad password"], timeout=5)
            if "Bad password" in buf or "#" not in buf:
                raise OLTConnectionError(f"Enable password rejected on {self.host}")
        logger.info("ssh_privileged", host=self.host)

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def _write(self, text: str) -> None:
        if not self._writer:
            raise OLTConnectionError("Not connected to OLT")
        self._writer.write(text.encode("ascii", errors="replace"))

    async def execute(self, command: str, timeout: float | None = None) -> str:
        if not self._connected or not self._writer:
            raise OLTConnectionError("Not connected to OLT")

        timeout = timeout or self.command_timeout
        async with self._lock:
            logger.debug("ssh_command", host=self.host, command=command)
            try:
                self._write(command + "\r\n")
            except (BrokenPipeError, OSError) as e:
                self._connected = False
                raise OLTConnectionError(f"SSH channel closed on {self.host}: {e}") from e

            output = await self._read_until_prompt(timeout=timeout)

            # Strip command echo
            lines = output.split("\n")
            if lines and command.strip() in lines[0]:
                lines = lines[1:]
            result = "\n".join(lines).strip()

            # Check for errors
            for pattern in ERROR_PATTERNS:
                if re.search(pattern, result):
                    raise OLTCommandError(
                        f"OLT command error: {result}",
                        command=command,
                        raw_output=result,
                    )

            logger.debug("ssh_response", host=self.host, output=result[:200])
            return result

    async def execute_config_mode(self, commands: list[str]) -> list[str]:
        results = []
        await self.execute("configure terminal")
        try:
            for cmd in commands:
                result = await self.execute(cmd)
                results.append(result)
        finally:
            try:
                await self.execute("end")
            except Exception:
                pass
        return results

    # ------------------------------------------------------------------
    # Low-level read helpers
    # ------------------------------------------------------------------

    async def _read_until_prompt(self, timeout: float) -> str:
        if not self._reader:
            raise OLTConnectionError("No active Telnet connection")
        buffer = ""
        end_time = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = end_time - asyncio.get_event_loop().time()
            if remaining <= 0:
                if PROMPT_PATTERN.search(buffer):
                    return buffer
                raise OLTTimeoutError(
                    f"Timeout waiting for OLT prompt after {timeout}s"
                )
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(4096), timeout=min(remaining, 5.0)
                )
                if not chunk:
                    raise OLTConnectionError("Telnet connection closed by remote host")
                buffer += _strip_iac(chunk).decode("ascii", errors="replace")
                if PROMPT_PATTERN.search(buffer):
                    return buffer
            except asyncio.TimeoutError:
                if PROMPT_PATTERN.search(buffer):
                    return buffer
                if asyncio.get_event_loop().time() >= end_time:
                    raise OLTTimeoutError(
                        f"Timeout waiting for OLT prompt after {timeout}s"
                    )

    async def _read_until_any(self, markers: list[str], timeout: float) -> str:
        if not self._reader:
            return ""
        buffer = ""
        end_time = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end_time:
            remaining = end_time - asyncio.get_event_loop().time()
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(4096), timeout=min(remaining, 1.0)
                )
                if chunk:
                    buffer += _strip_iac(chunk).decode("ascii", errors="replace")
                    if any(m in buffer for m in markers):
                        return buffer
            except asyncio.TimeoutError:
                if any(m in buffer for m in markers):
                    return buffer
                break
        return buffer

    # ------------------------------------------------------------------
    # Properties / context manager
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()
