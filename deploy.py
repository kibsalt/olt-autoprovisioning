"""Deployment script for OLT Provisioning API to production server."""

import os
import sys
import time

import paramiko


SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE_DIR = "/home/jtlacs/olt-provisioning-api"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def create_ssh_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
    return client


def run_cmd(client, cmd, check=True):
    print(f"  > {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(f"    {out[:500]}")
    if err and exit_code != 0:
        print(f"    [ERR] {err[:300]}")
    if check and exit_code != 0:
        print(f"    Command failed with exit code {exit_code}")
    return exit_code, out, err


def sudo_cmd(client, cmd, check=True):
    """Run command with sudo, piping password via stdin."""
    full_cmd = f"echo '{PASSWORD}' | sudo -S {cmd}"
    return run_cmd(client, full_cmd, check=check)


def upload_project(client):
    sftp = client.open_sftp()

    for root, dirs, files in os.walk(PROJECT_DIR):
        rel_root = os.path.relpath(root, PROJECT_DIR).replace("\\", "/")
        if any(skip in rel_root for skip in [
            "__pycache__", ".git", "venv", ".venv", "node_modules", ".claude", "deploy.py"
        ]):
            continue

        remote_root = f"{REMOTE_DIR}/{rel_root}" if rel_root != "." else REMOTE_DIR
        try:
            sftp.stat(remote_root)
        except FileNotFoundError:
            run_cmd(client, f"mkdir -p {remote_root}")

        for f in files:
            if f.endswith((".pyc", ".pyo")) or f == "deploy.py":
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

    # 1. Server info
    print("=== Server Info ===")
    run_cmd(client, "uname -a")
    run_cmd(client, "cat /etc/os-release | head -3")
    run_cmd(client, "free -h | head -2")
    run_cmd(client, "df -h / | tail -1")

    # 2. Security hardening
    print("\n=== Security Hardening ===")

    print("\n-- Updating system packages --")
    sudo_cmd(client, "apt-get update -y", check=False)
    sudo_cmd(client, "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y", check=False)

    print("\n-- Installing security tools --")
    sudo_cmd(client, "DEBIAN_FRONTEND=noninteractive apt-get install -y ufw fail2ban unattended-upgrades apt-listchanges curl", check=False)

    # UFW firewall
    print("\n-- Configuring UFW firewall --")
    sudo_cmd(client, "ufw default deny incoming", check=False)
    sudo_cmd(client, "ufw default allow outgoing", check=False)
    sudo_cmd(client, "ufw allow 22/tcp", check=False)
    sudo_cmd(client, "ufw allow 8000/tcp", check=False)
    sudo_cmd(client, "ufw allow 443/tcp", check=False)
    sudo_cmd(client, "ufw allow 80/tcp", check=False)
    sudo_cmd(client, "ufw --force enable", check=False)
    sudo_cmd(client, "ufw status verbose")

    # fail2ban
    print("\n-- Configuring fail2ban --")
    fail2ban_conf = (
        "[sshd]\\n"
        "enabled = true\\n"
        "port = ssh\\n"
        "filter = sshd\\n"
        "logpath = /var/log/auth.log\\n"
        "maxretry = 5\\n"
        "bantime = 3600\\n"
        "findtime = 600"
    )
    sudo_cmd(client, f"bash -c 'echo -e \"{fail2ban_conf}\" > /etc/fail2ban/jail.local'", check=False)
    sudo_cmd(client, "systemctl enable fail2ban", check=False)
    sudo_cmd(client, "systemctl restart fail2ban", check=False)

    # SSH hardening
    print("\n-- Hardening SSH --")
    ssh_cmds = [
        "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config",
        "sed -i 's/^#*MaxAuthTries.*/MaxAuthTries 3/' /etc/ssh/sshd_config",
        "sed -i 's/^#*ClientAliveInterval.*/ClientAliveInterval 300/' /etc/ssh/sshd_config",
        "sed -i 's/^#*ClientAliveCountMax.*/ClientAliveCountMax 2/' /etc/ssh/sshd_config",
        "systemctl reload sshd || systemctl reload ssh",
    ]
    for cmd in ssh_cmds:
        sudo_cmd(client, cmd, check=False)

    # Kernel hardening
    print("\n-- Kernel hardening --")
    sysctl_lines = [
        "net.ipv4.conf.all.rp_filter=1",
        "net.ipv4.conf.default.rp_filter=1",
        "net.ipv4.icmp_echo_ignore_broadcasts=1",
        "net.ipv4.conf.all.accept_source_route=0",
        "net.ipv6.conf.all.accept_source_route=0",
        "net.ipv4.conf.all.send_redirects=0",
        "net.ipv4.conf.default.send_redirects=0",
        "net.ipv4.tcp_syncookies=1",
        "net.ipv4.tcp_max_syn_backlog=2048",
        "net.ipv4.tcp_synack_retries=2",
        "net.ipv4.conf.all.log_martians=1",
        "net.ipv4.conf.all.accept_redirects=0",
        "net.ipv6.conf.all.accept_redirects=0",
    ]
    for line in sysctl_lines:
        sudo_cmd(client, f"bash -c 'echo \"{line}\" >> /etc/sysctl.d/99-hardening.conf'", check=False)
    sudo_cmd(client, "sysctl --system > /dev/null 2>&1", check=False)

    # Unattended upgrades
    print("\n-- Enabling unattended security upgrades --")
    sudo_cmd(client, "bash -c 'echo unattended-upgrades unattended-upgrades/enable_auto_updates boolean true | debconf-set-selections'", check=False)
    sudo_cmd(client, "dpkg-reconfigure -f noninteractive unattended-upgrades", check=False)

    print("\n-- Security hardening complete --")

    # 3. Docker check
    print("\n=== Docker Setup ===")
    exit_code, out, _ = run_cmd(client, "docker --version", check=False)
    if exit_code != 0:
        print("Docker not found, installing...")
        sudo_cmd(client, "bash -c 'curl -fsSL https://get.docker.com | sh'", check=False)
        sudo_cmd(client, "usermod -aG docker jtlacs", check=False)
        sudo_cmd(client, "systemctl enable docker", check=False)
        sudo_cmd(client, "systemctl start docker", check=False)
    else:
        print(f"Docker installed: {out}")
    run_cmd(client, "docker compose version", check=False)

    # 4. Create project directory
    print("\n=== Deploying Application ===")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/alembic/versions")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/app/api/v1")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/app/models")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/app/schemas")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/app/services")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/app/olt_driver")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/app/notifications")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/app/db")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/app/utils")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/tests/test_api")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/tests/test_services")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/tests/test_olt_driver")

    # 5. Upload project files
    print("\n-- Uploading project files --")
    upload_project(client)

    # 6. Create .env
    print("\n-- Creating .env file --")
    # Generate Fernet key
    _, fernet_key, _ = run_cmd(client, "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" 2>/dev/null || echo 'placeholder'", check=False)
    if not fernet_key or fernet_key == "placeholder":
        fernet_key = "GENERATE_AFTER_DOCKER_BUILD"

    env_lines = [
        f"OLT_API_KEYS=bss-prod-key-change-me",
        f"OLT_DB_HOST=mariadb",
        f"OLT_DB_PORT=3306",
        f"OLT_DB_USER=olt_api",
        f"OLT_DB_PASSWORD=JtlOltDb2024!",
        f"OLT_DB_NAME=olt_provisioning",
        f"OLT_CREDENTIAL_ENCRYPTION_KEY={fernet_key}",
        f"OLT_ACS_URL=http://197.232.61.253:7547",
        f"OLT_ACS_USERNAME=ACS",
        f"OLT_ACS_PASSWORD=jtl@acs",
        f"OLT_SSH_CONNECT_TIMEOUT=10",
        f"OLT_SSH_COMMAND_TIMEOUT=30",
        f"OLT_SMTP_HOST=smtp.gmail.com",
        f"OLT_SMTP_PORT=587",
        f"OLT_SMTP_USERNAME=",
        f"OLT_SMTP_PASSWORD=",
        f"OLT_SMTP_FROM_EMAIL=noreply@jtl.co.ke",
        f"OLT_SMTP_USE_TLS=true",
        f"OLT_AT_USERNAME=",
        f"OLT_AT_API_KEY=",
        f"OLT_AT_SENDER_ID=JTL",
        f"OLT_WIFI_SSID_PREFIX=JTL",
        f"OLT_SERVER_HOST=0.0.0.0",
        f"OLT_SERVER_PORT=8000",
        f"OLT_WORKERS=4",
        f"OLT_DEBUG=false",
        f"MARIADB_ROOT_PASSWORD=JtlRootDb2024!",
    ]
    env_content = "\\n".join(env_lines)
    run_cmd(client, f"bash -c 'echo -e \"{env_content}\" > {REMOTE_DIR}/.env'")

    # 7. Build and start
    print("\n-- Building and starting containers --")
    run_cmd(client, f"cd {REMOTE_DIR} && docker compose pull mariadb", check=False)
    run_cmd(client, f"cd {REMOTE_DIR} && docker compose build --no-cache", check=False)
    run_cmd(client, f"cd {REMOTE_DIR} && docker compose up -d", check=False)

    # 8. Wait and check
    print("\n-- Waiting for services to start (15s) --")
    time.sleep(15)
    run_cmd(client, f"cd {REMOTE_DIR} && docker compose ps")
    run_cmd(client, f"cd {REMOTE_DIR} && docker compose logs --tail=30 api", check=False)

    # 9. Verify
    print("\n=== Verification ===")
    run_cmd(client, "curl -sf http://localhost:8000/health || echo 'API not responding yet'", check=False)

    print(f"\n=== Deployment Complete ===")
    print(f"  API: http://{SERVER}:8000")
    print(f"  Docs: http://{SERVER}:8000/docs")
    print(f"  Health: http://{SERVER}:8000/health")

    client.close()


if __name__ == "__main__":
    main()
