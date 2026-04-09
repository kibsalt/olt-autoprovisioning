"""Fix Docker Hub connectivity and build/start containers."""

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


def run(client, cmd, check=True, timeout=600):
    print(f"  > {cmd[:180]}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        for line in out.split("\n")[:25]:
            print(f"    {line}")
    if err:
        for line in err.split("\n")[:10]:
            print(f"    {line}")
    if check and exit_code != 0:
        print(f"    Exit code: {exit_code}")
    return exit_code, out, err


def sudo(client, cmd, **kwargs):
    return run(client, f"echo '{PASSWORD}' | sudo -S bash -c '{cmd}'", **kwargs)


def main():
    print(f"Connecting to {SERVER}...")
    client = create_ssh_client()
    print("Connected!\n")

    # Check Docker Hub connectivity
    print("=== Checking Docker Hub Connectivity ===")
    run(client, "curl -sf --connect-timeout 10 https://registry-1.docker.io/v2/ && echo 'Docker Hub reachable' || echo 'Docker Hub unreachable'", check=False)
    run(client, "curl -sf --connect-timeout 10 https://auth.docker.io/ && echo 'Auth reachable' || echo 'Auth unreachable'", check=False)

    # Check DNS
    run(client, "nslookup registry-1.docker.io 2>/dev/null || dig registry-1.docker.io +short 2>/dev/null || host registry-1.docker.io 2>/dev/null || echo 'DNS tools not available'", check=False)
    run(client, "cat /etc/resolv.conf", check=False)

    # Try with different DNS if needed
    print("\n-- Trying to fix DNS --")
    sudo(client, "echo nameserver 8.8.8.8 > /etc/resolv.conf.bak && cp /etc/resolv.conf /etc/resolv.conf.orig", check=False)
    # Add Google DNS
    sudo(client, "grep -q 8.8.8.8 /etc/resolv.conf || echo nameserver 8.8.8.8 >> /etc/resolv.conf", check=False)
    sudo(client, "grep -q 1.1.1.1 /etc/resolv.conf || echo nameserver 1.1.1.1 >> /etc/resolv.conf", check=False)
    run(client, "cat /etc/resolv.conf", check=False)

    # Test again
    print("\n-- Testing connectivity after DNS fix --")
    run(client, "curl -sf --connect-timeout 15 https://registry-1.docker.io/v2/ && echo 'Docker Hub NOW reachable' || echo 'Still unreachable'", check=False)

    # Check if mariadb image exists locally
    print("\n=== Checking local Docker images ===")
    sudo(client, "docker images", check=False)

    # Try pulling mariadb
    print("\n-- Pulling MariaDB --")
    sudo(client, "docker pull mariadb:11", check=False, timeout=300)

    # Build API image
    print("\n-- Building API image --")
    sudo(client, f"cd {REMOTE_DIR} && docker compose build --no-cache", check=False, timeout=600)

    # Start containers
    print("\n-- Starting containers --")
    sudo(client, f"cd {REMOTE_DIR} && docker compose up -d", check=False)

    print("\n-- Waiting 25s --")
    time.sleep(25)

    # Status
    print("\n=== Container Status ===")
    sudo(client, f"cd {REMOTE_DIR} && docker compose ps")

    print("\n-- API logs --")
    sudo(client, f"cd {REMOTE_DIR} && docker compose logs --tail=40 api", check=False)

    print("\n-- MariaDB logs --")
    sudo(client, f"cd {REMOTE_DIR} && docker compose logs --tail=10 mariadb", check=False)

    # Verify
    print("\n=== Health Check ===")
    for i in range(4):
        time.sleep(5)
        code, out, _ = run(client, "curl -sf http://localhost:8000/health", check=False)
        if code == 0 and out:
            print(f"    API is UP: {out}")
            break
        print(f"    Attempt {i+1}: waiting...")

    print(f"\n  API:    http://{SERVER}:8000")
    print(f"  Docs:   http://{SERVER}:8000/docs")

    client.close()


if __name__ == "__main__":
    main()
