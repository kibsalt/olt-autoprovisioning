"""Deploy PPPoE fix: sn-bind non-fatal, configure_pppoe, PPPoE fields in DB."""
import paramiko
import os

SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE_DIR = f"/home/{USERNAME}/olt-provisioning-api"

FILES = [
    "app/olt_driver/base.py",
    "app/olt_driver/zxan_driver.py",
    "app/olt_driver/titan_driver.py",
    "app/schemas/provision.py",
    "app/models/onu.py",
    "app/services/provision_service.py",
    "app/services/onu_service.py",
]


def create_clients():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
    sftp = client.open_sftp()
    return client, sftp


def run(client, cmd, timeout=60):
    print(f"  > {cmd[:200]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    for line in (out + "\n" + err).split("\n"):
        if line.strip():
            print(f"    {line}")
    return rc


def main():
    print(f"Connecting to {SERVER}...")
    client, sftp = create_clients()
    print("Connected!\n")

    # 1. Upload changed files
    print("=== Uploading files ===")
    base = os.path.dirname(os.path.abspath(__file__))
    for rel in FILES:
        local = os.path.join(base, rel)
        remote = f"{REMOTE_DIR}/{rel}"
        # Ensure remote directory exists
        remote_dir = remote.rsplit("/", 1)[0]
        run(client, f"mkdir -p {remote_dir}")
        sftp.put(local, remote)
        print(f"  Uploaded: {rel}")

    # 2. Add pppoe columns to DB (idempotent — ignore if already exists)
    print("\n=== Adding pppoe_username / pppoe_password columns ===")
    alter_sql = """
ALTER TABLE onus
  ADD COLUMN IF NOT EXISTS pppoe_username VARCHAR(64) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS pppoe_password VARCHAR(64) DEFAULT NULL;
"""
    run(client, f"""cd {REMOTE_DIR} && python3 -c "
from sqlalchemy import text, create_engine
from app.config import settings
engine = create_engine(settings.sync_database_url)
with engine.connect() as conn:
    conn.execute(text('''ALTER TABLE onus ADD COLUMN IF NOT EXISTS pppoe_username VARCHAR(64) DEFAULT NULL'''))
    conn.execute(text('''ALTER TABLE onus ADD COLUMN IF NOT EXISTS pppoe_password VARCHAR(64) DEFAULT NULL'''))
    conn.commit()
print('columns ok')
" """, timeout=30)

    # 3. Restart service
    print("\n=== Restarting API ===")
    run(client, f"echo '{PASSWORD}' | sudo -S systemctl restart olt-api", timeout=30)
    import time; time.sleep(4)

    # 4. Health check
    print("\n=== Health check ===")
    run(client, "curl -s http://localhost:8000/health")

    sftp.close()
    client.close()
    print("\nDone.")


main()
