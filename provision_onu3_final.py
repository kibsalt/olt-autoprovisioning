"""Push missing tcont/gemport/service-port + fix pon-onu-mng for ONU:3 ZTEGD1397E71."""
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
    proc.stdin.write('terminal length 0\n')
    await rp(proc, 3)

    # Step 1: Configure interface gpon-onu_1/9/2:3 — add tcont, gemport, switchport, service-port
    commands = [
        'configure terminal',
        'interface gpon-onu_1/9/2:3',
        'tcont 1 name Fix_10M profile Fix_10M',
        'gemport 1 name Fix_10M tcont 1 queue 1',
        'switchport mode hybrid vport 1',
        'service-port 1 vport 1 user-vlan 2918 vlan 2918',
        'exit',
        # Step 2: Fix pon-onu-mng — add the missing gemport binding
        'pon-onu-mng gpon-onu_1/9/2:3',
        'gemport 1 flow 1 dot1p-list 0',
        'exit',
        'end',
    ]

    for cmd in commands:
        proc.stdin.write(cmd + '\n')
        out = await rp(proc, 10)
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out).strip()
        if 'Error' in clean or 'error' in clean:
            print(f'ERROR [{cmd}]: {clean[-300:]}')
        else:
            print(f'OK: {cmd}')

    # Verify interface config
    proc.stdin.write('show running-config interface gpon-onu_1/9/2:3\n')
    out = await rp(proc, 10)
    print('\n=== VERIFY INTERFACE CONFIG ===')
    print(re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out))

    # Verify pon-onu-mng
    proc.stdin.write('show running-config | begin pon-onu-mng gpon-onu_1/9/2:3\n')
    out = await rp(proc, 10)
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out)
    # Print until the next pon-onu-mng or !
    lines = clean.split('\n')
    capture = False
    for line in lines:
        if 'pon-onu-mng gpon-onu_1/9/2:3' in line:
            capture = True
        elif capture and ('pon-onu-mng gpon-onu_1/9/2:4' in line or (line.strip() == '!' and capture)):
            print(line)
            break
        if capture:
            print(line)

    # Wait and check IP
    print('\nWaiting 15s for PPPoE authentication...')
    await asyncio.sleep(15)

    proc.stdin.write('show gpon remote-onu ip-host gpon-onu_1/9/2:3\n')
    out = await rp(proc, 10)
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out)
    print('\n=== IP HOST STATUS ===')
    # Just show Host ID 1
    lines = clean.split('\n')
    for i, line in enumerate(lines):
        if 'Host ID' in line or 'IP addres' in line or 'Current IP' in line or 'Current mask' in line or 'Current gateway' in line or 'MAC address' in line or 'DHCP' in line or 'Current primary' in line:
            print(line.strip())
        if 'Host ID:            2' in line:
            break

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)

sftp = client.open_sftp()
with sftp.open("/tmp/prov3.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()

_, stdout, _ = client.exec_command(
    "docker cp /tmp/prov3.py jtl_olt_api:/tmp/prov3.py && "
    "docker exec jtl_olt_api python /tmp/prov3.py 2>&1",
    timeout=180,
)
print(stdout.read().decode())
client.close()
