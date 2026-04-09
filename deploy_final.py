"""Final deployment: UFW setup + Docker build with sudo (now that sudo is fixed)."""

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


def run(client, cmd, check=True):
    print(f"  > {cmd[:150]}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=600, get_pty=False)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        for line in out.split("\n")[:20]:
            print(f"    {line}")
        remaining = out.count("\n") - 20
        if remaining > 0:
            print(f"    ... ({remaining} more lines)")
    if err and exit_code != 0:
        print(f"    [ERR] {err[:300]}")
    if check and exit_code != 0:
        print(f"    Exit code: {exit_code}")
    return exit_code, out, err


def sudo(client, cmd, check=True):
    """Run command with sudo, piping password."""
    return run(client, f"echo '{PASSWORD}' | sudo -S {cmd}", check=check)


def main():
    print(f"Connecting to {SERVER}...")
    client = create_ssh_client()
    print("Connected!\n")

    # Verify sudo works now
    print("=== Testing sudo ===")
    code, out, _ = sudo(client, "whoami")
    if "root" not in out:
        print("ERROR: sudo still not working!")
        client.close()
        return
    print("sudo works!\n")

    # ============================
    # 1. UFW Firewall
    # ============================
    print("=== Configuring UFW Firewall ===")
    sudo(client, "/usr/sbin/ufw default deny incoming", check=False)
    sudo(client, "/usr/sbin/ufw default allow outgoing", check=False)
    sudo(client, "/usr/sbin/ufw allow 22/tcp", check=False)
    sudo(client, "/usr/sbin/ufw allow 8000/tcp", check=False)
    sudo(client, "/usr/sbin/ufw allow 443/tcp", check=False)
    sudo(client, "/usr/sbin/ufw allow 80/tcp", check=False)
    sudo(client, "/usr/sbin/ufw --force enable", check=False)
    sudo(client, "/usr/sbin/ufw status verbose")

    # ============================
    # 2. Ensure docker group membership is active
    # ============================
    print("\n=== Docker Setup ===")
    sudo(client, "usermod -aG docker jtlacs", check=False)

    # Use sudo for docker commands (group change needs re-login)
    print("\n-- Pulling MariaDB image --")
    sudo(client, "docker pull mariadb:11", check=False)

    print("\n-- Building API image --")
    sudo(client, f"cd {REMOTE_DIR} && docker compose build --no-cache", check=False)

    print("\n-- Starting containers --")
    sudo(client, f"cd {REMOTE_DIR} && docker compose up -d")

    print("\n-- Waiting 25s for services to initialize --")
    time.sleep(25)

    print("\n-- Container status --")
    sudo(client, f"cd {REMOTE_DIR} && docker compose ps")

    print("\n-- API container logs --")
    sudo(client, f"cd {REMOTE_DIR} && docker compose logs --tail=40 api", check=False)

    print("\n-- MariaDB container logs --")
    sudo(client, f"cd {REMOTE_DIR} && docker compose logs --tail=15 mariadb", check=False)

    # ============================
    # 3. Verify
    # ============================
    print("\n=== Verification ===")
    for attempt in range(3):
        time.sleep(5)
        code, out, _ = run(client, "curl -sf http://localhost:8000/health", check=False)
        if code == 0 and out:
            print(f"    Health check passed: {out}")
            break
        print(f"    Attempt {attempt + 1}: not ready yet...")

    # Try the docs page
    run(client, "curl -sf http://localhost:8000/docs | head -5 || echo 'Docs endpoint check'", check=False)

    # Security summary
    print("\n=== Security Summary ===")
    sudo(client, "/usr/sbin/ufw status numbered")
    sudo(client, "systemctl status fail2ban --no-pager | head -5", check=False)
    sudo(client, "grep PermitRootLogin /etc/ssh/sshd_config | head -1", check=False)
    sudo(client, "grep MaxAuthTries /etc/ssh/sshd_config | head -1", check=False)

    print(f"\n{'='*50}")
    print(f"  Deployment Complete!")
    print(f"  API:    http://{SERVER}:8000")
    print(f"  Docs:   http://{SERVER}:8000/docs")
    print(f"  Health: http://{SERVER}:8000/health")
    print(f"{'='*50}")

    client.close()


if __name__ == "__main__":
    main()
