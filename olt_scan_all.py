"""Scan all GPON ports on slots 7 and 9 of the test C300."""
import asyncio
import asyncssh

OLT_HOST = "192.168.248.10"
OLT_USER = "alex"
OLT_PASS = "alex321"
ENABLE_PASS = "zxr10"

_LEGACY_KEX = [
    "diffie-hellman-group14-sha256", "diffie-hellman-group14-sha1",
    "diffie-hellman-group1-sha1",
]
_LEGACY_CIPHERS = ["aes128-ctr", "aes256-ctr", "aes128-cbc", "3des-cbc"]
_LEGACY_HOST_KEY_ALGS = ["ssh-rsa", "ssh-dss"]
_LEGACY_MACS = ["hmac-sha2-256", "hmac-sha1"]


async def read_until(process, markers, timeout=8):
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


async def cmd(process, command, timeout=8):
    process.stdin.write(command + "\n")
    buf = await read_until(process, ["#"], timeout=timeout)
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

    print("Scanning all GPON ports...\n")
    all_onus = []

    # Slot 7: 8 ports (0-7)
    for port in range(8):
        out = await cmd(proc, f"show gpon onu uncfg gpon-olt_1/7/{port}", timeout=6)
        lines = [l for l in out.split("\n") if "gpon-onu" in l.lower() or (len(l.strip()) > 5 and "-----" not in l and "OnuIndex" not in l and "TESTAUTOPROV" not in l)]
        if lines:
            print(f"Slot 7 Port {port}:")
            for l in lines:
                print(f"  {l.strip()}")
                all_onus.append((7, port, l.strip()))

    # Slot 9: 16 ports (0-15)
    for port in range(16):
        out = await cmd(proc, f"show gpon onu uncfg gpon-olt_1/9/{port}", timeout=6)
        lines = [l for l in out.split("\n") if "gpon-onu" in l.lower() or (len(l.strip()) > 5 and "-----" not in l and "OnuIndex" not in l and "TESTAUTOPROV" not in l)]
        if lines:
            print(f"Slot 9 Port {port}:")
            for l in lines:
                print(f"  {l.strip()}")
                all_onus.append((9, port, l.strip()))

    print(f"\nTotal unconfigured ONUs found: {len(all_onus)}")
    if all_onus:
        print("\nAll serial numbers found:")
        for slot, port, line in all_onus:
            # extract serial from line
            parts = line.split()
            if len(parts) >= 2:
                print(f"  1/{slot}/{port}: {parts[1]}")

    conn.close()

asyncio.run(main())
