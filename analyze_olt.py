"""Full analysis of the OLT - all ports, ONUs, configs, optical, WAN status."""
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

    # 1. System info
    print('=' * 70)
    print('OLT ANALYSIS REPORT')
    print('=' * 70)

    out = await run(proc, 'show hostname')
    for l in out.split('\n'):
        if 'hostname' in l.lower() or 'TESTAUTOPROV' in l:
            print(f'Hostname: {l.strip()}')

    out = await run(proc, 'show system-group')
    print('\n--- SYSTEM ---')
    for l in out.split('\n'):
        l = l.strip()
        if any(k in l.lower() for k in ['uptime', 'version', 'model', 'serial', 'cpu', 'memory', 'temperature']):
            print(f'  {l}')

    # 2. Card/slot info
    print('\n--- CARDS/SLOTS ---')
    out = await run(proc, 'show card')
    for l in out.split('\n'):
        l = l.strip()
        if l and not l.startswith('show ') and 'TESTAUTOPROV' not in l:
            print(f'  {l}')

    # 3. Find all GPON ports with ONUs
    print('\n--- GPON PORTS WITH ONUs ---')
    out = await run(proc, 'show running-config | include gpon-olt')
    gpon_ports = set()
    for l in out.split('\n'):
        m = re.search(r'interface gpon-olt_(\d+/\d+/\d+)', l)
        if m:
            gpon_ports.add(m.group(1))

    # Also check which ports have ONUs
    out = await run(proc, 'show running-config | include "onu .* type .* sn"', 20)
    onu_ports = set()
    for l in out.split('\n'):
        # Lines under interface gpon-olt_X/X/X sections
        m = re.search(r'onu\s+(\d+)\s+type\s+(\S+)\s+sn\s+(\S+)', l)
        if m:
            pass  # We'll get full detail per port below

    # 4. Per-port analysis
    # Scan known slots
    active_ports = []
    for slot in range(1, 20):
        for port in range(1, 17):
            port_str = f'1/{slot}/{port}'
            out = await run(proc, f'show gpon onu state gpon-olt_{port_str}', 5)
            if 'OnuIndex' in out and 'ONU Number' in out:
                m = re.search(r'ONU Number:\s*(\d+)/(\d+)', out)
                if m and int(m.group(1)) > 0:
                    active_ports.append(port_str)
                    count = m.group(1)
                    print(f'\n  Port gpon-olt_{port_str} — {count} ONUs')
                    for l in out.split('\n'):
                        if 'gpon-onu' in l:
                            print(f'    {l.strip()}')

    # 5. Detailed ONU analysis for each active port
    for port_str in active_ports:
        print(f'\n{"=" * 70}')
        print(f'PORT: gpon-olt_{port_str}')
        print('=' * 70)

        # Running config
        out = await run(proc, f'show running-config interface gpon-olt_{port_str}', 15)
        print('\n--- Port Config ---')
        for l in out.split('\n'):
            l = l.strip()
            if l and not l.startswith('show ') and 'Building' not in l and 'TESTAUTOPROV' not in l and l != 'end' and l != '!':
                print(f'  {l}')

        # Get ONU list
        onus = []
        for l in out.split('\n'):
            m = re.search(r'onu\s+(\d+)\s+type\s+(\S+)\s+sn\s+(\S+)', l)
            if m:
                onus.append({'id': int(m.group(1)), 'type': m.group(2), 'sn': m.group(3)})

        # Per-ONU details
        for onu in onus:
            onu_path = f'gpon-onu_{port_str}:{onu["id"]}'
            print(f'\n  --- ONU:{onu["id"]} | {onu["sn"]} | {onu["type"]} ---')

            # Interface config
            out = await run(proc, f'show running-config interface {onu_path}', 10)
            has_tcont = 'tcont' in out
            has_svcport = 'service-port' in out
            config_lines = []
            for l in out.split('\n'):
                l = l.strip()
                if l and not l.startswith('show ') and 'Building' not in l and 'TESTAUTOPROV' not in l and l != 'end' and l != '!' and 'interface' not in l.lower():
                    config_lines.append(l)
            if config_lines:
                print(f'    Interface config:')
                for l in config_lines:
                    print(f'      {l}')
            else:
                print(f'    Interface config: (EMPTY - missing tcont/gemport/service-port)')

            # Optical info
            out = await run(proc, f'show gpon onu optical-info {onu_path}', 10)
            for l in out.split('\n'):
                if 'Rx' in l and 'power' in l.lower():
                    print(f'    {l.strip()}')

            # Detail info (distance, state)
            out = await run(proc, f'show gpon onu detail-info {onu_path}', 10)
            for l in out.split('\n'):
                l = l.strip()
                if any(k in l for k in ['Phase state:', 'ONU Distance:', 'Online Duration:', 'Admin state:']):
                    print(f'    {l}')

            # IP host
            out = await run(proc, f'show gpon remote-onu ip-host {onu_path}', 10)
            ip = '0.0.0.0'
            mac = '0000.0000.0000'
            for l in out.split('\n'):
                if 'Current IP address' in l:
                    m2 = re.search(r'([\d.]+)', l.split(':',1)[1])
                    if m2: ip = m2.group(1)
                if 'MAC address' in l and '0000.0000' not in l:
                    m2 = re.search(r'([0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4})', l, re.I)
                    if m2: mac = m2.group(1)
            has_ip = ip != '0.0.0.0'
            print(f'    WAN IP: {ip} {"✓ ONLINE" if has_ip else "✗ NO IP"}  |  MAC: {mac}')

    # 6. pon-onu-mng summary
    print(f'\n{"=" * 70}')
    print('PON-ONU-MNG CONFIG SUMMARY')
    print('=' * 70)
    out = await run(proc, 'show running-config | begin pon-onu-mng', 20)
    lines = out.split('\n')
    current_onu = None
    for l in lines:
        l_stripped = l.strip()
        m = re.search(r'pon-onu-mng gpon-onu_(\S+)', l)
        if m:
            current_onu = m.group(1)
            print(f'\n  pon-onu-mng gpon-onu_{current_onu}')
        elif current_onu and l_stripped and l_stripped != '!' and 'TESTAUTOPROV' not in l and not l_stripped.startswith('pon') and not l_stripped.startswith('ces') and not l_stripped.startswith('ip-service') and not l_stripped.startswith('auto-write') and not l_stripped.startswith('inband') and not l_stripped.startswith('version') and not l_stripped.startswith('hostname') and not l_stripped.startswith('enable') and not l_stripped.startswith('service') and not l_stripped.startswith('username'):
            if l_stripped == '!':
                current_onu = None
            else:
                print(f'    {l_stripped}')
        elif l_stripped == '!' and current_onu:
            current_onu = None

    # 7. Uplink / VLAN trunking
    print(f'\n{"=" * 70}')
    print('UPLINK / VLANS')
    print('=' * 70)
    out = await run(proc, 'show running-config | include vlan', 15)
    for l in out.split('\n'):
        l = l.strip()
        if l and 'vlan' in l.lower() and not l.startswith('show') and 'TESTAUTOPROV' not in l:
            print(f'  {l}')

    # 8. Alarm check
    print(f'\n{"=" * 70}')
    print('ACTIVE ALARMS')
    print('=' * 70)
    out = await run(proc, 'show alarm active', 15)
    alarm_count = 0
    for l in out.split('\n'):
        l = l.strip()
        if l and not l.startswith('show') and 'TESTAUTOPROV' not in l and l != '!':
            print(f'  {l}')
            if 'gpon' in l.lower():
                alarm_count += 1
    if alarm_count == 0:
        print('  No active GPON alarms')

    print(f'\n{"=" * 70}')
    print('END OF ANALYSIS')
    print('=' * 70)

    proc.close()
    conn.close()

asyncio.run(main())
'''

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
sftp = client.open_sftp()
with sftp.open("/tmp/analyze.py", "w") as f:
    f.write(OLT_SCRIPT)
sftp.close()
_, stdout, _ = client.exec_command(
    "docker cp /tmp/analyze.py jtl_olt_api:/tmp/analyze.py && "
    "docker exec jtl_olt_api python /tmp/analyze.py 2>&1",
    timeout=300)
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
print(stdout.read().decode(errors='replace'))
client.close()
