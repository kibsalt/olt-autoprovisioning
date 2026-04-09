"""Check ACS/TR-069 config on existing ONUs to verify command syntax."""
import asyncio
import asyncssh

OLT_HOST = "192.168.248.10"
OLT_USER = "alex"
OLT_PASS = "alex321"
ENABLE_PASS = "zxr10"

_LEGACY_KEX = ["diffie-hellman-group14-sha256", "diffie-hellman-group14-sha1", "diffie-hellman-group1-sha1"]
_LEGACY_CIPHERS = ["aes128-ctr", "aes256-ctr", "aes128-cbc", "3des-cbc"]
_LEGACY_HOST_KEY_ALGS = ["ssh-rsa", "ssh-dss"]
_LEGACY_MACS = ["hmac-sha2-256", "hmac-sha1"]


async def read_until(process, markers, timeout=12):
    buffer = ""
    loop = asyncio.get_event_loop()
    end_time = loop.time() + timeout
    while loop.time() < end_time:
        remaining = end_time - loop.time()
        try:
            chunk = await asyncio.wait_for(process.stdout.read(4096), timeout=min(remaining, 0.5))
            if chunk:
                buffer += chunk
                if any(m in buffer for m in markers):
                    return buffer
        except asyncio.TimeoutError:
            if any(m in buffer for m in markers):
                return buffer
            break
    return buffer


async def cmd(proc, command, timeout=12):
    proc.stdin.write(command + "\n")
    buf = await read_until(proc, ["#"], timeout=timeout)
    lines = buf.split("\n")
    if lines and command in lines[0]:
        lines = lines[1:]
    return "\n".join(lines).strip()


async def main():
    conn = await asyncssh.connect(
        OLT_HOST, port=22, username=OLT_USER, password=OLT_PASS,
        known_hosts=None, server_host_key_algs=_LEGACY_HOST_KEY_ALGS,
        kex_algs=_LEGACY_KEX, encryption_algs=_LEGACY_CIPHERS, mac_algs=_LEGACY_MACS,
    )
    proc = await conn.create_process(term_type="vt100", term_size=(200, 50), request_pty="force")
    buf = await read_until(proc, ["#", ">"], timeout=8)
    if ">" in buf:
        proc.stdin.write("enable\n")
        buf = await read_until(proc, ["Password", "#"], timeout=5)
        if "Password" in buf:
            proc.stdin.write(ENABLE_PASS + "\n")
            await read_until(proc, ["#"], timeout=5)
    proc.stdin.write("terminal length 0\n")
    await read_until(proc, ["#"], timeout=5)

    # Show full running-config for both existing ONUs including all sub-configs
    print("=== show running-config (all ONU interfaces) ===")
    out = await cmd(proc, "show running-config", timeout=30)
    # Filter for gpon-onu sections
    lines = out.split("\n")
    in_gpon = False
    for line in lines:
        if "gpon-onu" in line or "gpon-olt" in line:
            in_gpon = True
        if in_gpon:
            print(line)
        if in_gpon and line.strip() == "!":
            in_gpon = False

    # Try show detail for ONU 1 and 2
    print("\n=== show gpon onu detail-info gpon-onu_1/7/2:1 ===")
    out = await cmd(proc, "show gpon onu detail-info gpon-onu_1/7/2:1", timeout=10)
    print(out[:3000] or "(none)")

    # Check what commands are available for wan-ip / tr069
    print("\n=== configure terminal + interface gpon-onu_1/7/2:1 + ? ===")
    proc.stdin.write("configure terminal\n")
    await read_until(proc, ["#"], timeout=5)
    proc.stdin.write("interface gpon-onu_1/7/2:1\n")
    await read_until(proc, ["#"], timeout=5)
    proc.stdin.write("wan-ip ?\n")
    buf = await read_until(proc, ["#", ">"], timeout=5)
    print("wan-ip ?:", buf[:500])
    proc.stdin.write("exit\n")
    await read_until(proc, ["#"], timeout=5)
    proc.stdin.write("exit\n")
    await read_until(proc, ["#"], timeout=5)

    conn.close()

asyncio.run(main())
