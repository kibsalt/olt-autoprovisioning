"""Fix pip install (typing_extensions conflict) + MariaDB setup + restart."""

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


def run(client, cmd, check=True, timeout=300):
    print(f"  > {cmd[:180]}")
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

    # 1. Force install packages, ignoring typing_extensions conflict
    print("=== Installing Python Packages (force) ===")
    sudo(client, "pip3 install --break-system-packages --ignore-installed typing_extensions", check=False, timeout=120)

    packages = "fastapi uvicorn sqlalchemy aiomysql alembic asyncssh pydantic-settings cryptography structlog africastalking aiosmtplib jinja2 pymysql"
    sudo(client, f"pip3 install --break-system-packages {packages}", check=False, timeout=300)

    # Verify installation
    run(client, "python3 -c 'import uvicorn; import fastapi; import sqlalchemy; print(\"All imports OK\")'")

    # 2. Setup MariaDB database (fix SQL quoting)
    print("\n=== Setting up MariaDB Database ===")
    # Write SQL to a file to avoid quoting hell
    sql_setup = """CREATE DATABASE IF NOT EXISTS olt_provisioning CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'olt_api'@'%' IDENTIFIED BY 'JtlOltDb2024!';
CREATE USER IF NOT EXISTS 'olt_api'@'localhost' IDENTIFIED BY 'JtlOltDb2024!';
GRANT ALL PRIVILEGES ON olt_provisioning.* TO 'olt_api'@'%';
GRANT ALL PRIVILEGES ON olt_provisioning.* TO 'olt_api'@'localhost';
FLUSH PRIVILEGES;
"""
    run(client, f"cat > /tmp/db_setup.sql << 'SQLEOF'\n{sql_setup}\nSQLEOF")
    sudo(client, "mariadb -u root < /tmp/db_setup.sql")
    run(client, "rm /tmp/db_setup.sql")

    # Verify DB access
    run(client, "python3 -c \"import pymysql; c=pymysql.connect(host='127.0.0.1',user='olt_api',password='JtlOltDb2024!',database='olt_provisioning'); print('DB connection OK'); c.close()\"", check=False)

    # 3. Create tables
    print("\n=== Creating Database Tables ===")
    run(client, f"""cd {REMOTE_DIR} && python3 << 'PYEOF'
from sqlalchemy import create_engine
from app.config import settings
from app.models.base import Base
import app.models
engine = create_engine(settings.sync_database_url)
Base.metadata.create_all(engine)
print("Tables created successfully!")
engine.dispose()
PYEOF""")

    # 4. Restart service
    print("\n=== Restarting API Service ===")
    sudo(client, "systemctl restart olt-api")

    print("-- Waiting 8s --")
    time.sleep(8)
    sudo(client, "systemctl status olt-api --no-pager | head -12")

    # 5. Verify
    print("\n=== Health Check ===")
    for i in range(5):
        time.sleep(3)
        code, out, _ = run(client, "curl -sf http://localhost:8000/health", check=False)
        if code == 0 and "ok" in out.lower():
            print(f"\n    API is LIVE: {out}")
            break
        print(f"    Attempt {i+1}: waiting...")
    else:
        print("\n-- Checking logs --")
        sudo(client, "journalctl -u olt-api --no-pager -n 20")

    # 6. Remove other Docker containers (user requested)
    print("\n=== Removing Other Docker Containers ===")
    sudo(client, "docker stop jtl-portal-v1 genieacs-v1 genieacs-dbv1 2>/dev/null || true", check=False)
    sudo(client, "docker rm jtl-portal-v1 genieacs-v1 genieacs-dbv1 2>/dev/null || true", check=False)
    sudo(client, "docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}'", check=False)

    # Test API key auth
    print("\n=== Testing API ===")
    run(client, "curl -s http://localhost:8000/api/v1/olts -H 'X-API-Key: bss-prod-key-change-me' | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8000/api/v1/olts -H 'X-API-Key: bss-prod-key-change-me'", check=False)

    print(f"\n{'='*50}")
    print(f"  API:    http://{SERVER}:8000")
    print(f"  Docs:   http://{SERVER}:8000/docs")
    print(f"  Health: http://{SERVER}:8000/health")
    print(f"{'='*50}")

    client.close()


if __name__ == "__main__":
    main()
