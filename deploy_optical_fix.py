"""Deploy optical/power level fix — copies files into running docker containers."""

import os
import paramiko

PASSWORD = "bssadmin+ZTE"
USERNAME = "jtlacs"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONTAINER = "jtl_olt_api"

SERVERS = [
    ("192.168.14.4",  "local"),
    ("172.16.37.18",  "production"),
]

# local_relative_path -> container absolute path
FILES = [
    ("app/olt_driver/zxan_driver.py",     "/app/app/olt_driver/zxan_driver.py"),
    ("app/olt_driver/response_parser.py", "/app/app/olt_driver/response_parser.py"),
    ("app/services/onu_service.py",       "/app/app/services/onu_service.py"),
    ("app/services/alarm_poller.py",      "/app/app/services/alarm_poller.py"),
    ("app/schemas/onu.py",                "/app/app/schemas/onu.py"),
    ("docs/bss-portal.html",              "/app/docs/bss-portal.html"),
]


def connect(host):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USERNAME, password=PASSWORD, timeout=15)
    return client


def run(client, cmd, timeout=90):
    print(f"  $ {cmd[:200]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    combined = (out + "\n" + err).strip()
    for line in combined.split("\n"):
        if line.strip():
            print(f"    {line}")
    return code, out


def upload_and_cp(client, local_rel, container_path):
    """Upload file to /tmp on remote then docker cp into container."""
    local = os.path.join(PROJECT_DIR, local_rel)
    tmp = f"/tmp/_dep_{os.path.basename(local)}"
    with open(local, "rb") as f:
        data = f.read()
    sftp = client.open_sftp()
    with sftp.file(tmp, "wb") as rf:
        rf.write(data)
    sftp.close()
    code, out = run(client, f"docker cp {tmp} {CONTAINER}:{container_path} && echo OK")
    run(client, f"rm -f {tmp}")
    return "OK" in out


def deploy(host, label):
    print(f"\n{'='*60}")
    print(f"  Deploying to {label} ({host})")
    print(f"{'='*60}")
    client = connect(host)
    print("  Connected.")

    # Verify container running
    code, out = run(client, f"docker inspect --format='{{{{.State.Running}}}}' {CONTAINER} 2>/dev/null")
    if "true" not in out.lower():
        print(f"  ERROR: container {CONTAINER} not running!")
        client.close()
        return

    # Verify expected paths exist in container
    run(client, f"docker exec {CONTAINER} ls /app/app/olt_driver/ 2>/dev/null | head -5")

    print("\n--- Uploading files ---")
    results = []
    for local_rel, container_path in FILES:
        ok = upload_and_cp(client, local_rel, container_path)
        status = "OK" if ok else "FAIL"
        print(f"    [{status}] {local_rel}")
        results.append((status, local_rel))

    if any(s == "FAIL" for s, _ in results):
        print("\n  Some files failed — checking actual container paths:")
        run(client, f"docker exec {CONTAINER} find /app -name 'alarm_poller.py' 2>/dev/null")
        client.close()
        return

    print("\n--- Restarting container ---")
    run(client, f"docker restart {CONTAINER}", timeout=60)

    print("\n--- API logs (last 25 lines) ---")
    run(client, f"docker logs --tail=25 {CONTAINER} 2>&1", timeout=30)

    client.close()
    print(f"\n  Done: {label}")


if __name__ == "__main__":
    for host, label in SERVERS:
        try:
            deploy(host, label)
        except Exception as e:
            print(f"  FAILED ({label}): {e}")
    print("\nAll done.")
