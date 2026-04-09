"""
Upload ssh_client.py fix and rebuild olt-api container.
"""
import os, time, paramiko

SERVER   = "192.168.14.4"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE   = "/home/jtlacs/jtl-automation"
LOCAL    = os.path.dirname(os.path.abspath(__file__))

def ssh_cmd(client, cmd, timeout=120):
    print(f"  $ {cmd[:120]}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out.strip(): print(out.strip())
    if err.strip(): print(f"[stderr] {err.strip()[:300]}")
    return out, err

def sudo_cmd(client, cmd, timeout=300):
    return ssh_cmd(client, f'echo "{PASSWORD}" | sudo -S {cmd}', timeout=timeout)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
print(f"Connected to {SERVER}")

sftp = client.open_sftp()

files_to_upload = [
    ("olt-provisioning-api/app/olt_driver/ssh_client.py",
     "olt-provisioning-api/app/olt_driver/ssh_client.py"),
]

for local_rel, remote_rel in files_to_upload:
    local_path = os.path.join(LOCAL, local_rel)
    remote_path = f"{REMOTE}/{remote_rel}"
    print(f"\nUploading {local_rel}...")
    sftp.put(local_path, remote_path)
    print("  Uploaded.")

sftp.close()

# Rebuild and recreate olt-api
print("\nRebuilding olt-api image (no-cache for app layer)...")
sudo_cmd(client,
    f"bash -c 'cd {REMOTE} && docker compose build olt-api'",
    timeout=300)

print("\nForce-recreating olt-api container...")
sudo_cmd(client,
    f"bash -c 'cd {REMOTE} && docker compose up -d --force-recreate olt-api'",
    timeout=60)

time.sleep(6)

print("\nContainer status:")
sudo_cmd(client, "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'")

print("\nOLT health check:")
ssh_cmd(client,
    'curl -s http://localhost:8000/api/v1/olts/1/health -H "X-API-Key: bss-prod-key-change-me"')

client.close()
print("\nDone.")
