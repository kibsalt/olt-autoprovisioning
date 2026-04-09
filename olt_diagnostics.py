"""
SSH into ZTE C300 OLT and discover card/port layout and unregistered ONUs.
Uses legacy SSH algorithms required by older ZTE hardware.
"""
import asyncio
import asyncssh

OLT_HOST = "192.168.248.10"
OLT_USER = "alex"
OLT_PASS = "alex321"
ENABLE_PASS = "zxr10"

_LEGACY_KEX = [
    "diffie-hellman-group14-sha256",
    "diffie-hellman-group14-sha1",
    "diffie-hellman-group1-sha1",
    "diffie-hellman-group-exchange-sha256",
    "diffie-hellman-group-exchange-sha1",
]
_LEGACY_CIPHERS = ["aes128-ctr", "aes256-ctr", "aes128-cbc", "aes256-cbc", "3des-cbc"]
_LEGACY_HOST_KEY_ALGS = ["ssh-rsa", "ssh-dss"]
_LEGACY_MACS = ["hmac-sha2-256", "hmac-sha1", "hmac-md5"]


async def read_until_any(process, markers, timeout=10):
    buffer = ""
    loop = asyncio.get_event_loop()
    end_time = loop.time() + timeout
    while loop.time() < end_time:
        remaining = end_time - loop.time()
        try:
            chunk = await asyncio.wait_for(
                process.stdout.read(4096), timeout=min(remaining, 1.0)
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


async def run_command(process, cmd, timeout=15):
    process.stdin.write(cmd + "\n")
    buf = await read_until_any(process, ["#", ">"], timeout=timeout)
    # strip the command echo
    lines = buf.split("\n")
    if lines and cmd in lines[0]:
        lines = lines[1:]
    return "\n".join(lines).strip()


async def main():
    print(f"Connecting to OLT at {OLT_HOST}...")
    conn = await asyncssh.connect(
        OLT_HOST,
        port=22,
        username=OLT_USER,
        password=OLT_PASS,
        known_hosts=None,
        server_host_key_algs=_LEGACY_HOST_KEY_ALGS,
        kex_algs=_LEGACY_KEX,
        encryption_algs=_LEGACY_CIPHERS,
        mac_algs=_LEGACY_MACS,
    )
    print("Connected. Opening shell...")
    process = await conn.create_process(term_type="vt100", term_size=(200, 50), request_pty="force")

    # Wait for initial prompt
    buf = await read_until_any(process, ["#", ">", "Password"], timeout=10)
    print(f"Initial: {buf[-50:]!r}")

    # Enter enable mode if needed
    if ">" in buf:
        process.stdin.write("enable\n")
        buf = await read_until_any(process, ["Password", "#"], timeout=5)
        if "Password" in buf:
            process.stdin.write(ENABLE_PASS + "\n")
            buf = await read_until_any(process, ["#", ">"], timeout=5)
    print(f"After enable: {buf[-30:]!r}")

    # Disable paging
    process.stdin.write("terminal length 0\n")
    await read_until_any(process, ["#"], timeout=5)

    # Show card layout
    print("\n=== show card ===")
    out = await run_command(process, "show card", timeout=10)
    print(out)

    # Show running-config for gpon interfaces to find active slots
    print("\n=== show running-config | include gpon-olt ===")
    out = await run_command(process, "show running-config | include gpon-olt", timeout=15)
    print(out[:3000])

    # Try to list unconfigured ONUs on common slots
    print("\n=== Scanning for unregistered ONUs ===")
    for slot in range(1, 10):
        for port in range(0, 8):
            cmd = f"show gpon onu uncfg gpon-olt_1/{slot}/{port}"
            out = await run_command(process, cmd, timeout=5)
            if out and "%" not in out and len(out.strip()) > 5 and "uncfg" not in out.lower():
                print(f"\nSlot {slot} Port {port}:")
                print(out[:500])

    conn.close()
    print("\nDone.")


asyncio.run(main())
