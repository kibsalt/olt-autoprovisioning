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
_NAWS = 0x1F   # option: Negotiate About Window Size
_TTYPE = 0x18  # option: Terminal Type

# Tell the OLT our terminal is 200 columns wide so long commands aren't wrapped.
# IAC WILL NAWS + IAC SB NAWS <width_hi> <width_lo> <height_hi> <height_lo> IAC SE
_NAWS_ANNOUNCE = (
    bytes([_IAC, _WILL, _NAWS]) +
    bytes([_IAC, _SB, _NAWS, 0x00, 200, 0x00, 50, _IAC, _SE])
)


def _respond_iac(data: bytes) -> bytes:
    """Generate WONT/DONT replies for all incoming DO/WILL Telnet negotiations.
    Exception: accept DO NAWS by sending our window size subnegotiation."""
    resp = bytearray()
    i = 0
    while i < len(data):
        if data[i] == _IAC and i + 2 < len(data):
            cmd, opt = data[i + 1], data[i + 2]
            if cmd == _DO and opt == _NAWS:
                # Server wants to know our window size — send WILL NAWS + size
                resp += bytes([_IAC, _WILL, _NAWS])
                resp += bytes([_IAC, _SB, _NAWS, 0x00, 200, 0x00, 50, _IAC, _SE])
            elif cmd == _DO:
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


def _clean_telnet_output(text: str) -> str:
    """Remove backspace sequences and reflow artifacts from Telnet echo.

    ZTE OLTs in Telnet mode echo commands back with \x08 (backspace) sequences
    that split long lines — e.g. 'show running-config inter\x08\x08...' — which
    corrupt the output and falsely match error patterns.  Strip all backspace
    processing so only the actual OLT response remains.
    """
    # Remove any \x08-based line reflow: process backspaces character by character
    result = []
    for ch in text:
        if ch == '\x08':
            if result:
                result.pop()
        else:
            result.append(ch)
    cleaned = ''.join(result)
    # Also strip lines that are purely the echoed command (contain no newline content)
    lines = cleaned.split('\n')
    out_lines = []
    for line in lines:
        # Drop lines that still contain raw backspace or are pure whitespace artifacts
        if '\x08' not in line:
            out_lines.append(line)
    return '\n'.join(out_lines)


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

            logger.info("telnet_connected", host=self.host, port=self.port)

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
            else:
                # Proactively announce our window size so the OLT doesn't wrap long commands
                self._writer.write(_NAWS_ANNOUNCE)
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
        logger.info("telnet_disconnected", host=self.host)

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
        try:
            self._writer.write(text.encode("ascii", errors="replace"))
        except (BrokenPipeError, OSError, RuntimeError) as e:
            self._connected = False
            raise OLTConnectionError(f"Telnet connection lost on {self.host}: {e}") from e

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

            # Clean Telnet echo artifacts (backspace sequences from OLT line reflow)
            output = _clean_telnet_output(output)

            # Strip command echo
            lines = output.split("\n")
            if lines and command.strip() in lines[0]:
                lines = lines[1:]
            result = "\n".join(lines).strip()

            # Check for errors — only in lines that don't contain the echoed command
            clean_for_errors = "\n".join(
                l for l in result.split("\n") if command[:20] not in l
            )
            for pattern in ERROR_PATTERNS:
                if re.search(pattern, clean_for_errors):
                    raise OLTCommandError(
                        f"OLT command error: {result}",
                        command=command,
                        raw_output=result,
                    )

            logger.debug("ssh_response", host=self.host, output=result[:200])
            return result

    async def execute_config_mode(
        self, commands: list[str], cmd_timeout: float | None = None
    ) -> list[str]:
        """Execute a batch of config-mode commands in a single locked session.

        Holds self._lock for the entire configure-terminal … end block so that
        the alarm poller (or any other concurrent caller) cannot inject commands
        in the middle of a multi-step config sequence.  Previously the lock was
        released between every command, allowing interleaving that would corrupt
        the CLI context and make each subsequent command unpredictably slow.
        """
        if not self._connected or not self._writer:
            raise OLTConnectionError("Not connected to OLT")

        t_cmd = cmd_timeout or self.command_timeout

        async with self._lock:          # ← hold for entire session
            results: list[str] = []

            # Enter config mode
            self._write("configure terminal\r\n")
            await self._read_until_prompt(timeout=self.command_timeout)

            try:
                for cmd in commands:
                    t0 = asyncio.get_event_loop().time()
                    self._write(cmd + "\r\n")
                    raw = await self._read_until_prompt(timeout=t_cmd)
                    elapsed = asyncio.get_event_loop().time() - t0
                    if elapsed > 2.0:
                        logger.warning(
                            "slow_config_cmd",
                            cmd=cmd[:60],
                            elapsed_s=round(elapsed, 2),
                            host=self.host,
                        )

                    raw = _clean_telnet_output(raw)
                    lines = raw.split("\n")
                    if lines and cmd.strip() in lines[0]:
                        lines = lines[1:]
                    result = "\n".join(lines).strip()

                    # Error check (skip lines that merely echo the command)
                    clean_for_errors = "\n".join(
                        l for l in result.split("\n") if cmd[:20] not in l
                    )
                    for pattern in ERROR_PATTERNS:
                        if re.search(pattern, clean_for_errors):
                            raise OLTCommandError(
                                f"Config-mode error: {result}",
                                command=cmd,
                                raw_output=result,
                            )
                    results.append(result)
            finally:
                try:
                    self._write("end\r\n")
                    await self._read_until_prompt(timeout=self.command_timeout)
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
        if not self._connected:
            return False
        # Check if the underlying TCP transport is still alive
        if self._writer is None or self._writer.is_closing():
            self._connected = False
            return False
        return True

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()
