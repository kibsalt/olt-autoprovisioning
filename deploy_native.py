"""Deploy natively with Python + existing MariaDB (no Docker needed)."""

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
    if err and exit_code != 0:
        for line in err.split("\n")[:5]:
            print(f"    [ERR] {line}")
    if check and exit_code != 0:
        print(f"    Exit code: {exit_code}")
    return exit_code, out, err


def sudo(client, cmd, **kwargs):
    return run(client, f"echo '{PASSWORD}' | sudo -S bash -c '{cmd}'", **kwargs)


def main():
    print(f"Connecting to {SERVER}...")
    client = create_ssh_client()
    print("Connected!\n")

    # 1. Check what's available
    print("=== Checking Environment ===")
    run(client, "python3 --version")
    run(client, "pip3 --version", check=False)

    # Check if MariaDB is running locally
    run(client, "systemctl status mariadb --no-pager | head -5 2>/dev/null || echo 'No systemd mariadb'", check=False)
    sudo(client, "mariadb --version 2>/dev/null || mysql --version 2>/dev/null || echo 'No mariadb client'", check=False)

    # Check if there's a MariaDB docker container running
    sudo(client, "docker ps --format '{{.Names}} {{.Image}} {{.Status}}' 2>/dev/null || echo 'No docker ps'", check=False)

    # 2. Install Python dependencies
    print("\n=== Installing Python Dependencies ===")
    sudo(client, f"pip3 install --break-system-packages -r /dev/stdin << 'EOF'\nfastapi>=0.115\nuvicorn[standard]>=0.32\nsqlalchemy[asyncio]>=2.0\naiomysql>=0.2\nalembic>=1.14\nasyncssh>=2.17\npydantic-settings>=2.6\ncryptography>=44.0\nstructlog>=24.4\nafricastalking>=1.2\naiosmtplib>=3.0\njinja2>=3.1\nEOF", check=False, timeout=300)

    # Alternative: install from pyproject.toml
    sudo(client, f"cd {REMOTE_DIR} && pip3 install --break-system-packages . 2>/dev/null || pip3 install --break-system-packages fastapi uvicorn sqlalchemy aiomysql alembic asyncssh pydantic-settings cryptography structlog africastalking aiosmtplib jinja2", check=False, timeout=300)

    # 3. Setup MariaDB database
    print("\n=== Setting up MariaDB Database ===")
    # Check if mariadb is accessible (might be in Docker already)
    code, out, _ = sudo(client, "mariadb -u root -e 'SELECT 1' 2>/dev/null || mysql -u root -e 'SELECT 1' 2>/dev/null", check=False)
    if code != 0:
        print("    MariaDB not accessible with root without password, trying with docker...")
        # Check for running MariaDB in docker
        code2, out2, _ = sudo(client, "docker exec $(docker ps -q --filter ancestor=genieacs-db:v1 2>/dev/null || docker ps -q --filter name=mariadb 2>/dev/null) mariadb -u root -e 'SELECT 1' 2>/dev/null", check=False)
        if code2 == 0:
            print("    Found MariaDB in Docker!")
            # Get the container name
            _, container, _ = sudo(client, "docker ps --format '{{.Names}}' --filter ancestor=genieacs-db:v1 2>/dev/null || docker ps --format '{{.Names}}' --filter name=mariadb 2>/dev/null", check=False)
            print(f"    Container: {container}")

    # Try creating database and user
    db_setup_sql = """
CREATE DATABASE IF NOT EXISTS olt_provisioning CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'olt_api'@'%' IDENTIFIED BY 'JtlOltDb2024!';
CREATE USER IF NOT EXISTS 'olt_api'@'localhost' IDENTIFIED BY 'JtlOltDb2024!';
GRANT ALL PRIVILEGES ON olt_provisioning.* TO 'olt_api'@'%';
GRANT ALL PRIVILEGES ON olt_provisioning.* TO 'olt_api'@'localhost';
FLUSH PRIVILEGES;
"""
    sudo(client, f"mariadb -u root << 'SQLEOF'\n{db_setup_sql}\nSQLEOF", check=False)

    # 4. Update .env to use localhost instead of docker service name
    print("\n=== Updating .env for native deployment ===")
    _, fernet_key, _ = run(client, "python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'", check=False)
    if not fernet_key or len(fernet_key) < 20:
        fernet_key = "REPLACE_ME"

    env_content = f"""OLT_API_KEYS=bss-prod-key-change-me
OLT_DB_HOST=127.0.0.1
OLT_DB_PORT=3306
OLT_DB_USER=olt_api
OLT_DB_PASSWORD=JtlOltDb2024!
OLT_DB_NAME=olt_provisioning
OLT_CREDENTIAL_ENCRYPTION_KEY={fernet_key}
OLT_ACS_URL=http://197.232.61.253:7547
OLT_ACS_USERNAME=ACS
OLT_ACS_PASSWORD=jtl@acs
OLT_SSH_CONNECT_TIMEOUT=10
OLT_SSH_COMMAND_TIMEOUT=30
OLT_SMTP_HOST=smtp.gmail.com
OLT_SMTP_PORT=587
OLT_SMTP_USERNAME=
OLT_SMTP_PASSWORD=
OLT_SMTP_FROM_EMAIL=noreply@jtl.co.ke
OLT_SMTP_USE_TLS=true
OLT_AT_USERNAME=
OLT_AT_API_KEY=
OLT_AT_SENDER_ID=JTL
OLT_WIFI_SSID_PREFIX=JTL
OLT_SERVER_HOST=0.0.0.0
OLT_SERVER_PORT=8000
OLT_WORKERS=4
OLT_DEBUG=false"""

    run(client, f"cat > {REMOTE_DIR}/.env << 'ENVEOF'\n{env_content}\nENVEOF")
    run(client, f"chmod 600 {REMOTE_DIR}/.env")

    # 5. Run Alembic migrations
    print("\n=== Running Database Migrations ===")
    run(client, f"cd {REMOTE_DIR} && python3 -m alembic upgrade head 2>&1 || echo 'Migration may need tables created first'", check=False)

    # If alembic fails, create tables directly
    run(client, f"cd {REMOTE_DIR} && python3 -c 'from app.models.base import Base; from app.db.session import engine; import asyncio; asyncio.run(Base.metadata.create_all(engine))' 2>&1 || echo 'Will try sync approach'", check=False)

    # Try sync table creation
    run(client, f"""cd {REMOTE_DIR} && python3 << 'PYEOF'
from sqlalchemy import create_engine
from app.config import settings
from app.models.base import Base
import app.models  # register all models
engine = create_engine(settings.sync_database_url)
Base.metadata.create_all(engine)
print("Tables created successfully!")
engine.dispose()
PYEOF""", check=False)

    # 6. Create systemd service
    print("\n=== Creating systemd service ===")
    service_content = f"""[Unit]
Description=JTL OLT Provisioning API
After=network.target mariadb.service

[Service]
Type=simple
User={USERNAME}
WorkingDirectory={REMOTE_DIR}
EnvironmentFile={REMOTE_DIR}/.env
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"""

    sudo(client, f"cat > /etc/systemd/system/olt-api.service << 'SVCEOF'\n{service_content}\nSVCEOF", check=False)
    sudo(client, "systemctl daemon-reload")
    sudo(client, "systemctl enable olt-api")
    sudo(client, "systemctl start olt-api")

    print("\n-- Waiting 8s for service to start --")
    time.sleep(8)
    sudo(client, "systemctl status olt-api --no-pager | head -15")

    # 7. Verify
    print("\n=== Verification ===")
    for i in range(4):
        time.sleep(3)
        code, out, _ = run(client, "curl -sf http://localhost:8000/health", check=False)
        if code == 0 and out:
            print(f"    API is UP: {out}")
            break
        print(f"    Attempt {i+1}: waiting...")

    # Check logs if it failed
    if code != 0:
        print("\n-- Service logs --")
        sudo(client, "journalctl -u olt-api --no-pager -n 30", check=False)

    print(f"\n{'='*50}")
    print(f"  API:    http://{SERVER}:8000")
    print(f"  Docs:   http://{SERVER}:8000/docs")
    print(f"  Health: http://{SERVER}:8000/health")
    print(f"{'='*50}")

    client.close()


if __name__ == "__main__":
    main()
