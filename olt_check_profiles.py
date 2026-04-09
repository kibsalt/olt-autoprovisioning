"""Check DBA profiles, traffic tables, ONU types, and VLANs on the test C300."""
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


async def read_until(process, markers, timeout=10):
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


async def cmd(proc, command, timeout=10):
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

    print("=== DBA Profiles ===")
    out = await cmd(proc, "show gpon dba-profile all", timeout=10)
    print(out[:2000] or "(none)")

    print("\n=== ONU Types ===")
    out = await cmd(proc, "show gpon onu-type all", timeout=10)
    print(out[:2000] or "(none)")

    print("\n=== Traffic Tables ===")
    out = await cmd(proc, "show traffic-table ip all", timeout=10)
    print(out[:2000] or "(none)")

    print("\n=== Existing ONU config on port 1/7/2 ===")
    out = await cmd(proc, "show running-config interface gpon-olt_1/7/2", timeout=10)
    print(out[:2000] or "(none)")

    # Test simulate minimal provisioning commands
    print("\n=== Testing ONU authorize syntax (dry run — show only) ===")
    # First check what ONU IDs are in use on 1/7/2
    out = await cmd(proc, "show gpon onu all gpon-olt_1/7/2", timeout=10)
    print("Existing ONUs on 1/7/2:")
    print(out[:1000] or "(none)")

    print("\n=== VLAN service ports ===")
    out = await cmd(proc, "show gpon service-port all", timeout=10)
    print(out[:2000] or "(none)")

    conn.close()

asyncio.run(main())
