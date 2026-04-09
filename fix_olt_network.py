"""
Push updated docker-compose.yml to server and restart olt-api with network_mode: host
so it can reach OLT management IPs on 192.168.248.x
"""
import os, time, paramiko

SERVER   = "192.168.14.4"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE   = "/home/jtlacs/jtl-automation"
LOCAL    = os.path.dirname(os.path.abspath(__file__))

def ssh_cmd(client, cmd, timeout=60):
    print(f"  $ {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out.strip(): print(out.strip())
    if err.strip(): print(f"[stderr] {err.strip()}")
    return out, err

def sudo_cmd(client, cmd, timeout=120):
    return ssh_cmd(client, f'echo "{PASSWORD}" | sudo -S {cmd}', timeout=timeout)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
print(f"Connected to {SERVER}")

# Upload updated docker-compose.yml
sftp = client.open_sftp()
local_file = os.path.join(LOCAL, "docker-compose.yml")
remote_file = f"{REMOTE}/docker-compose.yml"
print(f"\nUploading docker-compose.yml...")
sftp.put(local_file, remote_file)
sftp.close()
print("  Uploaded.")

# Force recreate olt-api only (m6k-api is fine as-is)
print("\nForce-recreating olt-api container with host networking...")
sudo_cmd(client,
    f"bash -c 'cd {REMOTE} && docker compose up -d --force-recreate olt-api'",
    timeout=180)

time.sleep(5)

# Check status
print("\nContainer status:")
sudo_cmd(client, "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'")

# Check OLT health
print("\nOLT health check:")
ssh_cmd(client,
    'curl -s http://localhost:8000/api/v1/olts/1/health -H "X-API-Key: bss-prod-key-change-me"')

client.close()
print("\nDone.")
