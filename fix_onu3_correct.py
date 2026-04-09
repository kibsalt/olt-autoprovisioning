"""Fix ONU:3 with correct C300 PPPoE config matching production reference."""
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

    # Step 1: Fix interface config — add tcont gap mode2
    print('=== Step 1: Fix interface gpon-onu_1/9/2:3 ===')
    iface_cmds = [
        'configure terminal',
        'interface gpon-onu_1/9/2:3',
        'name Service - kplc_test- (KPLC Test)',
        'tcont 1 name Fix_10M profile Fix_10M',
        'tcont 1 gap mode2',
        'gemport 1 name Fix_10M tcont 1 queue 1',
        'switchport mode hybrid vport 1',
        'service-port 1 vport 1 user-vlan 2918 vlan 2918',
        'exit',
        'end',
    ]
    for cmd in iface_cmds:
        out = await run(proc, cmd, 10)
        if 'Error' in out:
            print(f'  ERROR: {cmd} -> {out.strip()[-200:]}')
        else:
            print(f'  OK: {cmd}')

    # Step 2: Fix pon-onu-mng — match production reference exactly
    print('\n=== Step 2: Fix pon-onu-mng gpon-onu_1/9/2:3 ===')
    pon_cmds = [
        'configure terminal',
        'pon-onu-mng gpon-onu_1/9/2:3',
        'interface pon pon_0/1 rx-optical-thresh lower -24.0 upper ont-internal-policy',
        'flow mode 1 tag-filter vlan-filter untag-filter discard',
        'flow 1 pri 0 vlan 2918',
        'gemport 1 flow 1 dot1p-list 0',
        'switchport-bind switch_0/1 iphost 1',
        'pppoe 1 nat enable user kplc password kplc123',
        'vlan-filter-mode iphost 1 tag-filter vlan-filter untag-filter discard',
        'vlan-filter iphost 1 pri 0 vlan 2918',
        'firewall enable level low anti-hack disable',
        'security-mgmt 1 state enable mode forward protocol web',
        'security-mgmt 2 state enable mode forward ingress-type lan protocol web',
        'security-mgmt 3 state enable ingress-type lan protocol telnet',
        'security-mgmt 4 state enable protocol telnet',
        'exit',
        'end',
    ]
    for cmd in pon_cmds:
        out = await run(proc, cmd, 10)
        if 'Error' in out:
            print(f'  ERROR: {cmd} -> {out.strip()[-200:]}')
        else:
            print(f'  OK: {cmd}')

    # Step 3: Verify configs
    print('\n=== Verify: interface config ===')
    out = await run(proc, 'show running-config interface gpon-onu_1/9/2:3')
    for l in out.split('\n'):
        l = l.strip()
        if l and 'show running' not in l and 'Building' not in l and 'TESTAUTOPROV' not in l and l != 'end':
            print(f'  {l}')

    print('\n=== Verify: pon-onu-mng config ===')
    out = await run(proc, 'show running-config | begin pon-onu-mng gpon-onu_1/9/2:3', 10)
    capture = False
    for l in out.split('\n'):
        stripped = l.strip()
        if 'pon-onu-mng gpon-onu_1/9/2:3' in l:
            capture = True
            print(f'  {stripped}')
        elif capture and stripped == '!':
            print(f'  {stripped}')
            break
        elif capture and 'pon-onu-mng' in stripped:
            break
        elif capture and stripped and 'TESTAUTOPROV' not in stripped:
            print(f'  {stripped}')

    # Step 4: Reboot ONU
    print('\n=== Rebooting ONU:3 ===')
    await run(proc, 'configure terminal')
    await run(proc, 'pon-onu-mng gpon-onu_1/9/2:3')
    await run(proc, 'reboot')
    await run(proc, 'exit')
    await run(proc, 'end')

    # Step 5: Wait and check IP
    for label, secs in [('40s', 40), ('30s', 30), ('30s', 30)]:
        print(f'\nWaiting {label}...')
        await asyncio.sleep(secs)

        out = await run(proc, 'show gpon remote-onu ip-host gpon-onu_1/9/2:3', 10)
        ip = '0.0.0.0'
        mac = '—'
        gw = '0.0.0.0'
        dns = '0.0.0.0'
        for l in out.split('\n'):
            if 'Current IP address' in l:
                m = re.search(r'([\d.]+)', l.split(':',1)[1])
                if m: ip = m.group(1)
            if 'Current gateway' in l:
                m = re.search(r'([\d.]+)', l.split(':',1)[1])
                if m: gw = m.group(1)
            if 'Current primary DNS' in l:
                m = re.search(r'([\d.]+)', l.split(':',1)[1])
                if m: dns = m.group(1)
            if 'MAC address' in l:
                m = re.search(r'([0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4})', l, re.I)
                if m: mac = m.group(1)

        state_out = await run(proc, 'show gpon onu state gpon-olt_1/9/2', 5)
        state = '?'
        for l in state_out.split('\n'):
            if '1/9/2:3' in l:
                parts = l.strip().split()
                state = parts[-1] if parts else '?'

        if ip != '0.0.0.0':
            print(f'  GOT IP!  IP: {ip}  GW: {gw}  DNS: {dns}  MAC: {mac}  State: {state}')
            break
        else:
            print(f'  No IP yet.  MAC: {mac}  State: {state}')

    else:
        print('\nPPPoE still not establishing after 100s.')
        print('Next steps: Check BNG has PPPoE service on VLAN 2918, check RADIUS logs for "kplc"')

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
sftp = client.open_sftp()
with sftp.open("/tmp/fix3_correct.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()
_, stdout, _ = client.exec_command(
    "docker cp /tmp/fix3_correct.py jtl_olt_api:/tmp/fix3_correct.py && "
    "docker exec jtl_olt_api python /tmp/fix3_correct.py 2>&1",
    timeout=300)
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
print(stdout.read().decode(errors='replace'))
client.close()
