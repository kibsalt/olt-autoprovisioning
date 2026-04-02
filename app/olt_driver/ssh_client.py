import asyncio
import re

import asyncssh
import structlog

from app.olt_driver.exceptions import OLTCommandError, OLTConnectionError, OLTTimeoutError

logger = structlog.get_logger()

# Match ZTE prompts in all modes:
#   HOSTNAME#                         (privileged EXEC)
#   HOSTNAME>                         (user EXEC)
#   HOSTNAME(config)#                 (global config)
#   HOSTNAME(config-if)#              (interface config)
#   HOSTNAME(config-gpon-onu)#        (GPON ONU config)
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

# Legacy SSH algorithms required by older ZTE OLTs (C300/C320)
_LEGACY_KEX = [
    "diffie-hellman-group14-sha256",
    "diffie-hellman-group14-sha1",
    "diffie-hellman-group1-sha1",
    "diffie-hellman-group-exchange-sha256",
    "diffie-hellman-group-exchange-sha1",
]
_LEGACY_CIPHERS = [
    "aes128-ctr", "aes256-ctr", "aes128-cbc", "aes256-cbc", "3des-cbc",
]
_LEGACY_HOST_KEY_ALGS = ["ssh-rsa", "ssh-dss"]
_LEGACY_MACS = ["hmac-sha2-256", "hmac-sha1", "hmac-md5"]


class OLTSSHClient:
    """Async SSH client for ZTE OLT CLI interaction."""

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
        self.port = port
        self.username = username
        self.password = password
        self.enable_password = enable_password
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self._conn: asyncssh.SSHClientConnection | None = None
        self._process: asyncssh.SSHClientProcess | None = None
        self._lock = asyncio.Lock()
        self._connected = False

    async def connect(self) -> None:
        try:
            self._conn = await asyncio.wait_for(
                asyncssh.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    known_hosts=None,
                    server_host_key_algs=_LEGACY_HOST_KEY_ALGS,
                    kex_algs=_LEGACY_KEX,
                    encryption_algs=_LEGACY_CIPHERS,
                    mac_algs=_LEGACY_MACS,
                ),
                timeout=self.connect_timeout,
            )
            self._process = await self._conn.create_process(
                term_type="vt100",
                term_size=(200, 50),
                request_pty="force",
            )
            # Wait for initial prompt (may be > or #)
            await self._read_until_prompt(timeout=self.connect_timeout)

            # If we landed on user EXEC (>) and have an enable password, escalate
            if self.enable_password and not await self._is_privileged():
                await self._enter_privileged_mode()

            self._connected = True

            # Disable pagination — ignore AAA denial gracefully
            try:
                await self.execute("terminal length 0")
            except (OLTCommandError, OLTConnectionError):
                pass
            logger.info("ssh_connected", host=self.host, port=self.port)
        except asyncio.TimeoutError as e:
            raise OLTConnectionError(
                f"Connection to {self.host}:{self.port} timed out"
            ) from e
        except (OSError, asyncssh.Error) as e:
            raise OLTConnectionError(
                f"Failed to connect to {self.host}:{self.port}: {e}"
            ) from e

    async def _is_privileged(self) -> bool:
        """Send a blank line and check whether the prompt ends with #."""
        if not self._process:
            return False
        self._process.stdin.write("\n")
        buf = await self._read_until_prompt(timeout=3)
        return bool(PRIV_PROMPT_PATTERN.search(buf))

    async def _enter_privileged_mode(self) -> None:
        """Run enable + password to reach privileged EXEC (#) prompt."""
        if not self._process:
            return
        self._process.stdin.write("enable\n")
        buf = await self._read_until_any(["Password", "#", ">"], timeout=5)
        if "Password" in buf:
            self._process.stdin.write(self.enable_password + "\n")
            buf = await self._read_until_any(["#", ">", "Bad password"], timeout=5)
            if "Bad password" in buf or "#" not in buf:
                raise OLTConnectionError(
                    f"Enable password rejected on {self.host}"
                )
        logger.info("ssh_privileged", host=self.host)

    async def _read_until_any(self, markers: list[str], timeout: float) -> str:
        if not self._process:
            return ""
        buffer = ""
        end_time = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end_time:
            remaining = end_time - asyncio.get_event_loop().time()
            try:
                chunk = await asyncio.wait_for(
                    self._process.stdout.read(4096), timeout=min(remaining, 1.0)
                )
                if chunk:
                    buffer += chunk
                    if any(m in buffer for m in markers):
                        return buffer
            except asyncio.TimeoutError:
                if any(m in buffer for m in markers):
                    return buffer
                break
        return buffer

    async def disconnect(self) -> None:
        if self._process:
            self._process.close()
            self._process = None
        if self._conn:
            self._conn.close()
            self._conn = None
        self._connected = False
        logger.info("ssh_disconnected", host=self.host)

    async def execute(
        self, command: str, timeout: float | None = None
    ) -> str:
        if not self._connected or not self._process:
            raise OLTConnectionError("Not connected to OLT")

        timeout = timeout or self.command_timeout
        async with self._lock:
            logger.debug("ssh_command", host=self.host, command=command)
            try:
                self._process.stdin.write(command + "\n")
            except (BrokenPipeError, OSError, asyncssh.Error) as e:
                self._connected = False
                raise OLTConnectionError(f"SSH channel closed on {self.host}: {e}") from e
            output = await self._read_until_prompt(timeout=timeout)
            # Remove the command echo from output
            lines = output.split("\n")
            if lines and command in lines[0]:
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
            # Use 'end' instead of 'exit' — exits from ANY config sub-mode back to EXEC#
            # so a failed mid-sequence command never leaves the session stranded in config mode
            try:
                await self.execute("end")
            except Exception:
                pass
        return results

    async def _read_until_prompt(self, timeout: float) -> str:
        if not self._process:
            raise OLTConnectionError("No active SSH process")

        buffer = ""
        try:
            end_time = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = end_time - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                try:
                    chunk = await asyncio.wait_for(
                        self._process.stdout.read(4096),
                        timeout=min(remaining, 5.0),
                    )
                    if not chunk:
                        raise OLTConnectionError("SSH connection closed")
                    buffer += chunk
                    if PROMPT_PATTERN.search(buffer):
                        return buffer
                except asyncio.TimeoutError:
                    if PROMPT_PATTERN.search(buffer):
                        return buffer
                    if remaining <= 0:
                        raise
        except asyncio.TimeoutError as e:
            raise OLTTimeoutError(
                f"Timeout waiting for OLT prompt after {timeout}s"
            ) from e

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.disconnect()
