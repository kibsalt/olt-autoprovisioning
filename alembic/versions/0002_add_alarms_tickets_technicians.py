"""add technicians, alarms, tickets tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "technicians",
        sa.Column("id",         sa.Integer(),    nullable=False, autoincrement=True),
        sa.Column("name",       sa.String(255),  nullable=False),
        sa.Column("phone",      sa.String(30),   nullable=True),
        sa.Column("email",      sa.String(255),  nullable=True),
        sa.Column("zone",       sa.String(100),  nullable=True),
        sa.Column("active",     sa.Boolean(),    nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(),   nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(),   nullable=True,  onupdate=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "alarms",
        sa.Column("id",          sa.Integer(),  nullable=False, autoincrement=True),
        sa.Column("onu_id",      sa.Integer(),  nullable=False),
        sa.Column("alarm_type",  sa.Enum("los", "low_rx",                              name="alarmtype"),    nullable=False),
        sa.Column("severity",    sa.Enum("critical", "major", "minor",                 name="alarmseverity"), nullable=False),
        sa.Column("status",      sa.Enum("active", "resolved",                         name="alarmstatus"),   nullable=False, server_default="active"),
        sa.Column("rx_power",    sa.Float(),    nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("notes",       sa.Text(),     nullable=True),
        sa.Column("created_at",  sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at",  sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["onu_id"], ["onus.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "tickets",
        sa.Column("id",               sa.Integer(),    nullable=False, autoincrement=True),
        sa.Column("alarm_id",         sa.Integer(),    nullable=True),
        sa.Column("onu_id",           sa.Integer(),    nullable=False),
        sa.Column("customer_id",      sa.String(255),  nullable=False),
        sa.Column("title",            sa.String(500),  nullable=False),
        sa.Column("description",      sa.Text(),       nullable=True),
        sa.Column("status",           sa.Enum("open", "assigned", "in_progress", "resolved", "closed", name="ticketstatus"),   nullable=False, server_default="open"),
        sa.Column("priority",         sa.Enum("high", "medium", "low",                                  name="ticketpriority"), nullable=False, server_default="high"),
        sa.Column("assigned_to",      sa.Integer(),    nullable=True),
        sa.Column("assigned_at",      sa.DateTime(),   nullable=True),
        sa.Column("resolved_at",      sa.DateTime(),   nullable=True),
        sa.Column("resolution_notes", sa.Text(),       nullable=True),
        sa.Column("created_at",       sa.DateTime(),   nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at",       sa.DateTime(),   nullable=True),
        sa.ForeignKeyConstraint(["alarm_id"],    ["alarms.id"],      ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["onu_id"],      ["onus.id"],        ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_to"], ["technicians.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("tickets")
    op.drop_table("alarms")
    op.drop_table("technicians")
