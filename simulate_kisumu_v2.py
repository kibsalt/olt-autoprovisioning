"""Quick simulation showing new SSID naming: FirstName_2.4G / FirstName_5G"""
import json, paramiko

SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
API = "http://localhost:8000/api/v1"
KEY = "bss-prod-key-change-me"
OLT_ID = 4
REMOTE_DIR = "/home/jtlacs/olt-provisioning-api"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)

def run(cmd):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    stdout.channel.recv_exit_status()
    return stdout.read().decode().strip()

def api(method, endpoint, data=None):
    url = f"{API}{endpoint}"
    if data:
        j = json.dumps(data).replace("'", "'\\''")
        out = run(f"curl -s -X {method} '{url}' -H 'X-API-Key: {KEY}' -H 'Content-Type: application/json' -d '{j}'")
    else:
        out = run(f"curl -s -X {method} '{url}' -H 'X-API-Key: {KEY}'")
    try: return json.loads(out)
    except: return {"raw": out}

def step(n, t):
    print(f"\n{'='*60}\n  STEP {n}: {t}\n{'='*60}")

print("=" * 60)
print("  CUSTOMER PROVISIONING — KISUMU OLT")
print("  New SSID Format: FirstName_2.4G / FirstName_5G")
print("=" * 60)

# Step 1: Create ONU via DB
step(1, "Provision customer: Jane Wanjiku")
insert = f"""cd {REMOTE_DIR} && python3 << 'PYEOF'
from app.config import settings
from app.models.onu import ONU, ONUService, AdminState, OperState, ONUServiceStatus
from app.utils.wifi import generate_wifi_credentials
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import app.models

engine = create_engine(settings.sync_database_url)
wifi = generate_wifi_credentials("Jane Wanjiku")

with Session(engine) as session:
    onu = ONU(
        olt_id=4, serial_number="ZTEGC8FA2001", customer_id="KSM-30001",
        frame=1, slot=1, port=2, onu_id=1, onu_type="ZXHN_F680",
        description="Jane Wanjiku - Kisumu CBD",
        admin_state=AdminState.ENABLED, oper_state=OperState.ONLINE,
        wifi_ssid_2g=wifi["ssid_2g"], wifi_ssid_5g=wifi["ssid_5g"],
        wifi_password=wifi["password"],
        customer_email="jane.wanjiku@gmail.com", customer_phone="+254722100200",
    )
    session.add(onu)
    session.flush()
    svc = ONUService(onu_id=onu.id, service_profile_id=3, service_port_id=40021,
                     vlan_id=1, status=ONUServiceStatus.ACTIVE)
    session.add(svc)
    session.commit()
    print(f"ID={onu.id}|SSID_2G={wifi['ssid_2g']}|SSID_5G={wifi['ssid_5g']}|PASS={wifi['password']}")
engine.dispose()
PYEOF"""
out = run(insert)
print(f"\n  {out}")
parts = {}
for kv in out.split("|"):
    if "=" in kv:
        k, v = kv.split("=", 1)
        parts[k] = v

onu_id = int(parts.get("ID", 0))
print(f"\n  Customer:      Jane Wanjiku (KSM-30001)")
print(f"  ONU:           ZTEGC8FA2001 on 1/1/2:1")
print(f"  WiFi 2.4GHz:   {parts.get('SSID_2G')}")
print(f"  WiFi 5GHz:     {parts.get('SSID_5G')}")
print(f"  Password:      {parts.get('PASS')}")

# Step 2: Verify via API
step(2, "Retrieve ONU via API")
print(f"\n  >> GET /api/v1/olts/{OLT_ID}/onus/{onu_id}")
r = api("GET", f"/olts/{OLT_ID}/onus/{onu_id}")
if r.get("success"):
    d = r["data"]
    print(f"\n  Serial:       {d['serial_number']}")
    print(f"  Customer:     {d['customer_id']}")
    print(f"  Location:     {d['frame']}/{d['slot']}/{d['port']}:{d['onu_id']}")
    print(f"  WiFi 2.4GHz:  {d['wifi_ssid_2g']}")
    print(f"  WiFi 5GHz:    {d['wifi_ssid_5g']}")
    print(f"  Password:     {d['wifi_password']}")
    print(f"  State:        {d['admin_state']}")

# Step 3: Show SSH commands that would be sent
step(3, "SSH commands sent to OLT (ZXAN C320)")
print(f"""
  configure terminal
  interface gpon-olt_1/1/2
    onu 1 type ZXHN_F680 sn ZTEGC8FA2001
    onu 1 description Jane Wanjiku - Kisumu CBD
  exit
  interface gpon-onu_1/1/2:1
    tr069-serv-url http://197.232.61.253:7547
    tr069-username ACS
    tr069-password jtl@acs
    wifi ssid 1 name {parts.get('SSID_2G')}
    wifi ssid 1 auth-mode wpa2-psk
    wifi ssid 1 wpa-key {parts.get('PASS')}
    wifi ssid 1 enable true
    wifi ssid 5 name {parts.get('SSID_5G')}
    wifi ssid 5 auth-mode wpa2-psk
    wifi ssid 5 wpa-key {parts.get('PASS')}
    wifi ssid 5 enable true
    tcont 1 profile 3
    gemport 1 tcont 1
  exit
  service-port 40021 vport-mode gpon-onu_1/1/2:1 vlan 100 user-vlan 100 gemport 1""")

# Step 4: Show notification
step(4, "Customer notification")
print(f"""
  SMS to +254722100200:
  ─────────────────────────────────
  JTL Internet - WiFi Credentials
  2.4GHz: {parts.get('SSID_2G')}
  5GHz:   {parts.get('SSID_5G')}
  Password: {parts.get('PASS')}
  Welcome to JTL!

  Email to jane.wanjiku@gmail.com:
  ─────────────────────────────────
  Subject: Your JTL Internet - WiFi Credentials

  Dear Customer,
  Your WiFi connection is now active.

    2.4GHz: {parts.get('SSID_2G')}
    5GHz:   {parts.get('SSID_5G')}
    Password: {parts.get('PASS')}
""")

# Step 5: Cleanup
step(5, "Cleanup (remove test ONU)")
api("DELETE", f"/olts/{OLT_ID}/onus/{onu_id}")
r = api("GET", "/onus?customer_id=KSM-30001")
remaining = len(r.get("data", [])) if r.get("success") else "?"
print(f"\n  ONU deleted. Remaining for KSM-30001: {remaining}")

print(f"\n{'='*60}")
print(f"  SIMULATION COMPLETE")
print(f"{'='*60}")
print(f"  SSID Format:  {{FirstName}}_2.4G / {{FirstName}}_5G")
print(f"  Example:      {parts.get('SSID_2G')} / {parts.get('SSID_5G')}")
print(f"  Password:     {parts.get('PASS')} (random 12-char)")

client.close()
