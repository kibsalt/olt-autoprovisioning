"""Reboot ONU:3 to trigger PPPoE dial, then monitor IP assignment."""
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

    # Reboot ONU
    print('Rebooting ONU gpon-onu_1/9/2:3...')
    proc.stdin.write('configure terminal\n')
    await rp(proc, 5)
    proc.stdin.write('pon-onu-mng gpon-onu_1/9/2:3\n')
    await rp(proc, 5)
    proc.stdin.write('reboot\n')
    out = await rp(proc, 10)
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out)
    print(f'Reboot result: {clean.strip()[-200:]}')
    proc.stdin.write('exit\n')
    await rp(proc, 3)
    proc.stdin.write('end\n')
    await rp(proc, 3)

    # Wait for ONU to come back online
    print('Waiting 30s for ONU to reboot and PPPoE to dial...')
    await asyncio.sleep(30)

    # Check state
    proc.stdin.write('show gpon onu state gpon-olt_1/9/2\n')
    out = await rp(proc, 10)
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out)
    for line in clean.split('\n'):
        if '1/9/2:3' in line or 'OnuIndex' in line or '---' in line:
            print(line.strip())

    # Check IP
    proc.stdin.write('show gpon remote-onu ip-host gpon-onu_1/9/2:3\n')
    out = await rp(proc, 10)
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out)
    print('\n=== IP HOST after reboot ===')
    for line in clean.split('\n'):
        line = line.strip()
        if any(k in line for k in ['Host ID:', 'IP addres', 'Current IP', 'Current mask', 'Current gateway', 'Current primary', 'MAC address', 'DHCP']):
            print(line)
        if 'Host ID:            2' in line:
            break

    # If still no IP, wait another 30s
    ip_line = [l for l in clean.split('\n') if 'Current IP address' in l]
    if ip_line and '0.0.0.0' in ip_line[0]:
        print('\nStill no IP, waiting another 30s...')
        await asyncio.sleep(30)
        proc.stdin.write('show gpon remote-onu ip-host gpon-onu_1/9/2:3\n')
        out = await rp(proc, 10)
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out)
        print('\n=== IP HOST (2nd check) ===')
        for line in clean.split('\n'):
            line = line.strip()
            if any(k in line for k in ['Host ID:', 'IP addres', 'Current IP', 'Current mask', 'Current gateway', 'MAC address']):
                print(line)
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
with sftp.open("/tmp/reboot3.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()

_, stdout, _ = client.exec_command(
    "docker cp /tmp/reboot3.py jtl_olt_api:/tmp/reboot3.py && "
    "docker exec jtl_olt_api python /tmp/reboot3.py 2>&1",
    timeout=180,
)
print(stdout.read().decode())
client.close()
