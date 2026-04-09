"""
Deploy BSS provisioning routes and all new/changed files to production.

Run this from a machine with SSH access to 172.16.37.18:
  python deploy_bss_routes.py

Changed files since last deploy:
  app/main.py                     - added bss_router + CORS
  app/config.py                   - added at_whatsapp_sender + acs_management_url
  app/models/onu.py               - added 10 new nullable columns
  app/models/notification.py      - added WHATSAPP enum value
  app/olt_driver/zxan_driver.py   - create_service_port svlan + configure_dba_profile
  app/olt_driver/titan_driver.py  - configure_dba_profile
  app/olt_driver/base.py          - abstract configure_dba_profile
  app/schemas/provision.py        - NEW: ProvisionRequest/Response/PackageUpdateRequest
  app/services/provision_service.py - NEW: 14-step BSS flow
  app/api/bss/__init__.py         - NEW: package init
  app/api/bss/provision.py        - NEW: 7 BSS endpoints
  app/utils/packages.py           - NEW: GPON package map
  app/utils/wifi.py               - updated SSID naming
  app/utils/acs_client.py         - TR-181 WiFi paths + wait_for_inform
  app/notifications/whatsapp_service.py - NEW: WhatsApp via AT
  app/notifications/notify.py     - added WhatsApp dispatch
  docs/bss-portal.html            - updated BSS portal UI
  docs/api-documentation.html     - NEW: technical docs
  docs/executive-summary.html     - NEW: executive summary
"""

import os
import time
import paramiko

SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE_DIR = f"/home/{USERNAME}/olt-provisioning-api"
LOCAL_BASE = os.path.dirname(os.path.abspath(__file__))

FILES_TO_UPLOAD = [
    "app/main.py",
    "app/config.py",
    "app/models/onu.py",
    "app/models/notification.py",
    "app/olt_driver/zxan_driver.py",
    "app/olt_driver/titan_driver.py",
    "app/olt_driver/base.py",
    "app/schemas/provision.py",
    "app/services/provision_service.py",
    "app/api/bss/__init__.py",
    "app/api/bss/provision.py",
    "app/utils/packages.py",
    "app/utils/wifi.py",
    "app/utils/acs_client.py",
    "app/notifications/whatsapp_service.py",
    "app/notifications/notify.py",
    "docs/bss-portal.html",
    "docs/api-documentation.html",
    "docs/executive-summary.html",
]

# Alembic migration SQL for new ONU columns + WHATSAPP enum
MIGRATION_SQL = """
-- Add new columns to onus table (skip if already exist)
ALTER TABLE onus
  ADD COLUMN IF NOT EXISTS customer_name VARCHAR(256) NULL,
  ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(32) NULL,
  ADD COLUMN IF NOT EXISTS customer_email VARCHAR(256) NULL,
  ADD COLUMN IF NOT EXISTS wifi_ssid_2g VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS wifi_ssid_5g VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS wifi_password VARCHAR(64) NULL,
  ADD COLUMN IF NOT EXISTS package_id VARCHAR(32) NULL,
  ADD COLUMN IF NOT EXISTS service_vlan SMALLINT NULL,
  ADD COLUMN IF NOT EXISTS oam_vlan SMALLINT NULL,
  ADD COLUMN IF NOT EXISTS svlan SMALLINT NULL;

-- Update notifications enum to add whatsapp
ALTER TABLE notifications MODIFY COLUMN type ENUM('email','sms','whatsapp') NOT NULL;
"""


def create_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
    return client


def run(client, cmd, timeout=60):
    print(f"  $ {cmd[:120]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    for line in (out or err).split("\n")[:10]:
        if line:
            print(f"    {line}")
    return rc, out


def sudo(client, cmd, **kw):
    return run(client, f"echo '{PASSWORD}' | sudo -S bash -c \"{cmd}\"", **kw)


def upload(client, rel_path):
    local = os.path.join(LOCAL_BASE, rel_path.replace("/", os.sep))
    remote = f"{REMOTE_DIR}/{rel_path}"
    sftp = client.open_sftp()
    # Ensure remote dir exists
    remote_dir = remote.rsplit("/", 1)[0]
    try:
        sftp.makedirs(remote_dir)
    except Exception:
        pass
    print(f"  ↑ {rel_path}")
    sftp.put(local, remote)
    sftp.close()


def main():
    print(f"\n{'='*55}")
    print(f"  Deploying BSS Routes → {SERVER}")
    print(f"{'='*55}\n")

    print("Connecting...")
    client = create_client()
    print("Connected.\n")

    # 1. Upload all changed files
    print("=== Uploading Files ===")
    for f in FILES_TO_UPLOAD:
        local = os.path.join(LOCAL_BASE, f.replace("/", os.sep))
        if os.path.exists(local):
            upload(client, f)
        else:
            print(f"  SKIP (not found locally): {f}")

    # 2. Run DB migration
    print("\n=== Database Migration ===")
    migration_cmd = f"""cd {REMOTE_DIR} && python3 -c "
from app.db.session import engine
import asyncio
from sqlalchemy import text

async def migrate():
    async with engine.begin() as conn:
        stmts = '''
{MIGRATION_SQL}
'''.strip().split(';')
        for s in stmts:
            s = s.strip()
            if s:
                try:
                    await conn.execute(text(s))
                    print('OK:', s[:60])
                except Exception as e:
                    print('SKIP:', str(e)[:80])

asyncio.run(migrate())
"
"""
    run(client, migration_cmd, timeout=30)

    # 3. Restart systemd service
    print("\n=== Restarting Service ===")
    sudo(client, "systemctl restart olt-api", timeout=30)

    # 4. Wait and health-check
    print("\n=== Health Check ===")
    for i in range(8):
        time.sleep(5)
        rc, out = run(client, "curl -sf http://localhost:8000/health")
        if rc == 0 and "ok" in out.lower():
            print(f"\n  API is LIVE: {out}")
            break
        print(f"  attempt {i+1}/8...")
    else:
        print("  Health check failed — checking logs:")
        sudo(client, f"cd {REMOTE_DIR} && docker compose logs --tail=30 api")
        client.close()
        return

    # 5. Verify BSS routes are registered
    print("\n=== Verifying BSS Routes ===")
    rc, out = run(client, "curl -s http://localhost:8000/openapi.json | python3 -c \"import json,sys; paths=json.load(sys.stdin)['paths'].keys(); print('\\n'.join(p for p in sorted(paths) if '/provision' in p or '/onu/' in p))\"")

    # 6. Quick smoke test - list OLTs
    print("\n=== Smoke Test ===")
    run(client, "curl -s http://localhost:8000/api/v1/olts -H 'X-API-Key: bss-prod-key-change-me' | python3 -c \"import json,sys; d=json.load(sys.stdin); print('OLTs:', [o['name'] for o in d.get('data',[])])\"")

    # 7. Test BSS provision discovery
    print("\n=== Test ONU Discovery ===")
    run(client, "curl -s 'http://localhost:8000/onu/OLT-C300-TESTAUTOPROV/unconfigured?slot=7&port=2' -H 'X-API-Key: bss-prod-key-change-me'")

    print(f"\n{'='*55}")
    print(f"  DEPLOY COMPLETE")
    print(f"  OLT API:      http://{SERVER}:8000")
    print(f"  BSS Portal:   http://{SERVER}:8000/portal")
    print(f"  API Docs:     http://{SERVER}:8000/docs")
    print(f"  Exec Summary: http://{SERVER}:8000/static/executive-summary.html")
    print(f"  Tech Docs:    http://{SERVER}:8000/static/api-documentation.html")
    print(f"{'='*55}\n")
    print("To test provisioning, run:")
    print(f"  curl -X POST http://{SERVER}:8000/provision \\")
    print(f"    -H 'X-API-Key: bss-prod-key-change-me' \\")
    print(f"    -H 'Content-Type: application/json' \\")
    print(f"    -d '{{\"customer_id\":\"TEST-0001\",\"customer_name\":\"Test Customer\",")
    print(f"          \"onu_serial_number\":\"ZTEGD1397E71\",\"onu_model\":\"ZTEG-F660\",")
    print(f"          \"olt_id\":\"OLT-C300-TESTAUTOPROV\",\"package_id\":\"GPON-5M\",")
    print(f"          \"service_vlan\":200}}'")

    client.close()


if __name__ == "__main__":
    main()
