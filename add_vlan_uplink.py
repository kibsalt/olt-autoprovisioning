"""Add VLAN 2918 to the uplink trunk port and verify."""
import paramiko

SERVER = "192.168.14.4"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"

OLT_SCRIPT = r'''
import asyncssh, asyncio, re, time

PROMPT = re.compile(r'[A-Za-z0-9_\-\.]+(?:\([^)]*\))?[#>]\s*$')

async def rp(proc, t=15):
    buf = ''
    end = time.time() + t
    while time.time() < end:
        try:
            c = await asyncio.wait_for(proc.stdout.read(4096), timeout=2)
            if c: buf += c
            if PROMPT.search(buf): return buf
        except asyncio.TimeoutError:
            if PROMPT.search(buf): return buf
    return buf

async def run(proc, cmd, t=15):
    proc.stdin.write(cmd + '\n')
    out = await rp(proc, t)
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out)

async def main():
    conn = await asyncssh.connect('192.168.248.10', port=22, username='alex', password='alex321',
        known_hosts=None,
        server_host_key_algs=['ssh-rsa','ssh-dss'],
        kex_algs=['diffie-hellman-group14-sha256','diffie-hellman-group14-sha1','diffie-hellman-group1-sha1'],
        encryption_algs=['aes128-ctr','aes256-ctr','aes128-cbc','aes256-cbc'],
        mac_algs=['hmac-sha2-256','hmac-sha1'])
    proc = await conn.create_process(term_type='vt100', term_size=(200,50), request_pty='force')
    await rp(proc)
    proc.stdin.write('enable\n')
    await asyncio.sleep(0.3)
    buf = await rp(proc, 5)
    if 'Password' in buf:
        proc.stdin.write('zxr10\n')
        await rp(proc, 5)
    await run(proc, 'terminal length 0', 3)

    # 1. Find uplink interfaces (HUTQ slot 22)
    print('=== UPLINK INTERFACES (slot 22 - HUTQ) ===')
    out = await run(proc, 'show running-config | include "interface xgei"', 10)
    print(out)

    # Show all uplink port configs
    for port in range(1, 5):
        out = await run(proc, f'show running-config interface xgei_1/22/{port}', 10)
        if 'switchport' in out or 'vlan' in out:
            print(f'\n=== xgei_1/22/{port} ===')
            print(out)

    # Also check gei interfaces
    out = await run(proc, 'show running-config | include "interface gei"', 10)
    for l in out.split('\n'):
        if 'interface gei' in l:
            print(l.strip())

    # Find which interface has switchport vlan with 3331 (the working VLAN)
    print('\n=== INTERFACES WITH VLAN 3331 (working ONU uses this) ===')
    out = await run(proc, 'show running-config | include "switchport vlan.*3331"', 10)
    print(out)

    # Find all interfaces with switchport vlan tag
    print('\n=== ALL TRUNK CONFIGS ===')
    out = await run(proc, 'show running-config | include "switchport vlan"', 10)
    for l in out.split('\n'):
        l = l.strip()
        if 'switchport vlan' in l and l != 'show running-config | include "switchport vlan"':
            print(f'  {l}')

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
sftp = client.open_sftp()
with sftp.open("/tmp/uplink.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()
_, stdout, _ = client.exec_command(
    "docker cp /tmp/uplink.py jtl_olt_api:/tmp/uplink.py && docker exec jtl_olt_api python /tmp/uplink.py 2>&1",
    timeout=120)
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
print(stdout.read().decode(errors='replace'))
client.close()
