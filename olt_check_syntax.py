"""Check existing ONU config to understand CLI syntax on this C300 firmware."""
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

    # Check running config of existing gpon-onu interfaces
    for onu_id in [1, 2]:
        print(f"\n=== Running config gpon-onu_1/7/2:{onu_id} ===")
        out = await cmd(proc, f"show running-config interface gpon-onu_1/7/2:{onu_id}", timeout=12)
        print(out[:3000] or "(none)")

    # Check if there's a DBA section in running-config
    print("\n=== show running-config | include dba ===")
    out = await cmd(proc, "show running-config | include dba", timeout=12)
    print(out[:2000] or "(none)")

    # Show full running-config for dba profiles
    print("\n=== show running-config | include tcont ===")
    out = await cmd(proc, "show running-config | include tcont", timeout=12)
    print(out[:2000] or "(none)")

    print("\n=== show running-config | include traffic-table ===")
    out = await cmd(proc, "show running-config | include traffic-table", timeout=12)
    print(out[:2000] or "(none)")

    print("\n=== show running-config | include service-port ===")
    out = await cmd(proc, "show running-config | include service-port", timeout=12)
    print(out[:2000] or "(none)")

    # Try alternate DBA profile commands
    print("\n=== show dba-profile all ===")
    out = await cmd(proc, "show dba-profile all", timeout=8)
    print(out[:500] or "(none)")

    print("\n=== show gpon dba-profile ===")
    out = await cmd(proc, "show gpon dba-profile", timeout=8)
    print(out[:500] or "(none)")

    # Check ONU types
    print("\n=== show ont-type all ===")
    out = await cmd(proc, "show ont-type all", timeout=8)
    print(out[:1000] or "(none)")

    print("\n=== show onu-type all ===")
    out = await cmd(proc, "show onu-type all", timeout=8)
    print(out[:1000] or "(none)")

    # Check uplink service-port syntax
    print("\n=== show running-config | section uplink ===")
    out = await cmd(proc, "show running-config | section uplink", timeout=12)
    print(out[:2000] or "(none)")

    conn.close()

asyncio.run(main())
