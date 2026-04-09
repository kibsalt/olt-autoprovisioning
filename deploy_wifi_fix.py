"""Upload WiFi SSID naming fix and restart."""
import os, paramiko

SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
REMOTE = "/home/jtlacs/olt-provisioning-api"
LOCAL = os.path.dirname(os.path.abspath(__file__))

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)

sftp = client.open_sftp()
for f in ["app/utils/wifi.py", "app/schemas/onu.py", "app/services/onu_service.py"]:
    local = os.path.join(LOCAL, f)
    remote = f"{REMOTE}/{f}"
    print(f"Uploading {remote}")
    sftp.put(local, remote)
sftp.close()

print("Restarting service...")
stdin, stdout, stderr = client.exec_command(
    f"echo '{PASSWORD}' | sudo -S bash -c 'systemctl restart olt-api'", timeout=30
)
stdout.channel.recv_exit_status()

import time; time.sleep(5)
stdin, stdout, stderr = client.exec_command("curl -sf http://localhost:8000/health", timeout=10)
print(f"Health: {stdout.read().decode().strip()}")
client.close()
print("Done!")
