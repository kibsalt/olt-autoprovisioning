"""Add users, fixed_pppoe_cust tables; update tickets with acknowledged fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "technician", name="userrole"),
            nullable=False,
        ),
        sa.Column("technician_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_ticket_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("email"),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["technicians.id"],
            ondelete="SET NULL",
        ),
    )

    # 2. Create fixed_pppoe_cust table
    op.create_table(
        "fixed_pppoe_cust",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.String(100), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("service_id", sa.String(100), nullable=False),
        sa.Column("pppoe_username", sa.String(255), nullable=False),
        sa.Column("pppoe_password", sa.String(255), nullable=False),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_index("ix_fixed_pppoe_cust_customer_id", "fixed_pppoe_cust", ["customer_id"])

    # 3. Add acknowledge_notes and acknowledged_at to tickets
    op.add_column("tickets", sa.Column("acknowledge_notes", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("acknowledged_at", sa.DateTime(), nullable=True))

    # 4. Add ACKNOWLEDGED to tickets.status enum
    # MariaDB: modify the enum to include the new value
    op.execute(
        "ALTER TABLE tickets MODIFY COLUMN status "
        "ENUM('open','assigned','in_progress','acknowledged','resolved','closed') "
        "NOT NULL DEFAULT 'open'"
    )

    # 5. Add last_ticket_at to users (already in CREATE TABLE above, included for clarity)
    # Nothing extra needed here.


def downgrade() -> None:
    # Remove acknowledge fields from tickets
    op.drop_column("tickets", "acknowledged_at")
    op.drop_column("tickets", "acknowledge_notes")

    # Revert tickets.status enum (remove 'acknowledged')
    # Only safe if no rows have status='acknowledged'
    op.execute(
        "ALTER TABLE tickets MODIFY COLUMN status "
        "ENUM('open','assigned','in_progress','resolved','closed') "
        "NOT NULL DEFAULT 'open'"
    )

    # Drop tables
    op.drop_index("ix_fixed_pppoe_cust_customer_id", "fixed_pppoe_cust")
    op.drop_table("fixed_pppoe_cust")
    op.drop_table("users")
