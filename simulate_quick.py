"""Quick test of new SSID format."""
import json, paramiko, time

SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE_DIR = "/home/jtlacs/olt-provisioning-api"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)

def run(cmd):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if err:
        print(f"  [stderr] {err[:200]}")
    return exit_code, out

# Test wifi generation directly
print("=== Testing WiFi SSID Generation ===\n")
code, out = run(f"""cd {REMOTE_DIR} && python3 -c "
from app.utils.wifi import generate_wifi_credentials
print(generate_wifi_credentials('Jane Wanjiku'))
print(generate_wifi_credentials('Kevin Odhiambo'))
print(generate_wifi_credentials('Mary Achieng'))
" """)
print(f"  {out}")

# Create ONU
print("\n=== Creating test ONU ===\n")
code, out = run(f"""cd {REMOTE_DIR} && python3 << 'PYEOF'
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
        olt_id=4, serial_number="ZTEGC8FA3001", customer_id="KSM-40001",
        frame=1, slot=1, port=3, onu_id=1, onu_type="ZXHN_F680",
        description="Jane Wanjiku - Kisumu CBD",
        admin_state=AdminState.ENABLED, oper_state=OperState.ONLINE,
        wifi_ssid_2g=wifi["ssid_2g"], wifi_ssid_5g=wifi["ssid_5g"],
        wifi_password=wifi["password"],
        customer_email="jane.wanjiku@gmail.com", customer_phone="+254722100200",
    )
    session.add(onu)
    session.flush()
    onu_id = onu.id
    session.commit()
    print(f"ONU created: ID={onu_id}")
    print(f"  WiFi 2.4GHz: {wifi['ssid_2g']}")
    print(f"  WiFi 5GHz:   {wifi['ssid_5g']}")
    print(f"  Password:    {wifi['password']}")

engine.dispose()
PYEOF""")
print(f"  {out}")

# Verify via API
print("\n=== Verify via API ===\n")
code, out = run(f"curl -s http://localhost:8000/api/v1/onus?customer_id=KSM-40001 -H 'X-API-Key: bss-prod-key-change-me'")
data = json.loads(out)
if data.get("success") and data["data"]:
    onu = data["data"][0]
    onu_id = onu["id"]
    print(f"  Customer:     {onu['customer_id']}")
    print(f"  WiFi 2.4GHz:  {onu['wifi_ssid_2g']}")
    print(f"  WiFi 5GHz:    {onu['wifi_ssid_5g']}")
    print(f"  Password:     {onu['wifi_password']}")

    # Cleanup
    run(f"curl -s -X DELETE http://localhost:8000/api/v1/olts/4/onus/{onu_id} -H 'X-API-Key: bss-prod-key-change-me'")
    print(f"\n  Test ONU cleaned up.")

client.close()
