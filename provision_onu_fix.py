"""Push full provisioning config for ONU ZTEGD1397E71 (gpon-onu_1/9/2:3) via the production server."""
import paramiko
import time

SERVER = "192.168.14.4"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE = "/home/jtlacs/jtl-automation"

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

    commands = [
        'configure terminal',
        # T-CONT + GEM Port
        'interface gpon-onu_1/9/2:3',
        'tcont 1 profile 10',
        'gemport 1 tcont 1',
        # Service port with VLAN 2918
        'switchport mode hybrid vport 1',
        'service-port 1 vport 1 user-vlan 2918 vlan 2918',
        'exit',
        # OMCI profile: flow, PPPoE, ACS, security
        'pon-onu-mng gpon-onu_1/9/2:3',
        'flow mode 1 tag-filter vlan-filter untag-filter discard',
        'flow 1 pri 0 vlan 2918',
        'gemport 1 flow 1 dot1p-list 0',
        'switchport-bind switch_0/1 iphost 1',
        'pppoe 1 nat enable user kplc password kplc123',
        'vlan-filter-mode iphost 1 tag-filter vlan-filter untag-filter discard',
        'vlan-filter iphost 1 pri 0 vlan 2918',
        'firewall enable level low anti-hack disable',
        'tr069-mgmt 1 state unlock',
        'tr069-mgmt 1 acs http://197.232.61.253:7547 validate basic username ACS jtl@acs word admin',
        'security-mgmt 1 state enable mode forward protocol web',
        'security-mgmt 2 state enable ingress-type lan protocol web',
        'security-mgmt 3 state enable ingress-type lan protocol telnet',
        'security-mgmt 4 state enable protocol telnet',
        'exit',
        'end',
    ]

    for cmd in commands:
        proc.stdin.write(cmd + '\n')
        out = await rp(proc, 10)
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out).strip()
        if 'Error' in clean or 'error' in clean:
            print(f'ERROR [{cmd}]: {clean[-200:]}')
        else:
            print(f'OK: {cmd}')

    # Verify config
    proc.stdin.write('show running-config interface gpon-onu_1/9/2:3\n')
    out = await rp(proc, 10)
    print('\n=== VERIFY CONFIG ===')
    print(re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out))

    # Check IP after 10s
    print('\nWaiting 10s for PPPoE auth...')
    await asyncio.sleep(10)
    proc.stdin.write('show gpon remote-onu ip-host gpon-onu_1/9/2:3\n')
    out = await rp(proc, 10)
    print('\n=== IP HOST ===')
    print(re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out))

    proc.close()
    conn.close()

asyncio.run(main())
'''


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
    print(f"Connected to {SERVER}")

    # Upload the OLT script
    sftp = client.open_sftp()
    with sftp.open("/tmp/prov_onu.py", "w") as f:
        f.write(OLT_SCRIPT)
    sftp.close()
    print("Script uploaded")

    # Copy into Docker container and run
    _, stdout, _ = client.exec_command(
        "docker cp /tmp/prov_onu.py jtl_olt_api:/tmp/prov_onu.py && "
        "docker exec jtl_olt_api python /tmp/prov_onu.py 2>&1",
        timeout=180,
    )
    print(stdout.read().decode())

    client.close()


if __name__ == "__main__":
    main()
