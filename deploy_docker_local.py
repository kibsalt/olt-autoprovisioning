"""Build Docker image using local base + fix code issues, then run."""

import os
import time
import paramiko

SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE_DIR = f"/home/{USERNAME}/olt-provisioning-api"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def create_ssh_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
    return client


def run(client, cmd, check=True, timeout=600):
    print(f"  > {cmd[:200]}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        for line in out.split("\n")[:25]:
            print(f"    {line}")
    if err:
        for line in err.split("\n")[:8]:
            print(f"    [stderr] {line}")
    return exit_code, out, err


def sudo(client, cmd, **kwargs):
    return run(client, f"echo '{PASSWORD}' | sudo -S bash -c '{cmd}'", **kwargs)


def upload_file(client, local_path, remote_path):
    sftp = client.open_sftp()
    sftp.put(local_path, remote_path)
    sftp.close()


def upload_project(client):
    sftp = client.open_sftp()
    for root, dirs, files in os.walk(PROJECT_DIR):
        rel_root = os.path.relpath(root, PROJECT_DIR).replace("\\", "/")
        if any(skip in rel_root for skip in ["__pycache__", ".git", "venv", ".venv", "node_modules", ".claude", "deploy"]):
            continue
        remote_root = f"{REMOTE_DIR}/{rel_root}" if rel_root != "." else REMOTE_DIR
        try:
            sftp.stat(remote_root)
        except FileNotFoundError:
            run(client, f"mkdir -p {remote_root}")
        for f in files:
            if f.endswith((".pyc", ".pyo")) or f.startswith("deploy"):
                continue
            local_path = os.path.join(root, f)
            remote_path = f"{remote_root}/{f}"
            print(f"  Uploading: {remote_path}")
            sftp.put(local_path, remote_path)
    sftp.close()


def main():
    print(f"Connecting to {SERVER}...")
    client = create_ssh_client()
    print("Connected!\n")

    # Check available Docker images
    print("=== Available Docker Images ===")
    sudo(client, "docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}'")

    # Check Docker Hub connectivity
    code, _, _ = run(client, "curl -sf --connect-timeout 10 https://registry-1.docker.io/v2/ && echo 'OK' || echo 'BLOCKED'", check=False)

    # Re-upload all project files with fixes
    print("\n=== Uploading Fixed Project Files ===")
    upload_project(client)

    # Create a Dockerfile that builds from debian (which may be cached)
    print("\n=== Creating Local Dockerfile ===")
    dockerfile = """FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \\
    python3 python3-pip python3-venv \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml .
RUN pip install --no-cache-dir fastapi uvicorn[standard] sqlalchemy[asyncio] aiomysql alembic asyncssh pydantic-settings cryptography structlog africastalking aiosmtplib jinja2 pymysql

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
"""
    run(client, f"cat > {REMOTE_DIR}/Dockerfile << 'DEOF'\n{dockerfile}\nDEOF")

    # Update docker-compose to use host network for MariaDB (use local mariadb)
    compose = """services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
    network_mode: host
"""
    run(client, f"cat > {REMOTE_DIR}/docker-compose.yml << 'CEOF'\n{compose}\nCEOF")

    # Update .env to use 127.0.0.1 for DB (host network mode)
    _, fernet_key, _ = run(client, "python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'", check=False)
    if not fernet_key or len(fernet_key) < 20:
        fernet_key = "KY9H8mOJADlRi011uMnA5KHn3ZTML8mq9pJz6uY1NoQ="

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

    # Stop old service if running
    sudo(client, "systemctl stop olt-api 2>/dev/null || true", check=False)

    # Build Docker image
    print("\n=== Building Docker Image ===")
    sudo(client, f"cd {REMOTE_DIR} && docker compose build --no-cache", timeout=600)

    # Start
    print("\n=== Starting Container ===")
    sudo(client, f"cd {REMOTE_DIR} && docker compose up -d")

    print("-- Waiting 15s --")
    time.sleep(15)

    sudo(client, f"cd {REMOTE_DIR} && docker compose ps")
    sudo(client, f"cd {REMOTE_DIR} && docker compose logs --tail=30", check=False)

    # Health check
    print("\n=== Health Check ===")
    for i in range(5):
        time.sleep(5)
        code, out, _ = run(client, "curl -sf http://localhost:8000/health", check=False)
        if code == 0 and out:
            print(f"\n    API is LIVE: {out}")
            break
        print(f"    Attempt {i+1}...")
    else:
        sudo(client, f"cd {REMOTE_DIR} && docker compose logs --tail=30")

    # Test API
    print("\n=== API Test ===")
    run(client, "curl -s http://localhost:8000/api/v1/olts -H 'X-API-Key: bss-prod-key-change-me'", check=False)

    print(f"\n  API: http://{SERVER}:8000")
    print(f"  Docs: http://{SERVER}:8000/docs")

    client.close()


if __name__ == "__main__":
    main()
