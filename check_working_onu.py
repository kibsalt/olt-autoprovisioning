"""Check config of all ONUs on port 1/9/2 to find a working reference."""
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

    # Show all ONUs on the port
    proc.stdin.write('show gpon onu state gpon-olt_1/9/2\n')
    out = await rp(proc, 10)
    print('=== ONU STATES ===')
    print(re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out))

    # Show running config for the entire port (to see all ONU configs)
    proc.stdin.write('show running-config interface gpon-olt_1/9/2\n')
    out = await rp(proc, 15)
    print('\n=== PORT RUNNING CONFIG ===')
    print(re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out))

    # Show all service ports
    proc.stdin.write('show service-port\n')
    out = await rp(proc, 15)
    print('\n=== SERVICE PORTS ===')
    print(re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out))

    # Check pon-onu-mng for ONU 1 (ZTEGD139764E - first ONU)
    proc.stdin.write('show pon-onu-mng gpon-onu_1/9/2:1\n')
    out = await rp(proc, 10)
    print('\n=== PON-ONU-MNG ONU:1 ===')
    print(re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out))

    # Check pon-onu-mng for ONU 3 (ZTEGD1397E71 - our target)
    proc.stdin.write('show pon-onu-mng gpon-onu_1/9/2:3\n')
    out = await rp(proc, 10)
    print('\n=== PON-ONU-MNG ONU:3 (ZTEGD1397E71) ===')
    print(re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out))

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)

sftp = client.open_sftp()
with sftp.open("/tmp/check_onu2.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()

_, stdout, _ = client.exec_command(
    "docker cp /tmp/check_onu2.py jtl_olt_api:/tmp/check_onu2.py && "
    "docker exec jtl_olt_api python /tmp/check_onu2.py 2>&1",
    timeout=120,
)
print(stdout.read().decode())
client.close()
