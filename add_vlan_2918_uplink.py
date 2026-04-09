"""Add VLAN 2918 to uplink xgei_1/22/1 trunk and verify PPPoE comes up."""
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

    # Add VLAN 2918 to uplink trunk
    print('Adding VLAN 2918 to uplink xgei_1/22/1...')
    cmds = [
        'configure terminal',
        'interface xgei_1/22/1',
        'switchport vlan 1,153,2918,3331 tag',
        'exit',
        'end',
    ]
    for cmd in cmds:
        out = await run(proc, cmd, 10)
        clean = out.strip()
        if 'Error' in clean:
            print(f'ERROR [{cmd}]: {clean[-200:]}')
        else:
            print(f'OK: {cmd}')

    # Verify
    out = await run(proc, 'show running-config interface xgei_1/22/1', 10)
    print('\n=== UPLINK CONFIG AFTER ===')
    for l in out.split('\n'):
        l = l.strip()
        if 'switchport vlan' in l:
            print(f'  {l}')

    # Wait for PPPoE to dial on ONU:3
    print('\nWaiting 20s for PPPoE session to establish...')
    await asyncio.sleep(20)

    out = await run(proc, 'show gpon remote-onu ip-host gpon-onu_1/9/2:3', 10)
    print('\n=== ONU:3 IP HOST ===')
    for l in out.split('\n'):
        l = l.strip()
        if any(k in l for k in ['Host ID:            1', 'IP addres', 'Current IP', 'Current mask', 'Current gateway', 'Current primary', 'MAC address']):
            print(f'  {l}')
        if 'Host ID:            2' in l:
            break

    # If still no IP, wait more
    if '0.0.0.0' in out.split('Host ID:            2')[0] if 'Host ID:            2' in out else out:
        has_ip = False
        for l in out.split('\n'):
            if 'Current IP address' in l and '0.0.0.0' not in l:
                has_ip = True
        if not has_ip:
            print('\nStill no IP, waiting another 30s...')
            await asyncio.sleep(30)
            out = await run(proc, 'show gpon remote-onu ip-host gpon-onu_1/9/2:3', 10)
            print('\n=== ONU:3 IP HOST (2nd check) ===')
            for l in out.split('\n'):
                l = l.strip()
                if any(k in l for k in ['Host ID:            1', 'IP addres', 'Current IP', 'Current mask', 'Current gateway', 'Current primary', 'MAC address']):
                    print(f'  {l}')
                if 'Host ID:            2' in l:
                    break

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
sftp = client.open_sftp()
with sftp.open("/tmp/add_vlan.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()
_, stdout, _ = client.exec_command(
    "docker cp /tmp/add_vlan.py jtl_olt_api:/tmp/add_vlan.py && docker exec jtl_olt_api python /tmp/add_vlan.py 2>&1",
    timeout=180)
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
print(stdout.read().decode(errors='replace'))
client.close()
