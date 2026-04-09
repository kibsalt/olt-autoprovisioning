"""
Upload all driver fixes, rebuild olt-api, and run full provisioning test.
"""
import os, time, json, paramiko

SERVER   = "192.168.14.4"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE   = "/home/jtlacs/jtl-automation"
LOCAL    = os.path.dirname(os.path.abspath(__file__))

def ssh_cmd(client, cmd, timeout=120):
    print(f"  $ {cmd[:140]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out.strip(): print(out.strip())
    if err.strip(): print(f"[stderr] {err.strip()[:400]}")
    return out, err

def sudo_cmd(client, cmd, timeout=300):
    return ssh_cmd(client, f'echo "{PASSWORD}" | sudo -S {cmd}', timeout=timeout)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
print(f"Connected to {SERVER}\n")

sftp = client.open_sftp()

files_to_upload = [
    "olt-provisioning-api/app/olt_driver/ssh_client.py",
    "olt-provisioning-api/app/olt_driver/zxan_driver.py",
    "olt-provisioning-api/app/olt_driver/response_parser.py",
    "olt-provisioning-api/app/services/provision_service.py",
    "olt-provisioning-api/app/api/v1/olts.py",
]

for rel in files_to_upload:
    local_path = os.path.join(LOCAL, rel)
    remote_path = f"{REMOTE}/{rel}"
    print(f"Uploading {rel.split('/')[-1]}...")
    sftp.put(local_path, remote_path)
sftp.close()
print("All files uploaded.\n")

# Rebuild
print("Rebuilding olt-api...")
sudo_cmd(client, f"bash -c 'cd {REMOTE} && docker compose build olt-api'", timeout=300)

print("\nForce-recreating olt-api...")
sudo_cmd(client, f"bash -c 'cd {REMOTE} && docker compose up -d --force-recreate olt-api'", timeout=60)

time.sleep(8)

print("\n--- Container status ---")
sudo_cmd(client, "docker ps --format 'table {{.Names}}\\t{{.Status}}'")

print("\n--- Health check ---")
out, _ = ssh_cmd(client, 'curl -s http://localhost:8000/api/v1/olts/1/health -H "X-API-Key: bss-prod-key-change-me"')
try:
    data = json.loads(out)
    print(json.dumps(data, indent=2))
except Exception:
    print(out)

# ── Provisioning test ──────────────────────────────────────────────────────
print("\n" + "="*60)
print("PROVISIONING TEST: ZXICC9F27071 on OLT-C300-TESTAUTOPROV")
print("="*60)

provision_payload = json.dumps({
    "customer_id": "TEST-CUST-001",
    "customer_name": "Test Customer One",
    "customer_phone": None,
    "customer_email": None,
    "onu_serial_number": "ZXICC9F27071",
    "onu_model": "ZTEG-F660",
    "olt_id": "OLT-C300-TESTAUTOPROV",
    "package_id": "GPON-5M",
    "service_vlan": 200,
    "oam_vlan": 1450
})

out, _ = ssh_cmd(client,
    f"curl -s -X POST http://localhost:8000/provision "
    f"-H 'X-API-Key: bss-prod-key-change-me' "
    f"-H 'Content-Type: application/json' "
    f"-d '{provision_payload}'",
    timeout=200)
try:
    data = json.loads(out)
    print(json.dumps(data, indent=2))
except Exception:
    print(out)

client.close()
print("\nDone.")
