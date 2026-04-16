#!/usr/bin/env python3
"""Seed users, technicians, and fixed_pppoe_cust records.

Idempotent — safely skips records that already exist.

Usage:
    python scripts/seed_users.py
"""
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import settings
from app.services.auth_service import hash_password

engine = create_engine(settings.sync_database_url, echo=False)

# ── Seed data ─────────────────────────────────────────────────────────────────

admins = [
    {"username": "admin",       "email": "admin@jtl.co.ke",  "password": "JTLAdmin2026!"},
    {"username": "ops_manager", "email": "ops@jtl.co.ke",    "password": "OpsManager2026!"},
    {"username": "noc_admin",   "email": "noc@jtl.co.ke",    "password": "NOCAdmin2026!"},
]

technicians = [
    # existing — match by name
    {"username": "alex",  "email": "alex@jtl.co.ke",  "password": "Alex@JTL2026!",  "tech_name": "Alex"},
    {"username": "john",  "email": "john@jtl.co.ke",  "password": "John@JTL2026!",  "tech_name": "John"},
    # new
    {"username": "brian", "email": "brian@jtl.co.ke", "password": "Brian@JTL2026!", "tech_name": "Brian Omondi",   "phone": "+254700000003", "zone": "Nairobi"},
    {"username": "kevin", "email": "kevin@jtl.co.ke", "password": "Kevin@JTL2026!", "tech_name": "Kevin Maina",    "phone": "+254700000004", "zone": "Mombasa"},
    {"username": "diana", "email": "diana@jtl.co.ke", "password": "Diana@JTL2026!", "tech_name": "Diana Wanjiku", "phone": "+254700000005", "zone": "Kisumu"},
]

customers = [
    {
        "customer_id":    "JTL-00001",
        "full_name":      "John Kamau",
        "service_id":     "100001",
        "package":        "GPON-10M",
        "pppoe_username": "Engineering_test_2",
        "pppoe_password": "Engineering_test_2",
        "vlan_id":        2918,
    },
    {
        "customer_id":    "JTL-00002",
        "full_name":      "Gilbert Rotich",
        "service_id":     "100002",
        "package":        "GPON-10M",
        "pppoe_username": "gilbert",
        "pppoe_password": "gilbert123",
        "vlan_id":        2918,
    },
    {
        "customer_id":    "JTL-00003",
        "full_name":      "Mike Kirui",
        "service_id":     "100003",
        "package":        "GPON-10M",
        "pppoe_username": "kplc",
        "pppoe_password": "kplc123",
        "vlan_id":        2918,
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_technician_id_by_name(session: Session, name: str) -> int | None:
    row = session.execute(
        text("SELECT id FROM technicians WHERE name = :name LIMIT 1"),
        {"name": name},
    ).fetchone()
    return row[0] if row else None


def create_technician_if_missing(
    session: Session, name: str, phone: str | None, zone: str | None, email: str | None
) -> int:
    tech_id = get_technician_id_by_name(session, name)
    if tech_id:
        return tech_id
    result = session.execute(
        text(
            "INSERT INTO technicians (name, phone, zone, email, active) "
            "VALUES (:name, :phone, :zone, :email, 1)"
        ),
        {"name": name, "phone": phone, "zone": zone, "email": email},
    )
    session.flush()
    return result.lastrowid


def user_exists(session: Session, username: str) -> bool:
    row = session.execute(
        text("SELECT id FROM users WHERE username = :username LIMIT 1"),
        {"username": username},
    ).fetchone()
    return row is not None


def insert_user(
    session: Session,
    username: str,
    email: str | None,
    hashed: str,
    role: str,
    technician_id: int | None,
) -> None:
    session.execute(
        text(
            "INSERT INTO users (username, email, hashed_password, role, technician_id, active) "
            "VALUES (:username, :email, :hashed, :role, :tech_id, 1)"
        ),
        {
            "username": username,
            "email": email,
            "hashed": hashed,
            "role": role,
            "tech_id": technician_id,
        },
    )


def customer_exists(session: Session, customer_id: str) -> bool:
    row = session.execute(
        text("SELECT id FROM fixed_pppoe_cust WHERE customer_id = :cid LIMIT 1"),
        {"cid": customer_id},
    ).fetchone()
    return row is not None


def insert_customer(session: Session, cust: dict) -> None:
    session.execute(
        text(
            "INSERT INTO fixed_pppoe_cust "
            "(customer_id, full_name, service_id, package, pppoe_username, pppoe_password, vlan_id) "
            "VALUES (:customer_id, :full_name, :service_id, :package, :pppoe_username, :pppoe_password, :vlan_id)"
        ),
        cust,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Seeding database...")
    with Session(engine) as session:
        # ── Admin users ──────────────────────────────────────────────────────
        print("\n[Admins]")
        for adm in admins:
            if user_exists(session, adm["username"]):
                print(f"  SKIP  admin user '{adm['username']}' (already exists)")
                continue
            hashed = hash_password(adm["password"])
            insert_user(session, adm["username"], adm["email"], hashed, "admin", None)
            print(f"  CREATE admin user '{adm['username']}'")

        # ── Technician users ─────────────────────────────────────────────────
        print("\n[Technicians]")
        for tech in technicians:
            username   = tech["username"]
            tech_name  = tech["tech_name"]
            tech_phone = tech.get("phone")
            tech_zone  = tech.get("zone")
            email      = tech["email"]
            password   = tech["password"]

            if user_exists(session, username):
                print(f"  SKIP  technician user '{username}' (already exists)")
                continue

            # Find or create the Technician record
            tech_id = create_technician_if_missing(session, tech_name, tech_phone, tech_zone, email)
            hashed = hash_password(password)
            insert_user(session, username, email, hashed, "technician", tech_id)
            print(f"  CREATE technician user '{username}' → technicians.id={tech_id} ({tech_name})")

        session.flush()

        # ── Customers ────────────────────────────────────────────────────────
        print("\n[Customers]")
        for cust in customers:
            if customer_exists(session, cust["customer_id"]):
                print(f"  SKIP  customer '{cust['customer_id']}' (already exists)")
                continue
            insert_customer(session, cust)
            print(f"  CREATE customer '{cust['customer_id']}' ({cust['full_name']})")

        session.commit()
        print("\nDone.")


if __name__ == "__main__":
    main()
