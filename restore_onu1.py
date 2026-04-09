"""Restore ONU:1 ZTEGD139764E on the OLT with its original config."""
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

    # Check current state
    print('=== CURRENT PORT STATE ===')
    out = await run(proc, 'show running-config interface gpon-olt_1/9/2')
    for l in out.split('\n'):
        l = l.strip()
        if 'onu' in l.lower() or 'interface' in l.lower() and 'gpon' in l.lower():
            print(f'  {l}')

    # Step 1: Re-register ONU:1 on the PON port
    print('\n=== Restoring ONU:1 ZTEGD139764E ===')
    cmds = [
        'configure terminal',
        # Register ONU
        'interface gpon-olt_1/9/2',
        'onu 1 type ZTE-F660 sn ZTEGD139764E',
        'exit',
        # Interface config (matching original)
        'interface gpon-onu_1/9/2:1',
        'name Service #40718 - Engineering_test_2- (MISOFFICELINKS MISOFFICELINKS)',
        'tcont 1 name Fix_75M profile Fix_75M',
        'tcont 1 gap mode2',
        'gemport 1 name Fix_75M tcont 1 queue 1',
        'switchport mode hybrid vport 1',
        'service-port 1 vport 1 user-vlan 3331 vlan 3331',
        'exit',
        # pon-onu-mng (matching original)
        'pon-onu-mng gpon-onu_1/9/2:1',
        'flow mode 1 tag-filter vlan-filter untag-filter discard',
        'flow 1 pri 0 vlan 3331',
        'gemport 1 flow 1 dot1p-list 0',
        'switchport-bind switch_0/1 iphost 1',
        'pppoe 1 nat enable user Engineering_test_2 password Engineering_Test_2',
        'vlan-filter-mode iphost 1 tag-filter vlan-filter untag-filter discard',
        'vlan-filter iphost 1 pri 0 vlan 3331',
        'firewall enable level low anti-hack enable',
        'security-mgmt 1 state enable protocol web tr069',
        'security-mgmt 2 state enable ingress-type lan protocol web',
        'security-mgmt 3 state enable ingress-type lan protocol telnet',
        'security-mgmt 4 state enable protocol telnet',
        'exit',
        'end',
    ]
    for cmd in cmds:
        out = await run(proc, cmd, 10)
        if 'Error' in out:
            print(f'  ERROR: {cmd} -> {out.strip()[-200:]}')
        else:
            print(f'  OK: {cmd}')

    # Verify
    print('\n=== Verify ONU:1 interface ===')
    out = await run(proc, 'show running-config interface gpon-onu_1/9/2:1')
    for l in out.split('\n'):
        l = l.strip()
        if l and 'show running' not in l and 'Building' not in l and 'TESTAUTOPROV' not in l and l != 'end':
            print(f'  {l}')

    # Check all ONU states
    print('\n=== ALL ONU STATES ===')
    out = await run(proc, 'show gpon onu state gpon-olt_1/9/2')
    for l in out.split('\n'):
        if 'gpon-onu' in l or 'OnuIndex' in l or 'ONU Number' in l:
            print(f'  {l.strip()}')

    # Wait for ONU:1 to come online and get IP
    print('\nWaiting 40s for ONU:1 PPPoE...')
    await asyncio.sleep(40)

    out = await run(proc, 'show gpon remote-onu ip-host gpon-onu_1/9/2:1', 10)
    ip = '0.0.0.0'
    for l in out.split('\n'):
        if 'Current IP address' in l:
            m = re.search(r'([\d.]+)', l.split(':',1)[1])
            if m: ip = m.group(1)

    if ip != '0.0.0.0':
        print(f'  ONU:1 GOT IP: {ip}')
    else:
        print(f'  ONU:1 still no IP - checking state...')
        out = await run(proc, 'show gpon onu state gpon-olt_1/9/2')
        for l in out.split('\n'):
            if '1/9/2:1' in l:
                print(f'  {l.strip()}')
        out = await run(proc, 'show gpon remote-onu ip-host gpon-onu_1/9/2:1', 10)
        for l in out.split('\n'):
            l = l.strip()
            if any(k in l for k in ['Current IP', 'MAC address', 'Host name']):
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
with sftp.open("/tmp/restore1.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()
_, stdout, _ = client.exec_command(
    "docker cp /tmp/restore1.py jtl_olt_api:/tmp/restore1.py && "
    "docker exec jtl_olt_api python /tmp/restore1.py 2>&1",
    timeout=180)
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
print(stdout.read().decode(errors='replace'))
client.close()
