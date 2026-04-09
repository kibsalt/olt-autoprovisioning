# JTL OLT Provisioning API — Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Server Setup & Deployment](#server-setup--deployment)
4. [Security Hardening](#security-hardening)
5. [Configuration](#configuration)
6. [API Authentication](#api-authentication)
7. [API Endpoints Reference](#api-endpoints-reference)
8. [Provisioning Workflow](#provisioning-workflow)
9. [OLT Driver Layer](#olt-driver-layer)
10. [Notifications (Email & SMS)](#notifications-email--sms)
11. [Database Schema](#database-schema)
12. [Troubleshooting](#troubleshooting)
13. [Maintenance](#maintenance)

---

## Overview

The JTL OLT Provisioning API is a REST API server that sits between JTL's BSS (Business Support System) and the ZTE OLT (Optical Line Terminal) fleet. It receives provisioning instructions from the BSS via REST and executes them on the OLTs via SSH.

**Supported OLT Models:**

| Model | Platform | Notes |
|-------|----------|-------|
| ZTE C300 | ZXAN | Legacy platform |
| ZTE C320 | ZXAN | Legacy platform |
| ZTE C600 | TITAN | Newer platform |
| ZTE C620 | TITAN | Newer platform |
| ZTE C650 | TITAN | Newer platform |

**Key Features:**
- Full ONU lifecycle management (add, configure, enable, disable, suspend, remove)
- Automatic WiFi SSID/password generation and ONU configuration (2.4GHz + 5GHz)
- TR-069 ACS configuration on every provisioned ONU
- Customer notification via email (SMTP) and SMS (Africa's Talking)
- Service profile management with bandwidth and VLAN control
- Full audit logging of all provisioning operations
- API key authentication

---

## Architecture

```
+--------+         +---------------------+         +-----------+
|  BSS   |  REST   | OLT Provisioning    |   SSH   | ZTE OLTs  |
| System | ------> | API Server          | ------> | C300/C320 |
|        |  JSON   | (172.16.37.18:8000) |  CLI    | C600/C620 |
+--------+         +---------------------+         | C650      |
                       |          |                 +-----------+
                       |          |
                   +---+---+  +--+---+
                   |MariaDB|  | SMTP |
                   | (local|  | + AT |
                   |  3306)|  | SMS  |
                   +-------+  +------+
```

**Technology Stack:**
- **Language:** Python 3.13
- **Framework:** FastAPI + Uvicorn (4 workers)
- **Database:** MariaDB 11.8 (local)
- **ORM:** SQLAlchemy 2.0 (async)
- **SSH:** asyncssh
- **SMS:** Africa's Talking API
- **Email:** aiosmtplib
- **Process Manager:** systemd

---

## Server Setup & Deployment

### Prerequisites

- Debian 13 (Trixie) or Ubuntu 22.04+
- Python 3.12+
- MariaDB 11.x running locally
- Network access to OLT management IPs via SSH (port 22)

### Step 1: Install System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip mariadb-server curl
```

### Step 2: Install Python Packages

```bash
sudo pip3 install --break-system-packages \
  fastapi uvicorn sqlalchemy aiomysql alembic asyncssh \
  pydantic-settings cryptography structlog africastalking \
  aiosmtplib jinja2 pymysql
```

If you encounter a `typing_extensions` conflict:
```bash
sudo pip3 install --break-system-packages --ignore-installed typing_extensions
# Then re-run the install command above
```

### Step 3: Create the Database

```sql
-- Connect as root
sudo mariadb -u root

CREATE DATABASE IF NOT EXISTS olt_provisioning
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'olt_api'@'localhost'
  IDENTIFIED BY 'JtlOltDb2024!';

CREATE USER IF NOT EXISTS 'olt_api'@'%'
  IDENTIFIED BY 'JtlOltDb2024!';

GRANT ALL PRIVILEGES ON olt_provisioning.*
  TO 'olt_api'@'localhost';

GRANT ALL PRIVILEGES ON olt_provisioning.*
  TO 'olt_api'@'%';

FLUSH PRIVILEGES;
```

### Step 4: Upload Application Files

Upload the project to `/home/jtlacs/olt-provisioning-api/` on the server. The directory structure:

```
olt-provisioning-api/
├── app/
│   ├── main.py              # FastAPI application
│   ├── config.py             # Configuration (reads .env)
│   ├── dependencies.py       # Auth & DI
│   ├── api/v1/               # REST endpoints
│   ├── models/               # SQLAlchemy models
│   ├── schemas/              # Pydantic schemas
│   ├── services/             # Business logic
│   ├── olt_driver/           # SSH drivers (ZXAN + TITAN)
│   ├── notifications/        # Email + SMS
│   ├── db/                   # Database session
│   └── utils/                # Crypto, WiFi generation
├── alembic/                  # Migrations
├── .env                      # Environment config (create this)
└── pyproject.toml
```

### Step 5: Create .env File

```bash
cd /home/jtlacs/olt-provisioning-api

# Generate a Fernet encryption key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Create `.env` with the generated key:

```ini
# API Authentication
OLT_API_KEYS=your-bss-api-key-here

# Database
OLT_DB_HOST=127.0.0.1
OLT_DB_PORT=3306
OLT_DB_USER=olt_api
OLT_DB_PASSWORD=JtlOltDb2024!
OLT_DB_NAME=olt_provisioning

# Credential Encryption (paste the generated Fernet key)
OLT_CREDENTIAL_ENCRYPTION_KEY=your-fernet-key-here

# ACS (TR-069) — configured on every ONU
OLT_ACS_URL=http://197.232.61.253:7547
OLT_ACS_USERNAME=ACS
OLT_ACS_PASSWORD=jtl@acs

# SSH Timeouts
OLT_SSH_CONNECT_TIMEOUT=10
OLT_SSH_COMMAND_TIMEOUT=30

# Email (SMTP)
OLT_SMTP_HOST=smtp.gmail.com
OLT_SMTP_PORT=587
OLT_SMTP_USERNAME=your-email@jtl.co.ke
OLT_SMTP_PASSWORD=your-app-password
OLT_SMTP_FROM_EMAIL=noreply@jtl.co.ke
OLT_SMTP_USE_TLS=true

# SMS (Africa's Talking)
OLT_AT_USERNAME=your-at-username
OLT_AT_API_KEY=your-at-api-key
OLT_AT_SENDER_ID=JTL

# WiFi
OLT_WIFI_SSID_PREFIX=JTL

# Server
OLT_SERVER_HOST=0.0.0.0
OLT_SERVER_PORT=8000
OLT_WORKERS=4
OLT_DEBUG=false
```

Secure the file:
```bash
chmod 600 .env
```

### Step 6: Create Database Tables

```bash
cd /home/jtlacs/olt-provisioning-api
python3 << 'EOF'
from sqlalchemy import create_engine
from app.config import settings
from app.models.base import Base
import app.models
engine = create_engine(settings.sync_database_url)
Base.metadata.create_all(engine)
print("Tables created successfully!")
engine.dispose()
EOF
```

### Step 7: Create systemd Service

```bash
sudo tee /etc/systemd/system/olt-api.service << 'EOF'
[Unit]
Description=JTL OLT Provisioning API
After=network.target mariadb.service

[Service]
Type=simple
User=jtlacs
WorkingDirectory=/home/jtlacs/olt-provisioning-api
EnvironmentFile=/home/jtlacs/olt-provisioning-api/.env
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable olt-api
sudo systemctl start olt-api
```

### Step 8: Verify

```bash
# Check service status
sudo systemctl status olt-api

# Health check
curl http://localhost:8000/health
# Expected: {"status":"ok"}

# Test with API key
curl -H "X-API-Key: your-bss-api-key-here" http://localhost:8000/api/v1/olts
# Expected: {"success":true,"data":[],"total":0,"page":1,"page_size":50,"request_id":""}

# Swagger UI (open in browser)
# http://172.16.37.18:8000/docs
```

---

## Security Hardening

### UFW Firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 8000/tcp  # API
sudo ufw allow 443/tcp   # HTTPS (for future reverse proxy)
sudo ufw allow 80/tcp    # HTTP
sudo ufw --force enable
sudo ufw status verbose
```

### fail2ban (SSH Brute Force Protection)

```bash
sudo apt-get install -y fail2ban

sudo tee /etc/fail2ban/jail.local << 'EOF'
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 3600
findtime = 600
EOF

sudo systemctl enable fail2ban
sudo systemctl restart fail2ban
```

### SSH Hardening

Edit `/etc/ssh/sshd_config`:

```
PermitRootLogin no
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
```

Then reload:
```bash
sudo systemctl reload ssh
```

### Kernel Hardening (sysctl)

```bash
sudo tee /etc/sysctl.d/99-hardening.conf << 'EOF'
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.conf.all.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 2048
net.ipv4.tcp_synack_retries = 2
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
EOF

sudo sysctl --system
```

### Automatic Security Updates

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
```

---

## Configuration

All configuration is via environment variables (`.env` file), prefixed with `OLT_`.

| Variable | Description | Default |
|----------|-------------|---------|
| `OLT_API_KEYS` | Comma-separated API keys for BSS auth | (required) |
| `OLT_DB_HOST` | MariaDB host | `127.0.0.1` |
| `OLT_DB_PORT` | MariaDB port | `3306` |
| `OLT_DB_USER` | MariaDB username | `olt_api` |
| `OLT_DB_PASSWORD` | MariaDB password | (required) |
| `OLT_DB_NAME` | Database name | `olt_provisioning` |
| `OLT_CREDENTIAL_ENCRYPTION_KEY` | Fernet key for encrypting OLT SSH creds | (required) |
| `OLT_ACS_URL` | TR-069 ACS URL | `http://197.232.61.253:7547` |
| `OLT_ACS_USERNAME` | ACS username | `ACS` |
| `OLT_ACS_PASSWORD` | ACS password | `jtl@acs` |
| `OLT_SSH_CONNECT_TIMEOUT` | SSH connection timeout (seconds) | `10` |
| `OLT_SSH_COMMAND_TIMEOUT` | SSH command timeout (seconds) | `30` |
| `OLT_SMTP_HOST` | SMTP server | `localhost` |
| `OLT_SMTP_PORT` | SMTP port | `587` |
| `OLT_SMTP_USERNAME` | SMTP username | (empty) |
| `OLT_SMTP_PASSWORD` | SMTP password | (empty) |
| `OLT_SMTP_FROM_EMAIL` | From email address | `noreply@jtl.co.ke` |
| `OLT_AT_USERNAME` | Africa's Talking username | (empty) |
| `OLT_AT_API_KEY` | Africa's Talking API key | (empty) |
| `OLT_AT_SENDER_ID` | SMS sender ID | `JTL` |
| `OLT_WIFI_SSID_PREFIX` | WiFi SSID prefix | `JTL` |

---

## API Authentication

All `/api/v1/*` endpoints require an API key in the `X-API-Key` header.

```bash
curl -H "X-API-Key: your-api-key" http://172.16.37.18:8000/api/v1/olts
```

Unauthenticated requests return:
```json
{"detail": "Not authenticated"}
```

Invalid keys return:
```json
{"detail": "Invalid API key"}
```

Multiple API keys can be configured as comma-separated values:
```
OLT_API_KEYS=bss-key-1,bss-key-2,monitoring-key
```

---

## API Endpoints Reference

Base URL: `http://172.16.37.18:8000/api/v1`

Interactive docs: `http://172.16.37.18:8000/docs`

### OLT Management

#### Register a New OLT

```http
POST /api/v1/olts
```

```json
{
  "name": "OLT-NAIROBI-01",
  "host": "10.10.1.1",
  "ssh_port": 22,
  "model": "C600",
  "software_version": "V6.0.10P3",
  "location": "Nairobi POP",
  "ssh_username": "admin",
  "ssh_password": "zte@admin"
}
```

**Response (201):**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "name": "OLT-NAIROBI-01",
    "host": "10.10.1.1",
    "ssh_port": 22,
    "model": "C600",
    "platform": "TITAN",
    "software_version": "V6.0.10P3",
    "location": "Nairobi POP",
    "status": "active",
    "created_at": "2026-03-31T10:00:00",
    "updated_at": null
  }
}
```

> Note: SSH credentials are encrypted at rest using the Fernet key. The platform (ZXAN/TITAN) is automatically determined from the model.

#### List OLTs

```http
GET /api/v1/olts?page=1&page_size=50&status=active&model=C600
```

#### Get OLT Details

```http
GET /api/v1/olts/{olt_id}
```

#### Update OLT

```http
PUT /api/v1/olts/{olt_id}
```

```json
{
  "location": "Nairobi POP - Rack 3",
  "status": "maintenance"
}
```

#### Delete (Decommission) OLT

```http
DELETE /api/v1/olts/{olt_id}
```

Sets status to `decommissioned` (soft delete).

#### Check OLT Health

```http
GET /api/v1/olts/{olt_id}/health
```

Tests SSH connectivity and returns reachability status.

---

### ONU Provisioning

#### Discover Unregistered ONUs

```http
GET /api/v1/olts/{olt_id}/onus/unregistered?frame=1&slot=1&port=1
```

Queries the OLT via SSH for unregistered ONUs on the specified GPON port.

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "serial_number": "ZTEGC8FA0001",
      "frame": 1,
      "slot": 1,
      "port": 1,
      "onu_type": null
    }
  ]
}
```

#### Provision a New ONU

This is the primary endpoint. It performs the full provisioning workflow:

```http
POST /api/v1/olts/{olt_id}/onus
```

```json
{
  "serial_number": "ZTEGC8FA0001",
  "customer_id": "CUST-10042",
  "frame": 1,
  "slot": 1,
  "port": 1,
  "onu_type": "ZXHN_F680",
  "description": "John Doe - Residential",
  "service_profile_ids": [1, 2],
  "customer_email": "john.doe@gmail.com",
  "customer_phone": "+254712345678"
}
```

**What happens during provisioning:**

1. Finds the next available ONU ID on the GPON port
2. Authorizes the ONU on the OLT via SSH
3. Configures TR-069 ACS (URL: `http://197.232.61.253:7547`, user: `ACS`)
4. Generates WiFi credentials (e.g., SSID: `JTL_CUST10042`, `JTL_CUST10042_5G`)
5. Configures WiFi on the ONU (2.4GHz + 5GHz, WPA2-PSK)
6. Applies service profiles (T-CONT, GEM port, service port, VLAN)
7. Saves everything to the database
8. Sends WiFi credentials to customer via email and SMS

**Response (201):**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "olt_id": 1,
    "serial_number": "ZTEGC8FA0001",
    "customer_id": "CUST-10042",
    "frame": 1,
    "slot": 1,
    "port": 1,
    "onu_id": 1,
    "onu_type": "ZXHN_F680",
    "description": "John Doe - Residential",
    "admin_state": "enabled",
    "oper_state": "unknown",
    "wifi_ssid_2g": "JTL_CUST10042",
    "wifi_ssid_5g": "JTL_CUST10042_5G",
    "wifi_password": "aB3xYz9kLm2p",
    "customer_email": "john.doe@gmail.com",
    "customer_phone": "+254712345678",
    "created_at": "2026-03-31T10:05:00",
    "updated_at": null
  }
}
```

#### List ONUs on an OLT

```http
GET /api/v1/olts/{olt_id}/onus?page=1&page_size=50
```

#### Find ONU by Customer ID

```http
GET /api/v1/onus?customer_id=CUST-10042
```

#### Get ONU Details

```http
GET /api/v1/olts/{olt_id}/onus/{onu_id}
```

#### Update ONU

```http
PUT /api/v1/olts/{olt_id}/onus/{onu_id}
```

```json
{
  "description": "John Doe - Upgraded to Business",
  "customer_email": "john.doe@business.co.ke"
}
```

#### Remove ONU

```http
DELETE /api/v1/olts/{olt_id}/onus/{onu_id}
```

This:
1. Deletes all service ports on the OLT
2. De-authorizes the ONU
3. Removes the database record

---

### Service Profile Management

#### Create a Service Profile

```http
POST /api/v1/service-profiles
```

```json
{
  "name": "RESIDENTIAL_50M",
  "service_type": "internet",
  "upstream_profile_id": 1,
  "downstream_profile_id": 2,
  "vlan_id": 1,
  "gem_port": 1,
  "tcont_id": 1,
  "description": "50Mbps residential internet"
}
```

#### List Service Profiles

```http
GET /api/v1/service-profiles
```

#### Apply Service to an ONU

```http
POST /api/v1/olts/{olt_id}/onus/{onu_id}/services
```

```json
{
  "service_profile_id": 1,
  "vlan_id": null
}
```

#### Remove Service from ONU

```http
DELETE /api/v1/olts/{olt_id}/onus/{onu_id}/services/{service_id}
```

---

### VLAN Management

#### Create VLAN

```http
POST /api/v1/vlans
```

```json
{
  "vlan_tag": 100,
  "name": "INTERNET_VLAN",
  "service_type": "internet",
  "description": "Internet service VLAN"
}
```

#### List VLANs

```http
GET /api/v1/vlans
```

#### Update / Delete VLAN

```http
PUT /api/v1/vlans/{vlan_id}
DELETE /api/v1/vlans/{vlan_id}
```

---

### Bandwidth Profile Management

#### Create Bandwidth Profile

```http
POST /api/v1/bandwidth-profiles
```

```json
{
  "name": "50M_DOWNSTREAM",
  "traffic_table_index": 10,
  "cir": 50000,
  "pir": 51200,
  "cbs": 0,
  "pbs": 0,
  "dba_type": "type3",
  "direction": "downstream",
  "description": "50Mbps downstream profile"
}
```

`cir` and `pir` are in **kbps**. For example:
- 10 Mbps = `10000` kbps
- 50 Mbps = `50000` kbps
- 100 Mbps = `100000` kbps

#### List / Update / Delete

```http
GET /api/v1/bandwidth-profiles
PUT /api/v1/bandwidth-profiles/{id}
DELETE /api/v1/bandwidth-profiles/{id}
```

---

### Operations (Enable / Disable / Suspend)

#### Enable ONU

```http
POST /api/v1/olts/{olt_id}/onus/{onu_id}/enable
```

#### Disable ONU

```http
POST /api/v1/olts/{olt_id}/onus/{onu_id}/disable
```

#### Suspend ONU

```http
POST /api/v1/olts/{olt_id}/onus/{onu_id}/suspend
```

Suspend keeps the ONU registered but marks all services as suspended.

#### Get Live ONU Status

```http
GET /api/v1/olts/{olt_id}/onus/{onu_id}/status
```

Queries the OLT in real-time via SSH and returns:
```json
{
  "success": true,
  "data": {
    "onu_id": 1,
    "serial_number": "ZTEGC8FA0001",
    "admin_state": "enable",
    "oper_state": "working",
    "rx_power": "-18.5",
    "tx_power": "2.3",
    "distance": "1250",
    "last_down_cause": "dying-gasp"
  }
}
```

---

## Provisioning Workflow

### Complete Example: Provision a New Customer

```bash
API="http://172.16.37.18:8000/api/v1"
KEY="X-API-Key: bss-prod-key-change-me"

# 1. Register the OLT (one-time)
curl -X POST "$API/olts" -H "$KEY" -H "Content-Type: application/json" -d '{
  "name": "OLT-WESTLANDS-01",
  "host": "10.10.1.1",
  "ssh_port": 22,
  "model": "C600",
  "ssh_username": "admin",
  "ssh_password": "zte_password"
}'

# 2. Create VLANs (one-time)
curl -X POST "$API/vlans" -H "$KEY" -H "Content-Type: application/json" -d '{
  "vlan_tag": 100,
  "name": "INTERNET",
  "service_type": "internet"
}'

# 3. Create bandwidth profiles (one-time)
curl -X POST "$API/bandwidth-profiles" -H "$KEY" -H "Content-Type: application/json" -d '{
  "name": "UP_10M",
  "cir": 10000, "pir": 10240,
  "dba_type": "type3",
  "direction": "upstream"
}'

curl -X POST "$API/bandwidth-profiles" -H "$KEY" -H "Content-Type: application/json" -d '{
  "name": "DOWN_50M",
  "cir": 50000, "pir": 51200,
  "dba_type": "type3",
  "direction": "downstream"
}'

# 4. Create a service profile (one-time)
curl -X POST "$API/service-profiles" -H "$KEY" -H "Content-Type: application/json" -d '{
  "name": "RESIDENTIAL_50M",
  "service_type": "internet",
  "upstream_profile_id": 1,
  "downstream_profile_id": 2,
  "vlan_id": 1,
  "gem_port": 1,
  "tcont_id": 1
}'

# 5. Discover unregistered ONUs
curl "$API/olts/1/onus/unregistered?frame=1&slot=1&port=1" -H "$KEY"

# 6. Provision the customer ONU
curl -X POST "$API/olts/1/onus" -H "$KEY" -H "Content-Type: application/json" -d '{
  "serial_number": "ZTEGC8FA0001",
  "customer_id": "CUST-10042",
  "frame": 1,
  "slot": 1,
  "port": 1,
  "onu_type": "ZXHN_F680",
  "description": "John Doe - Westlands",
  "service_profile_ids": [1],
  "customer_email": "john@example.com",
  "customer_phone": "+254712345678"
}'
# This automatically:
#   - Authorizes ONU on OLT
#   - Configures ACS (TR-069)
#   - Generates & configures WiFi
#   - Creates service port with VLAN
#   - Sends WiFi credentials via email + SMS

# 7. Check ONU status
curl "$API/olts/1/onus/1/status" -H "$KEY"

# 8. Suspend customer (e.g. non-payment)
curl -X POST "$API/olts/1/onus/1/suspend" -H "$KEY"

# 9. Re-enable customer
curl -X POST "$API/olts/1/onus/1/enable" -H "$KEY"

# 10. Remove customer
curl -X DELETE "$API/olts/1/onus/1" -H "$KEY"
```

---

## OLT Driver Layer

The API uses platform-specific drivers to handle CLI syntax differences between ZXAN and TITAN platforms.

### ZXAN Platform (C300, C320)

Interface naming: `gpon-olt_1/2/3` and `gpon-onu_1/2/3:1`

Key commands:
```
configure terminal
interface gpon-olt_1/1/1
  onu 1 type ZXHN_F680 sn ZTEGC8FA0001
  onu 1 description "Customer Name"
exit

interface gpon-onu_1/1/1:1
  tcont 1 profile 1
  gemport 1 tcont 1
  wifi ssid 1 name JTL_CUST001
  wifi ssid 1 auth-mode wpa2-psk
  wifi ssid 1 wpa-key MyPassword123
  wifi ssid 1 enable true
exit

service-port 10001 vport-mode gpon-onu_1/1/1:1 vlan 100 user-vlan 100 gemport 1
```

### TITAN Platform (C600, C620, C650)

Interface naming: `gpon_olt-1/2/3` and `gpon_onu-1/2/3:1` (note underscore vs hyphen)

Key commands:
```
configure terminal
interface gpon_olt-1/1/1
  onu 1 type ZXHN_F680 sn ZTEGC8FA0001
exit

interface gpon_onu-1/1/1:1
  tcont 1 profile 1
  gemport 1 tcont 1
exit

service-port 10001 gpon 1/1/1 onu 1 gemport 1 match vlan 100 action vlan 100
```

### SSH Connection Pool

The API maintains a connection pool — one SSH connection per OLT. Connections are lazy-initialized on first use and reused for subsequent commands. If a connection drops, it's automatically reconnected on the next request.

---

## Notifications (Email & SMS)

### Email

WiFi credentials are sent via SMTP after successful provisioning. Configure these `.env` variables:

```ini
OLT_SMTP_HOST=smtp.gmail.com
OLT_SMTP_PORT=587
OLT_SMTP_USERNAME=notifications@jtl.co.ke
OLT_SMTP_PASSWORD=your-app-password
OLT_SMTP_FROM_EMAIL=noreply@jtl.co.ke
OLT_SMTP_USE_TLS=true
```

### SMS (Africa's Talking)

Sign up at https://africastalking.com and get API credentials.

```ini
OLT_AT_USERNAME=your-username
OLT_AT_API_KEY=your-api-key
OLT_AT_SENDER_ID=JTL
```

### WiFi Credential Generation

WiFi credentials are auto-generated:
- **SSID (2.4GHz):** `JTL_{customer_id}` (e.g., `JTL_CUST10042`)
- **SSID (5GHz):** `JTL_{customer_id}_5G` (e.g., `JTL_CUST10042_5G`)
- **Password:** 12-character random alphanumeric string

Both the email and SMS include the SSID and password for both bands.

---

## Database Schema

### Tables

| Table | Description |
|-------|-------------|
| `olts` | OLT inventory (name, host, model, encrypted SSH creds, status) |
| `onus` | Provisioned ONUs (serial, customer_id, location, WiFi creds, state) |
| `service_profiles` | Named profiles (bandwidth, VLAN, GEM port, T-CONT) |
| `onu_services` | Which profiles are applied to which ONUs |
| `vlans` | VLAN registry (tag, name, service type) |
| `bandwidth_profiles` | Traffic tables (CIR, PIR, DBA type, direction) |
| `audit_logs` | Full audit trail of all API actions |
| `notifications` | Email/SMS delivery log |

### Verify Tables

```bash
sudo mariadb -u root -e "USE olt_provisioning; SHOW TABLES;"
```

---

## Troubleshooting

### Service won't start

```bash
# Check status
sudo systemctl status olt-api

# Check logs
sudo journalctl -u olt-api -n 50 --no-pager

# Common issues:
# - "No module named uvicorn" → pip packages not installed
# - "error parsing value for field api_keys" → .env format issue
# - "Can't connect to MySQL" → MariaDB not running or wrong credentials
```

### OLT SSH connection fails

```bash
# Test SSH manually
ssh admin@10.10.1.1

# Check from the server
curl http://localhost:8000/api/v1/olts/1/health -H "X-API-Key: your-key"

# Common issues:
# - Firewall blocking port 22 between API server and OLT
# - Wrong SSH credentials (they're encrypted - re-register the OLT)
# - OLT management interface down
```

### Database connection issues

```bash
# Test MariaDB
python3 -c "import pymysql; c=pymysql.connect(host='127.0.0.1',user='olt_api',password='JtlOltDb2024!',database='olt_provisioning'); print('OK'); c.close()"

# Check MariaDB is running
sudo systemctl status mariadb
```

### API returns 401

Ensure the `X-API-Key` header matches one of the keys in `OLT_API_KEYS` in `.env`.

### Email/SMS not sending

- Email: Check SMTP credentials and that the server can reach the SMTP host
- SMS: Verify Africa's Talking credentials and sender ID
- Check notification logs: `SELECT * FROM notifications ORDER BY created_at DESC LIMIT 10;`

---

## Maintenance

### Restart the API

```bash
sudo systemctl restart olt-api
```

### View logs

```bash
# Live logs
sudo journalctl -u olt-api -f

# Last 100 lines
sudo journalctl -u olt-api -n 100 --no-pager
```

### Update code

```bash
# Upload new files to /home/jtlacs/olt-provisioning-api/
# Then restart:
sudo systemctl restart olt-api
```

### Database backup

```bash
sudo mysqldump -u root olt_provisioning > /home/jtlacs/backup/olt_$(date +%Y%m%d).sql
```

### Check firewall status

```bash
sudo ufw status numbered
```

### Check fail2ban status

```bash
sudo systemctl status fail2ban
sudo fail2ban-client status sshd
```

### Generate a new API key

Add it to the `OLT_API_KEYS` variable in `.env` (comma-separated):
```
OLT_API_KEYS=existing-key,new-bss-key
```
Then restart: `sudo systemctl restart olt-api`

### Generate a new Fernet encryption key

> Warning: Changing this will make existing encrypted OLT credentials unreadable. You will need to re-register all OLTs.

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
