"""Check if ONU:3 gets IP after VLAN 2918 added to uplink. Also reboot ONU to trigger PPPoE."""
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

    # First re-push the pon-onu-mng config that was lost after reboot
    print('Re-pushing pon-onu-mng flow/vlan config...')
    cmds = [
        'configure terminal',
        'pon-onu-mng gpon-onu_1/9/2:3',
        'flow mode 1 tag-filter vlan-filter untag-filter discard',
        'flow 1 pri 0 vlan 2918',
        'gemport 1 flow 1 dot1p-list 0',
        'switchport-bind switch_0/1 iphost 1',
        'pppoe 1 nat enable user kplc password kplc123',
        'vlan-filter-mode iphost 1 tag-filter vlan-filter untag-filter discard',
        'vlan-filter iphost 1 pri 0 vlan 2918',
        'firewall enable level low anti-hack enable',
        'exit',
        'end',
    ]
    for cmd in cmds:
        out = await run(proc, cmd, 10)
        if 'Error' in out:
            print(f'  ERROR: {cmd} -> {out.strip()[-150:]}')
        else:
            print(f'  OK: {cmd}')

    # Reboot ONU to trigger fresh PPPoE dial
    print('\nRebooting ONU:3...')
    await run(proc, 'configure terminal')
    await run(proc, 'pon-onu-mng gpon-onu_1/9/2:3')
    await run(proc, 'reboot')
    await run(proc, 'exit')
    await run(proc, 'end')

    # Wait for ONU to come back and PPPoE to dial
    for wait_label, secs in [('30s', 30), ('30s more', 30), ('30s more', 30)]:
        print(f'\nWaiting {wait_label}...')
        await asyncio.sleep(secs)

        out = await run(proc, 'show gpon remote-onu ip-host gpon-onu_1/9/2:3', 10)
        ip = '0.0.0.0'
        mac = '0000.0000.0000'
        for l in out.split('\n'):
            if 'Current IP address' in l:
                m = re.search(r'([\d.]+)', l.split(':',1)[1])
                if m: ip = m.group(1)
            if 'MAC address' in l and '0000.0000' not in l:
                m = re.search(r'([0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4})', l, re.I)
                if m: mac = m.group(1)

        if ip != '0.0.0.0':
            print(f'  IP: {ip}  MAC: {mac}  << GOT IP!')
            # Show full details
            for l in out.split('\n'):
                l = l.strip()
                if any(k in l for k in ['Current IP', 'Current mask', 'Current gateway', 'Current primary', 'Current second']):
                    print(f'  {l}')
            break
        else:
            # Check state
            state_out = await run(proc, 'show gpon onu state gpon-olt_1/9/2', 5)
            for l in state_out.split('\n'):
                if '1/9/2:3' in l:
                    print(f'  State: {l.strip()}  |  IP: {ip}  MAC: {mac}')
    else:
        print('\nONU still has no IP after 90s. PPPoE session not establishing.')
        print('Check: RADIUS server logs, BNG PPPoE service on VLAN 2918')

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
sftp = client.open_sftp()
with sftp.open("/tmp/check_final.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()
_, stdout, _ = client.exec_command(
    "docker cp /tmp/check_final.py jtl_olt_api:/tmp/check_final.py && docker exec jtl_olt_api python /tmp/check_final.py 2>&1",
    timeout=300)
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
print(stdout.read().decode(errors='replace'))
client.close()
