"""Upload fixed config files, create DB tables, and restart service."""

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
    print(f"  > {cmd[:180]}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        for line in out.split("\n")[:20]:
            print(f"    {line}")
    if err:
        for line in err.split("\n")[:5]:
            print(f"    [stderr] {line}")
    return exit_code, out, err


def sudo(client, cmd, **kwargs):
    return run(client, f"echo '{PASSWORD}' | sudo -S bash -c '{cmd}'", **kwargs)


def upload_file(client, local_path, remote_path):
    sftp = client.open_sftp()
    print(f"  Uploading: {remote_path}")
    sftp.put(local_path, remote_path)
    sftp.close()


def main():
    print(f"Connecting to {SERVER}...")
    client = create_ssh_client()
    print("Connected!\n")

    # Upload fixed files
    print("=== Uploading Fixed Files ===")
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    files_to_upload = [
        ("app/config.py", f"{REMOTE_DIR}/app/config.py"),
        ("app/dependencies.py", f"{REMOTE_DIR}/app/dependencies.py"),
    ]
    for local_rel, remote in files_to_upload:
        upload_file(client, os.path.join(base, local_rel), remote)

    # Create DB tables
    print("\n=== Creating Database Tables ===")
    code, out, err = run(client, f"""cd {REMOTE_DIR} && python3 << 'PYEOF'
from sqlalchemy import create_engine
from app.config import settings
from app.models.base import Base
import app.models
engine = create_engine(settings.sync_database_url)
Base.metadata.create_all(engine)
print("Tables created successfully!")
engine.dispose()
PYEOF""")

    # Restart
    print("\n=== Restarting Service ===")
    sudo(client, "systemctl restart olt-api")
    time.sleep(8)
    sudo(client, "systemctl status olt-api --no-pager | head -10")

    # Health check
    print("\n=== Health Check ===")
    for i in range(5):
        time.sleep(3)
        code, out, _ = run(client, "curl -sf http://localhost:8000/health", check=False)
        if code == 0 and out:
            print(f"\n    API is LIVE: {out}")
            break
        print(f"    Attempt {i+1}...")
    else:
        print("\n-- Service logs --")
        sudo(client, "journalctl -u olt-api --no-pager -n 20")
        client.close()
        return

    # Test API
    print("\n=== API Tests ===")
    run(client, "curl -s http://localhost:8000/api/v1/olts -H 'X-API-Key: bss-prod-key-change-me'", check=False)
    run(client, "curl -s http://localhost:8000/api/v1/vlans -H 'X-API-Key: bss-prod-key-change-me'", check=False)

    print(f"\n{'='*50}")
    print(f"  API LIVE at http://{SERVER}:8000")
    print(f"  Docs: http://{SERVER}:8000/docs")
    print(f"{'='*50}")

    client.close()


if __name__ == "__main__":
    main()
