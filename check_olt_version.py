"""Check OLT firmware and find correct provisioning syntax."""
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

    cmds = [
        'show version',
        'show service-port all',
        'show gpon onu running-config gpon-onu_1/9/2:3',
        'show gpon onu tcont gpon-onu_1/9/2:3',
        'show gpon onu gemport gpon-onu_1/9/2:3',
        'show gpon onu service gpon-onu_1/9/2:3',
        'show running-config section pon-onu-mng',
        'show running-config | include service-port',
        'show running-config | include tcont',
        'show running-config | include gemport',
        'show running-config | include pon-onu-mng',
        'show running-config | include pppoe',
    ]
    for cmd in cmds:
        proc.stdin.write(cmd + '\n')
        out = await rp(proc, 10)
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out).strip()
        print(f'\n=== {cmd} ===')
        print(clean[:2000])

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)

sftp = client.open_sftp()
with sftp.open("/tmp/ck_ver.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()

_, stdout, _ = client.exec_command(
    "docker cp /tmp/ck_ver.py jtl_olt_api:/tmp/ck_ver.py && "
    "docker exec jtl_olt_api python /tmp/ck_ver.py 2>&1",
    timeout=120,
)
print(stdout.read().decode())
client.close()
