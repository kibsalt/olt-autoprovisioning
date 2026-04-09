"""Seed the production database with sample OLTs, VLANs, bandwidth profiles, and service profiles."""

import json
import paramiko

SERVER = "172.16.37.18"
USERNAME = "jtlacs"
PASSWORD = "bssadmin+ZTE"
API = "http://localhost:8000/api/v1"
KEY = "bss-prod-key-change-me"


def create_ssh_client():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USERNAME, password=PASSWORD, timeout=15)
    return client


def api_call(client, method, endpoint, data=None):
    url = f"{API}{endpoint}"
    cmd = f'curl -sf -X {method} "{url}" -H "X-API-Key: {KEY}" -H "Content-Type: application/json"'
    if data:
        json_data = json.dumps(data).replace('"', '\\"')
        cmd += f' -d "{json_data}"'
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    try:
        result = json.loads(out)
        return result
    except:
        return {"raw": out}


def main():
    print("Connecting to production server...")
    client = create_ssh_client()
    print("Connected!\n")

    # =============================================
    # SEED OLTs
    # =============================================
    print("=== Seeding OLTs ===")
    olts = [
        {"name": "OLT-C300-NAIROBI-01", "host": "10.10.1.1", "ssh_port": 22, "model": "C300", "location": "Nairobi POP - Site A", "ssh_username": "admin", "ssh_password": "admin@zte"},
        {"name": "OLT-C300-NAIROBI-02", "host": "10.10.1.2", "ssh_port": 22, "model": "C300", "location": "Nairobi POP - Site B", "ssh_username": "admin", "ssh_password": "admin@zte"},
        {"name": "OLT-C320-MOMBASA-01", "host": "10.10.2.1", "ssh_port": 22, "model": "C320", "location": "Mombasa POP", "ssh_username": "admin", "ssh_password": "admin@zte"},
        {"name": "OLT-C320-KISUMU-01", "host": "10.10.3.1", "ssh_port": 22, "model": "C320", "location": "Kisumu POP", "ssh_username": "admin", "ssh_password": "admin@zte"},
        {"name": "OLT-C600-WESTLANDS-01", "host": "10.10.4.1", "ssh_port": 22, "model": "C600", "location": "Westlands POP", "ssh_username": "admin", "ssh_password": "admin@zte"},
        {"name": "OLT-C600-UPPERHILL-01", "host": "10.10.4.2", "ssh_port": 22, "model": "C600", "location": "Upper Hill POP", "ssh_username": "admin", "ssh_password": "admin@zte"},
        {"name": "OLT-C620-KAREN-01", "host": "10.10.5.1", "ssh_port": 22, "model": "C620", "location": "Karen POP", "ssh_username": "admin", "ssh_password": "admin@zte"},
        {"name": "OLT-C620-KILIMANI-01", "host": "10.10.5.2", "ssh_port": 22, "model": "C620", "location": "Kilimani POP", "ssh_username": "admin", "ssh_password": "admin@zte"},
        {"name": "OLT-C650-THIKA-01", "host": "10.10.6.1", "ssh_port": 22, "model": "C650", "location": "Thika POP", "ssh_username": "admin", "ssh_password": "admin@zte"},
        {"name": "OLT-C650-NAKURU-01", "host": "10.10.6.2", "ssh_port": 22, "model": "C650", "location": "Nakuru POP", "ssh_username": "admin", "ssh_password": "admin@zte"},
    ]

    for olt in olts:
        result = api_call(client, "POST", "/olts", olt)
        if result.get("success"):
            d = result["data"]
            print(f"  Created: {d['name']} ({d['model']}/{d['platform']}) - ID {d['id']}")
        else:
            print(f"  Error creating {olt['name']}: {result}")

    # =============================================
    # SEED VLANs
    # =============================================
    print("\n=== Seeding VLANs ===")
    vlans = [
        {"vlan_tag": 100, "name": "INTERNET", "service_type": "internet", "description": "Internet service VLAN"},
        {"vlan_tag": 200, "name": "VOIP", "service_type": "voip", "description": "VoIP service VLAN"},
        {"vlan_tag": 300, "name": "IPTV", "service_type": "iptv", "description": "IPTV service VLAN"},
        {"vlan_tag": 999, "name": "MGMT", "service_type": "management", "description": "OLT management VLAN"},
    ]

    for vlan in vlans:
        result = api_call(client, "POST", "/vlans", vlan)
        if result.get("success"):
            d = result["data"]
            print(f"  Created: VLAN {d['vlan_tag']} - {d['name']} (ID {d['id']})")
        else:
            print(f"  Error creating VLAN {vlan['vlan_tag']}: {result}")

    # =============================================
    # SEED BANDWIDTH PROFILES
    # =============================================
    print("\n=== Seeding Bandwidth Profiles ===")
    bw_profiles = [
        {"name": "UP_5M", "traffic_table_index": 1, "cir": 5000, "pir": 5120, "dba_type": "type3", "direction": "upstream", "description": "5Mbps upstream"},
        {"name": "UP_10M", "traffic_table_index": 2, "cir": 10000, "pir": 10240, "dba_type": "type3", "direction": "upstream", "description": "10Mbps upstream"},
        {"name": "UP_20M", "traffic_table_index": 3, "cir": 20000, "pir": 20480, "dba_type": "type3", "direction": "upstream", "description": "20Mbps upstream"},
        {"name": "UP_50M", "traffic_table_index": 4, "cir": 50000, "pir": 51200, "dba_type": "type3", "direction": "upstream", "description": "50Mbps upstream"},
        {"name": "DOWN_10M", "traffic_table_index": 5, "cir": 10000, "pir": 10240, "dba_type": "type3", "direction": "downstream", "description": "10Mbps downstream"},
        {"name": "DOWN_20M", "traffic_table_index": 6, "cir": 20000, "pir": 20480, "dba_type": "type3", "direction": "downstream", "description": "20Mbps downstream"},
        {"name": "DOWN_50M", "traffic_table_index": 7, "cir": 50000, "pir": 51200, "dba_type": "type3", "direction": "downstream", "description": "50Mbps downstream"},
        {"name": "DOWN_100M", "traffic_table_index": 8, "cir": 100000, "pir": 102400, "dba_type": "type3", "direction": "downstream", "description": "100Mbps downstream"},
    ]

    for bw in bw_profiles:
        result = api_call(client, "POST", "/bandwidth-profiles", bw)
        if result.get("success"):
            d = result["data"]
            print(f"  Created: {d['name']} - {d['cir']}kbps CIR (ID {d['id']})")
        else:
            print(f"  Error creating {bw['name']}: {result}")

    # =============================================
    # SEED SERVICE PROFILES
    # =============================================
    print("\n=== Seeding Service Profiles ===")
    service_profiles = [
        {"name": "RESIDENTIAL_10M", "service_type": "internet", "upstream_profile_id": 1, "downstream_profile_id": 5, "vlan_id": 1, "gem_port": 1, "tcont_id": 1, "description": "Residential 10Mbps internet"},
        {"name": "RESIDENTIAL_20M", "service_type": "internet", "upstream_profile_id": 2, "downstream_profile_id": 6, "vlan_id": 1, "gem_port": 1, "tcont_id": 1, "description": "Residential 20Mbps internet"},
        {"name": "RESIDENTIAL_50M", "service_type": "internet", "upstream_profile_id": 3, "downstream_profile_id": 7, "vlan_id": 1, "gem_port": 1, "tcont_id": 1, "description": "Residential 50Mbps internet"},
        {"name": "BUSINESS_100M", "service_type": "internet", "upstream_profile_id": 4, "downstream_profile_id": 8, "vlan_id": 1, "gem_port": 1, "tcont_id": 1, "description": "Business 100Mbps internet"},
        {"name": "VOIP_SERVICE", "service_type": "voip", "vlan_id": 2, "gem_port": 2, "tcont_id": 2, "description": "VoIP service profile"},
        {"name": "IPTV_SERVICE", "service_type": "iptv", "vlan_id": 3, "gem_port": 3, "tcont_id": 3, "description": "IPTV service profile"},
    ]

    for sp in service_profiles:
        result = api_call(client, "POST", "/service-profiles", sp)
        if result.get("success"):
            d = result["data"]
            print(f"  Created: {d['name']} ({d['service_type']}) - ID {d['id']}")
        else:
            print(f"  Error creating {sp['name']}: {result}")

    # =============================================
    # VERIFY
    # =============================================
    print("\n=== Summary ===")
    for endpoint, label in [("/olts", "OLTs"), ("/vlans", "VLANs"), ("/bandwidth-profiles", "Bandwidth Profiles"), ("/service-profiles", "Service Profiles")]:
        result = api_call(client, "GET", endpoint)
        if result.get("success"):
            count = result.get("total", len(result.get("data", [])))
            print(f"  {label}: {count}")

    print("\nDone! Seed data created successfully.")
    client.close()


if __name__ == "__main__":
    main()
