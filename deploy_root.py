"""Deploy via jtlacs user, using 'su -c' for root commands."""

import time
import paramiko

SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
ROOT_PASS = PASSWORD  # same password
REMOTE_DIR = f"/home/{USERNAME}/olt-provisioning-api"


def create_ssh_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
    return client


def run(client, cmd, check=True):
    print(f"  > {cmd[:120]}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        for line in out.split("\n")[:15]:
            print(f"    {line}")
    if err and exit_code != 0:
        print(f"    [ERR] {err[:200]}")
    if check and exit_code != 0:
        print(f"    Exit code: {exit_code}")
    return exit_code, out, err


def su_cmd(client, cmd, check=True):
    """Run command as root via su -c, piping password."""
    # Escape single quotes in command
    escaped = cmd.replace("'", "'\\''")
    full = f"echo '{ROOT_PASS}' | su -c '{escaped}'"
    return run(client, full, check=check)


def main():
    print(f"Connecting to {SERVER} as {USERNAME}...")
    client = create_ssh_client()
    print("Connected!\n")

    # ============================
    # 1. Add jtlacs to sudo + docker groups
    # ============================
    print("=== User Setup ===")
    su_cmd(client, f"usermod -aG sudo,docker {USERNAME}")
    run(client, f"id {USERNAME}")

    # ============================
    # 2. Security Hardening
    # ============================
    print("\n=== Security Hardening ===")

    print("\n-- System update --")
    su_cmd(client, "apt-get update -y", check=False)
    su_cmd(client, "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y", check=False)

    print("\n-- Installing security tools --")
    su_cmd(client, "DEBIAN_FRONTEND=noninteractive apt-get install -y ufw fail2ban unattended-upgrades curl htop", check=False)

    # UFW Firewall
    print("\n-- Configuring UFW firewall --")
    su_cmd(client, "ufw default deny incoming")
    su_cmd(client, "ufw default allow outgoing")
    su_cmd(client, "ufw allow 22/tcp")
    su_cmd(client, "ufw allow 8000/tcp")
    su_cmd(client, "ufw allow 443/tcp")
    su_cmd(client, "ufw allow 80/tcp")
    su_cmd(client, "ufw --force enable")
    su_cmd(client, "ufw status verbose")

    # fail2ban
    print("\n-- Configuring fail2ban --")
    su_cmd(client, "bash -c 'cat > /etc/fail2ban/jail.local << JAILEOF\n[sshd]\nenabled = true\nport = ssh\nfilter = sshd\nlogpath = /var/log/auth.log\nmaxretry = 5\nbantime = 3600\nfindtime = 600\nJAILEOF'", check=False)
    su_cmd(client, "systemctl enable fail2ban", check=False)
    su_cmd(client, "systemctl restart fail2ban", check=False)

    # SSH hardening
    print("\n-- Hardening SSH --")
    su_cmd(client, "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config")
    su_cmd(client, "sed -i 's/^#*MaxAuthTries.*/MaxAuthTries 3/' /etc/ssh/sshd_config")
    su_cmd(client, "sed -i 's/^#*ClientAliveInterval.*/ClientAliveInterval 300/' /etc/ssh/sshd_config")
    su_cmd(client, "sed -i 's/^#*ClientAliveCountMax.*/ClientAliveCountMax 2/' /etc/ssh/sshd_config")
    su_cmd(client, "sed -i 's/^#*X11Forwarding.*/X11Forwarding no/' /etc/ssh/sshd_config")
    su_cmd(client, "systemctl reload sshd || systemctl reload ssh", check=False)

    # Kernel hardening
    print("\n-- Kernel hardening --")
    sysctl_cmds = [
        "net.ipv4.conf.all.rp_filter = 1",
        "net.ipv4.conf.default.rp_filter = 1",
        "net.ipv4.icmp_echo_ignore_broadcasts = 1",
        "net.ipv4.conf.all.accept_source_route = 0",
        "net.ipv6.conf.all.accept_source_route = 0",
        "net.ipv4.conf.all.send_redirects = 0",
        "net.ipv4.conf.default.send_redirects = 0",
        "net.ipv4.tcp_syncookies = 1",
        "net.ipv4.tcp_max_syn_backlog = 2048",
        "net.ipv4.tcp_synack_retries = 2",
        "net.ipv4.conf.all.log_martians = 1",
        "net.ipv4.conf.all.accept_redirects = 0",
        "net.ipv6.conf.all.accept_redirects = 0",
        "net.ipv4.ip_forward = 1",
    ]
    content = "\\n".join(sysctl_cmds)
    su_cmd(client, f"bash -c 'echo -e \"{content}\" > /etc/sysctl.d/99-hardening.conf'", check=False)
    su_cmd(client, "sysctl --system > /dev/null 2>&1", check=False)

    # Unattended upgrades
    print("\n-- Enabling unattended security upgrades --")
    su_cmd(client, "dpkg-reconfigure -f noninteractive unattended-upgrades", check=False)

    print("\n-- Security hardening complete --")

    # ============================
    # 3. Generate Fernet key & update .env
    # ============================
    print("\n=== Configure .env ===")
    su_cmd(client, "pip3 install cryptography --break-system-packages 2>/dev/null || true", check=False)
    _, fernet_key, _ = run(client, "python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'", check=False)
    if not fernet_key or len(fernet_key) < 20:
        fernet_key = "REPLACE_WITH_REAL_KEY"

    env_content = f"""OLT_API_KEYS=bss-prod-key-change-me
OLT_DB_HOST=mariadb
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
OLT_DEBUG=false
MARIADB_ROOT_PASSWORD=JtlRootDb2024!"""

    run(client, f"cat > {REMOTE_DIR}/.env << 'ENVEOF'\n{env_content}\nENVEOF")
    run(client, f"chmod 600 {REMOTE_DIR}/.env")

    # ============================
    # 4. Docker needs newgrp for current session
    # ============================
    print("\n=== Docker Build & Start ===")
    # Use su to run docker as root since group change needs re-login
    su_cmd(client, f"cd {REMOTE_DIR} && docker compose build --no-cache", check=False)
    su_cmd(client, f"cd {REMOTE_DIR} && docker compose up -d", check=False)

    print("\n-- Waiting 20s for services --")
    time.sleep(20)
    su_cmd(client, f"cd {REMOTE_DIR} && docker compose ps")

    print("\n-- API logs --")
    su_cmd(client, f"cd {REMOTE_DIR} && docker compose logs --tail=30 api", check=False)

    print("\n-- MariaDB logs --")
    su_cmd(client, f"cd {REMOTE_DIR} && docker compose logs --tail=10 mariadb", check=False)

    # ============================
    # 5. Verify
    # ============================
    print("\n=== Verification ===")
    time.sleep(5)
    run(client, "curl -sf http://localhost:8000/health || echo 'Not ready yet, trying again...'", check=False)
    time.sleep(5)
    run(client, "curl -sf http://localhost:8000/health", check=False)
    su_cmd(client, "ufw status numbered")
    su_cmd(client, "systemctl status fail2ban --no-pager | head -8", check=False)

    print(f"\n{'='*50}")
    print(f"  Deployment Complete!")
    print(f"  API:    http://{SERVER}:8000")
    print(f"  Docs:   http://{SERVER}:8000/docs")
    print(f"  Health: http://{SERVER}:8000/health")
    print(f"{'='*50}")

    client.close()


if __name__ == "__main__":
    main()
