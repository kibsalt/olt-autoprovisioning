"""Final native deployment: fix code, create tables, start systemd service."""

import time
import paramiko

SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE_DIR = f"/home/{USERNAME}/olt-provisioning-api"


def create_ssh_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
    return client


def run(client, cmd, check=True, timeout=120):
    print(f"  > {cmd[:200]}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        for line in out.split("\n")[:20]:
            print(f"    {line}")
    if err:
        for line in err.split("\n")[:8]:
            print(f"    [stderr] {line}")
    return exit_code, out, err


def sudo(client, cmd, **kwargs):
    return run(client, f"echo '{PASSWORD}' | sudo -S bash -c '{cmd}'", **kwargs)


def main():
    print(f"Connecting to {SERVER}...")
    client = create_ssh_client()
    print("Connected!\n")

    # 1. Create DB tables (files already uploaded with fixes)
    print("=== Creating Database Tables ===")
    code, out, err = run(client, f"""cd {REMOTE_DIR} && python3 << 'PYEOF'
from sqlalchemy import create_engine
from app.config import settings
from app.models.base import Base
import app.models
engine = create_engine(settings.sync_database_url)
Base.metadata.create_all(engine)
print("Tables created successfully!")
for t in Base.metadata.tables:
    print(f"  - {{t}}")
engine.dispose()
PYEOF""")

    if code != 0:
        print("\nTable creation failed. Checking what's wrong...")
        run(client, f"cd {REMOTE_DIR} && python3 -c 'from app.config import settings; print(settings.sync_database_url)'", check=False)
        run(client, f"cd {REMOTE_DIR} && python3 -c 'import app.models; print(\"Models loaded OK\")'", check=False)
        return

    # 2. Restart systemd service
    print("\n=== Restarting API Service ===")
    sudo(client, "systemctl restart olt-api")
    time.sleep(10)
    sudo(client, "systemctl status olt-api --no-pager | head -12")

    # 3. Health check
    print("\n=== Health Check ===")
    for i in range(6):
        time.sleep(3)
        code, out, _ = run(client, "curl -sf http://localhost:8000/health", check=False)
        if code == 0 and out:
            print(f"\n    API is LIVE: {out}")
            break
        print(f"    Attempt {i+1}...")
    else:
        print("\n-- Checking logs --")
        sudo(client, "journalctl -u olt-api --no-pager -n 25")
        client.close()
        return

    # 4. Test endpoints
    print("\n=== API Endpoint Tests ===")
    print("\n-- List OLTs --")
    run(client, "curl -s http://localhost:8000/api/v1/olts -H 'X-API-Key: bss-prod-key-change-me'", check=False)
    print("\n-- List VLANs --")
    run(client, "curl -s http://localhost:8000/api/v1/vlans -H 'X-API-Key: bss-prod-key-change-me'", check=False)
    print("\n-- List Service Profiles --")
    run(client, "curl -s http://localhost:8000/api/v1/service-profiles -H 'X-API-Key: bss-prod-key-change-me'", check=False)
    print("\n-- Auth test (no key) --")
    run(client, "curl -s http://localhost:8000/api/v1/olts", check=False)

    print(f"\n{'='*50}")
    print(f"  API LIVE at http://{SERVER}:8000")
    print(f"  Swagger Docs: http://{SERVER}:8000/docs")
    print(f"  Health Check: http://{SERVER}:8000/health")
    print(f"{'='*50}")

    client.close()


if __name__ == "__main__":
    main()
