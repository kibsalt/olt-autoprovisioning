"""Try alternative methods to add VLAN 2918 to uplink."""
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
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', out)
    return clean

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

    # Check if VLAN 2918 exists in database
    out = await run(proc, 'show vlan 2918')
    print('=== VLAN 2918 STATUS ===')
    print(out)

    # Try method 1: switchport vlan add
    print('\n--- Method 1: switchport vlan 2918 tag (add separately) ---')
    await run(proc, 'configure terminal')
    await run(proc, 'interface xgei_1/22/1')
    out = await run(proc, 'switchport vlan 2918 tag')
    print(out.strip())
    await run(proc, 'exit')
    await run(proc, 'end')

    # Verify
    out = await run(proc, 'show running-config interface xgei_1/22/1')
    for l in out.split('\n'):
        if 'switchport vlan' in l:
            print(f'  Result: {l.strip()}')

    # Check if 2918 is there now
    if '2918' not in out:
        # Method 2: Try with "switchport trunk allowed vlan add"
        print('\n--- Method 2: switchport trunk allowed vlan add 2918 ---')
        await run(proc, 'configure terminal')
        await run(proc, 'interface xgei_1/22/1')
        out = await run(proc, 'switchport trunk allowed vlan add 2918')
        print(out.strip())
        await run(proc, 'exit')
        await run(proc, 'end')

        out = await run(proc, 'show running-config interface xgei_1/22/1')
        for l in out.split('\n'):
            if 'switchport vlan' in l or 'trunk' in l:
                print(f'  Result: {l.strip()}')

    # Check if 2918 is there now
    out = await run(proc, 'show running-config interface xgei_1/22/1')
    if '2918' not in out:
        # Method 3: show help for the switchport command
        print('\n--- Checking switchport syntax help ---')
        await run(proc, 'configure terminal')
        await run(proc, 'interface xgei_1/22/1')
        out = await run(proc, 'switchport vlan ?')
        print(out)
        out = await run(proc, 'switchport ?')
        print(out)
        await run(proc, 'exit')
        await run(proc, 'end')

    # Final check
    out = await run(proc, 'show running-config interface xgei_1/22/1')
    print('\n=== FINAL UPLINK CONFIG ===')
    print(out)

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
sftp = client.open_sftp()
with sftp.open("/tmp/add_v2.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()
_, stdout, _ = client.exec_command(
    "docker cp /tmp/add_v2.py jtl_olt_api:/tmp/add_v2.py && docker exec jtl_olt_api python /tmp/add_v2.py 2>&1",
    timeout=120)
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
print(stdout.read().decode(errors='replace'))
client.close()
