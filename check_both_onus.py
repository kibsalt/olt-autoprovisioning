"""Emergency check — verify ONU:1 and ONU:3 state, uplink config, both VLANs."""
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

    # 1. ONU states
    print('=== ONU STATES ===')
    out = await run(proc, 'show gpon onu state gpon-olt_1/9/2')
    for l in out.split('\n'):
        if 'gpon-onu' in l or 'OnuIndex' in l or '---' in l or 'ONU Number' in l:
            print(f'  {l.strip()}')

    # 2. Uplink trunk config
    print('\n=== UPLINK xgei_1/22/1 ===')
    out = await run(proc, 'show running-config interface xgei_1/22/1')
    for l in out.split('\n'):
        if 'switchport' in l or 'shutdown' in l:
            print(f'  {l.strip()}')

    # 3. ONU:1 interface config (ZTEGD139764E - was working on VLAN 3331)
    print('\n=== ONU:1 ZTEGD139764E interface config ===')
    out = await run(proc, 'show running-config interface gpon-onu_1/9/2:1')
    for l in out.split('\n'):
        l = l.strip()
        if l and 'show running' not in l and 'Building' not in l and 'TESTAUTOPROV' not in l and l != 'end':
            print(f'  {l}')

    # 4. ONU:1 pon-onu-mng
    print('\n=== ONU:1 pon-onu-mng ===')
    out = await run(proc, 'show running-config | begin pon-onu-mng gpon-onu_1/9/2:1', 10)
    capture = False
    for l in out.split('\n'):
        stripped = l.strip()
        if 'pon-onu-mng gpon-onu_1/9/2:1' in l:
            capture = True
            print(f'  {stripped}')
        elif capture and stripped == '!':
            break
        elif capture and 'pon-onu-mng gpon-onu_1/9/2:2' in l:
            break
        elif capture and stripped and 'TESTAUTOPROV' not in stripped:
            print(f'  {stripped}')

    # 5. ONU:1 IP host
    print('\n=== ONU:1 IP HOST ===')
    out = await run(proc, 'show gpon remote-onu ip-host gpon-onu_1/9/2:1', 10)
    for l in out.split('\n'):
        l = l.strip()
        if any(k in l for k in ['Host ID:            1', 'IP addres', 'Current IP', 'Current gateway', 'MAC address', 'Host name']):
            print(f'  {l}')
        if 'Host ID:            2' in l:
            break

    # 6. ONU:3 IP host
    print('\n=== ONU:3 ZTEGD1397E71 IP HOST ===')
    out = await run(proc, 'show gpon remote-onu ip-host gpon-onu_1/9/2:3', 10)
    for l in out.split('\n'):
        l = l.strip()
        if any(k in l for k in ['Host ID:            1', 'IP addres', 'Current IP', 'Current gateway', 'MAC address', 'Host name']):
            print(f'  {l}')
        if 'Host ID:            2' in l:
            break

    # 7. Check VLAN membership
    print('\n=== VLAN 3331 membership ===')
    out = await run(proc, 'show vlan 3331')
    for l in out.split('\n'):
        l = l.strip()
        if l and 'show vlan' not in l and 'TESTAUTOPROV' not in l:
            print(f'  {l}')

    print('\n=== VLAN 2918 membership ===')
    out = await run(proc, 'show vlan 2918')
    for l in out.split('\n'):
        l = l.strip()
        if l and 'show vlan' not in l and 'TESTAUTOPROV' not in l:
            print(f'  {l}')

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
sftp = client.open_sftp()
with sftp.open("/tmp/check_both.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()
_, stdout, _ = client.exec_command(
    "docker cp /tmp/check_both.py jtl_olt_api:/tmp/check_both.py && "
    "docker exec jtl_olt_api python /tmp/check_both.py 2>&1",
    timeout=120)
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
print(stdout.read().decode(errors='replace'))
client.close()
