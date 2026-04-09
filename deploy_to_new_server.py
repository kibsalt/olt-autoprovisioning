"""
Full deployment: upload both APIs + unified docker-compose to 192.168.14.4
and bring up all containers (MariaDB, OLT API, M6K API).

Usage:
  cd D:/Claude/projects
  python deploy_to_new_server.py
"""

import os
import time
import paramiko
import stat

SERVER   = "192.168.14.4"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE   = "/home/jtlacs/jtl-automation"
LOCAL    = os.path.dirname(os.path.abspath(__file__))

# ── Files to upload ────────────────────────────────────────────────────────
# Format: (local_relative_path, remote_relative_path)
# Both relative to LOCAL (projects/) and REMOTE respectively
TREE = {
    # ── Top-level compose + env ──────────────────────────────────────────
    "docker-compose.yml": "docker-compose.yml",
    ".env":               ".env",

    # ── OLT Provisioning API ─────────────────────────────────────────────
    "olt-provisioning-api/Dockerfile":            "olt-provisioning-api/Dockerfile",
    "olt-provisioning-api/docker-entrypoint.sh":  "olt-provisioning-api/docker-entrypoint.sh",
    "olt-provisioning-api/.dockerignore":         "olt-provisioning-api/.dockerignore",
    "olt-provisioning-api/pyproject.toml":        "olt-provisioning-api/pyproject.toml",
    "olt-provisioning-api/alembic.ini":           "olt-provisioning-api/alembic.ini",
    # app/
    "olt-provisioning-api/app/__init__.py":                      "olt-provisioning-api/app/__init__.py",
    "olt-provisioning-api/app/main.py":                          "olt-provisioning-api/app/main.py",
    "olt-provisioning-api/app/config.py":                        "olt-provisioning-api/app/config.py",
    "olt-provisioning-api/app/dependencies.py":                  "olt-provisioning-api/app/dependencies.py",
    # api
    "olt-provisioning-api/app/api/__init__.py":                  "olt-provisioning-api/app/api/__init__.py",
    "olt-provisioning-api/app/api/router.py":                    "olt-provisioning-api/app/api/router.py",
    "olt-provisioning-api/app/api/middleware.py":                "olt-provisioning-api/app/api/middleware.py",
    "olt-provisioning-api/app/api/v1/__init__.py":               "olt-provisioning-api/app/api/v1/__init__.py",
    "olt-provisioning-api/app/api/v1/olts.py":                   "olt-provisioning-api/app/api/v1/olts.py",
    "olt-provisioning-api/app/api/v1/onus.py":                   "olt-provisioning-api/app/api/v1/onus.py",
    "olt-provisioning-api/app/api/v1/services.py":               "olt-provisioning-api/app/api/v1/services.py",
    "olt-provisioning-api/app/api/v1/vlans.py":                  "olt-provisioning-api/app/api/v1/vlans.py",
    "olt-provisioning-api/app/api/v1/bandwidth.py":              "olt-provisioning-api/app/api/v1/bandwidth.py",
    "olt-provisioning-api/app/api/v1/operations.py":             "olt-provisioning-api/app/api/v1/operations.py",
    "olt-provisioning-api/app/api/bss/__init__.py":              "olt-provisioning-api/app/api/bss/__init__.py",
    "olt-provisioning-api/app/api/bss/provision.py":             "olt-provisioning-api/app/api/bss/provision.py",
    # models
    "olt-provisioning-api/app/models/__init__.py":               "olt-provisioning-api/app/models/__init__.py",
    "olt-provisioning-api/app/models/base.py":                   "olt-provisioning-api/app/models/base.py",
    "olt-provisioning-api/app/models/olt.py":                    "olt-provisioning-api/app/models/olt.py",
    "olt-provisioning-api/app/models/onu.py":                    "olt-provisioning-api/app/models/onu.py",
    "olt-provisioning-api/app/models/service_profile.py":        "olt-provisioning-api/app/models/service_profile.py",
    "olt-provisioning-api/app/models/vlan.py":                   "olt-provisioning-api/app/models/vlan.py",
    "olt-provisioning-api/app/models/bandwidth_profile.py":      "olt-provisioning-api/app/models/bandwidth_profile.py",
    "olt-provisioning-api/app/models/audit_log.py":              "olt-provisioning-api/app/models/audit_log.py",
    "olt-provisioning-api/app/models/notification.py":           "olt-provisioning-api/app/models/notification.py",
    # schemas
    "olt-provisioning-api/app/schemas/__init__.py":              "olt-provisioning-api/app/schemas/__init__.py",
    "olt-provisioning-api/app/schemas/common.py":                "olt-provisioning-api/app/schemas/common.py",
    "olt-provisioning-api/app/schemas/olt.py":                   "olt-provisioning-api/app/schemas/olt.py",
    "olt-provisioning-api/app/schemas/onu.py":                   "olt-provisioning-api/app/schemas/onu.py",
    "olt-provisioning-api/app/schemas/service_profile.py":       "olt-provisioning-api/app/schemas/service_profile.py",
    "olt-provisioning-api/app/schemas/vlan.py":                  "olt-provisioning-api/app/schemas/vlan.py",
    "olt-provisioning-api/app/schemas/bandwidth_profile.py":     "olt-provisioning-api/app/schemas/bandwidth_profile.py",
    "olt-provisioning-api/app/schemas/operations.py":            "olt-provisioning-api/app/schemas/operations.py",
    "olt-provisioning-api/app/schemas/provision.py":             "olt-provisioning-api/app/schemas/provision.py",
    # services
    "olt-provisioning-api/app/services/__init__.py":             "olt-provisioning-api/app/services/__init__.py",
    "olt-provisioning-api/app/services/olt_service.py":          "olt-provisioning-api/app/services/olt_service.py",
    "olt-provisioning-api/app/services/onu_service.py":          "olt-provisioning-api/app/services/onu_service.py",
    "olt-provisioning-api/app/services/service_profile_svc.py":  "olt-provisioning-api/app/services/service_profile_svc.py",
    "olt-provisioning-api/app/services/vlan_service.py":         "olt-provisioning-api/app/services/vlan_service.py",
    "olt-provisioning-api/app/services/bandwidth_service.py":    "olt-provisioning-api/app/services/bandwidth_service.py",
    "olt-provisioning-api/app/services/audit_service.py":        "olt-provisioning-api/app/services/audit_service.py",
    "olt-provisioning-api/app/services/provision_service.py":    "olt-provisioning-api/app/services/provision_service.py",
    # olt_driver
    "olt-provisioning-api/app/olt_driver/__init__.py":           "olt-provisioning-api/app/olt_driver/__init__.py",
    "olt-provisioning-api/app/olt_driver/base.py":               "olt-provisioning-api/app/olt_driver/base.py",
    "olt-provisioning-api/app/olt_driver/ssh_client.py":         "olt-provisioning-api/app/olt_driver/ssh_client.py",
    "olt-provisioning-api/app/olt_driver/zxan_driver.py":        "olt-provisioning-api/app/olt_driver/zxan_driver.py",
    "olt-provisioning-api/app/olt_driver/titan_driver.py":       "olt-provisioning-api/app/olt_driver/titan_driver.py",
    "olt-provisioning-api/app/olt_driver/driver_factory.py":     "olt-provisioning-api/app/olt_driver/driver_factory.py",
    "olt-provisioning-api/app/olt_driver/response_parser.py":    "olt-provisioning-api/app/olt_driver/response_parser.py",
    "olt-provisioning-api/app/olt_driver/exceptions.py":         "olt-provisioning-api/app/olt_driver/exceptions.py",
    # utils
    "olt-provisioning-api/app/utils/__init__.py":                "olt-provisioning-api/app/utils/__init__.py",
    "olt-provisioning-api/app/utils/crypto.py":                  "olt-provisioning-api/app/utils/crypto.py",
    "olt-provisioning-api/app/utils/packages.py":                "olt-provisioning-api/app/utils/packages.py",
    "olt-provisioning-api/app/utils/wifi.py":                    "olt-provisioning-api/app/utils/wifi.py",
    "olt-provisioning-api/app/utils/acs_client.py":              "olt-provisioning-api/app/utils/acs_client.py",
    # notifications
    "olt-provisioning-api/app/notifications/__init__.py":        "olt-provisioning-api/app/notifications/__init__.py",
    "olt-provisioning-api/app/notifications/email_service.py":   "olt-provisioning-api/app/notifications/email_service.py",
    "olt-provisioning-api/app/notifications/sms_service.py":     "olt-provisioning-api/app/notifications/sms_service.py",
    "olt-provisioning-api/app/notifications/whatsapp_service.py":"olt-provisioning-api/app/notifications/whatsapp_service.py",
    "olt-provisioning-api/app/notifications/notify.py":          "olt-provisioning-api/app/notifications/notify.py",
    # db
    "olt-provisioning-api/app/db/__init__.py":                   "olt-provisioning-api/app/db/__init__.py",
    "olt-provisioning-api/app/db/session.py":                    "olt-provisioning-api/app/db/session.py",
    # alembic
    "olt-provisioning-api/alembic/env.py":                       "olt-provisioning-api/alembic/env.py",
    "olt-provisioning-api/alembic/script.py.mako":               "olt-provisioning-api/alembic/script.py.mako",
    "olt-provisioning-api/alembic/versions/0001_add_others_model_and_olt_description.py":
        "olt-provisioning-api/alembic/versions/0001_add_others_model_and_olt_description.py",
    # docs (served as static files from /portal)
    "olt-provisioning-api/docs/bss-portal.html":                 "olt-provisioning-api/docs/bss-portal.html",
    "olt-provisioning-api/docs/api-documentation.html":          "olt-provisioning-api/docs/api-documentation.html",
    "olt-provisioning-api/docs/executive-summary.html":          "olt-provisioning-api/docs/executive-summary.html",

    # ── M6K P2P Circuit API ──────────────────────────────────────────────
    "m6k-p2p-api/Dockerfile":          "m6k-p2p-api/Dockerfile",
    "m6k-p2p-api/.dockerignore":       "m6k-p2p-api/.dockerignore",
    "m6k-p2p-api/pyproject.toml":      "m6k-p2p-api/pyproject.toml",
    "m6k-p2p-api/config.yaml":         "m6k-p2p-api/config.yaml",
    "m6k-p2p-api/app/__init__.py":     "m6k-p2p-api/app/__init__.py",
    "m6k-p2p-api/app/main.py":         "m6k-p2p-api/app/main.py",
    "m6k-p2p-api/app/models.py":       "m6k-p2p-api/app/models.py",
    "m6k-p2p-api/app/config.py":       "m6k-p2p-api/app/config.py",
    "m6k-p2p-api/app/ssh_client.py":   "m6k-p2p-api/app/ssh_client.py",
    "m6k-p2p-api/app/circuit_builder.py": "m6k-p2p-api/app/circuit_builder.py",
    "m6k-p2p-api/app/circuit_service.py": "m6k-p2p-api/app/circuit_service.py",
    "m6k-p2p-api/app/audit_log.py":    "m6k-p2p-api/app/audit_log.py",
}


# ── Helpers ────────────────────────────────────────────────────────────────

def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
    return client


def run(client, cmd, timeout=120, quiet=False):
    if not quiet:
        print(f"  $ {cmd[:160]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    combined = out or err
    if combined and not quiet:
        for line in combined.split("\n")[:15]:
            print(f"    {line}")
    return rc, out


def sudo(client, cmd, **kw):
    return run(client, f"echo '{PASSWORD}' | sudo -S sh -c \"{cmd}\"", **kw)


def mkdirs_sftp(sftp, remote_path):
    """Recursively create remote directories (absolute path)."""
    # Build list of all ancestor paths
    parts = remote_path.rstrip("/").split("/")
    # parts[0] is '' for absolute paths starting with /
    to_create = []
    for i in range(2, len(parts) + 1):
        to_create.append("/".join(parts[:i]))
    for path in to_create:
        if not path:
            continue
        try:
            sftp.stat(path)
        except IOError:
            try:
                sftp.mkdir(path)
            except IOError:
                pass  # already exists or parent missing — try anyway


def upload_all(client):
    sftp = client.open_sftp()
    uploaded = 0
    skipped = 0
    for local_rel, remote_rel in TREE.items():
        local_path = os.path.join(LOCAL, local_rel.replace("/", os.sep))
        remote_path = f"{REMOTE}/{remote_rel}"

        if not os.path.exists(local_path):
            print(f"  SKIP (missing): {local_rel}")
            skipped += 1
            continue

        remote_dir = remote_path.rsplit("/", 1)[0]
        mkdirs_sftp(sftp, remote_dir)

        sftp.put(local_path, remote_path)

        # Make shell scripts executable
        if local_rel.endswith(".sh"):
            sftp.chmod(remote_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

        print(f"  ↑ {local_rel}")
        uploaded += 1

    sftp.close()
    print(f"\n  {uploaded} files uploaded, {skipped} skipped.")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"  JTL Network Automation — Full Docker Deployment")
    print(f"  Target: {USERNAME}@{SERVER}:{REMOTE}")
    print(f"{'='*60}\n")

    print("Connecting to server...")
    client = connect()
    print("Connected.\n")

    # ── 1. Create base directory ─────────────────────────────────────────
    print("=== 1/6  Preparing directory structure ===")
    dirs = " ".join([
        f"{REMOTE}/olt-provisioning-api/app/api/v1",
        f"{REMOTE}/olt-provisioning-api/app/api/bss",
        f"{REMOTE}/olt-provisioning-api/app/models",
        f"{REMOTE}/olt-provisioning-api/app/schemas",
        f"{REMOTE}/olt-provisioning-api/app/services",
        f"{REMOTE}/olt-provisioning-api/app/olt_driver",
        f"{REMOTE}/olt-provisioning-api/app/utils",
        f"{REMOTE}/olt-provisioning-api/app/notifications",
        f"{REMOTE}/olt-provisioning-api/app/db",
        f"{REMOTE}/olt-provisioning-api/alembic/versions",
        f"{REMOTE}/olt-provisioning-api/docs",
        f"{REMOTE}/m6k-p2p-api/app",
    ])
    run(client, f"mkdir -p {dirs}")
    run(client, f"chown -R {USERNAME}:{USERNAME} {REMOTE}")

    # ── 2. Upload all files ──────────────────────────────────────────────
    print("\n=== 2/6  Uploading files ===")
    upload_all(client)

    # ── 3. Add user to docker group (if not already) ─────────────────────
    print("\n=== 3/6  Docker group membership ===")
    sudo(client, f"usermod -aG docker {USERNAME}", quiet=True)

    # ── 4. Build & start containers ──────────────────────────────────────
    print("\n=== 4/6  Building Docker images (this takes 3–5 min) ===")
    rc, _ = run(
        client,
        f"cd {REMOTE} && docker compose build --no-cache 2>&1 | tail -20",
        timeout=600,
    )
    if rc != 0:
        print("\n  Build FAILED. Showing full logs:")
        run(client, f"cd {REMOTE} && docker compose build 2>&1 | tail -40", timeout=600)
        client.close()
        return

    print("\n=== 5/6  Starting containers ===")
    run(client, f"cd {REMOTE} && docker compose up -d", timeout=120)

    # ── 5. Wait for all services healthy ────────────────────────────────
    print("\n=== 6/6  Waiting for services to be ready ===")
    services = [
        ("OLT API",  8000, "/health"),
        ("M6K API",  8001, "/health"),
    ]
    for name, port, path in services:
        print(f"\n  Checking {name} (port {port})...")
        for attempt in range(20):
            time.sleep(6)
            rc, out = run(
                client,
                f"curl -sf http://localhost:{port}{path}",
                quiet=True,
            )
            if rc == 0 and out:
                print(f"  {name} LIVE: {out}")
                break
            print(f"    attempt {attempt+1}/20...")
        else:
            print(f"  {name} did not start — showing logs:")
            svc = "olt-api" if port == 8000 else "m6k-api"
            run(client, f"cd {REMOTE} && docker compose logs --tail=40 {svc}")

    # ── 6. Smoke tests ───────────────────────────────────────────────────
    print("\n=== Smoke Tests ===")

    print("\n  OLT API — list OLTs:")
    run(client, "curl -s http://localhost:8000/api/v1/olts "
                "-H 'X-API-Key: bss-prod-key-change-me'")

    print("\n  OLT API — BSS routes present:")
    run(client, "curl -s http://localhost:8000/openapi.json | "
                "python3 -c \"import json,sys; p=json.load(sys.stdin)['paths']; "
                "bss=[k for k in p if '/provision' in k or '/onu/' in k]; "
                "print('BSS routes:', bss)\"")

    print("\n  M6K API — circuit list:")
    run(client, "curl -s http://localhost:8001/circuits "
                "-H 'X-Api-Key: JTL-BSS-2026-M6KPROV'")

    # ── 7. Seed test OLT ─────────────────────────────────────────────────
    print("\n=== Seeding Test OLT ===")
    seed_cmd = (
        "curl -s -X POST http://localhost:8000/api/v1/olts "
        "-H 'X-API-Key: bss-prod-key-change-me' "
        "-H 'Content-Type: application/json' "
        "-d '{\"name\":\"OLT-C300-TESTAUTOPROV\","
        "\"host\":\"192.168.248.10\","
        "\"ssh_port\":22,"
        "\"model\":\"C300\","
        "\"platform\":\"ZXAN\","
        "\"username\":\"alex\","
        "\"password\":\"alex321\","
        "\"enable_password\":\"zxr10\","
        "\"location\":\"Test Lab\","
        "\"status\":\"active\"}'"
    )
    run(client, seed_cmd)

    # ── 8. Print summary ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  DEPLOYMENT COMPLETE")
    print(f"")
    print(f"  OLT Provisioning API:  http://{SERVER}:8000")
    print(f"  M6K P2P Circuit API:   http://{SERVER}:8001")
    print(f"  BSS Portal:            http://{SERVER}:8000/portal")
    print(f"  API Docs (OLT):        http://{SERVER}:8000/docs")
    print(f"  API Docs (M6K):        http://{SERVER}:8001/docs")
    print(f"  Tech Docs:             http://{SERVER}:8000/static/api-documentation.html")
    print(f"  Exec Summary:          http://{SERVER}:8000/static/executive-summary.html")
    print(f"")
    print(f"  API Key (OLT):  bss-prod-key-change-me")
    print(f"  API Key (M6K):  JTL-BSS-2026-M6KPROV")
    print(f"")
    print(f"  To provision a test customer:")
    print(f"  curl -X POST http://{SERVER}:8000/provision \\")
    print(f"    -H 'X-API-Key: bss-prod-key-change-me' \\")
    print(f"    -H 'Content-Type: application/json' \\")
    print(f"    -d '{{\"customer_id\":\"TEST-0001\",\"customer_name\":\"Test Customer\",")
    print(f"          \"onu_serial_number\":\"ZTEGD1397E71\",\"onu_model\":\"ZTEG-F660\",")
    print(f"          \"olt_id\":\"OLT-C300-TESTAUTOPROV\",\"package_id\":\"GPON-5M\",")
    print(f"          \"service_vlan\":200}}'")
    print(f"{'='*60}\n")

    client.close()


if __name__ == "__main__":
    main()
