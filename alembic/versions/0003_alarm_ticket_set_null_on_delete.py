"""change alarms/tickets onu_id FK from CASCADE to SET NULL, add serial_number to alarms

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add serial_number column to alarms for history after ONU deletion
    op.add_column("alarms", sa.Column("serial_number", sa.String(16), nullable=True))

    # Backfill serial_number from onus table
    op.execute(
        "UPDATE alarms a JOIN onus o ON a.onu_id = o.id SET a.serial_number = o.serial_number"
    )

    # alarms: drop CASCADE FK, make nullable, add SET NULL FK
    op.drop_constraint("alarms_ibfk_1", "alarms", type_="foreignkey")
    op.alter_column("alarms", "onu_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key("alarms_ibfk_1", "alarms", "onus", ["onu_id"], ["id"], ondelete="SET NULL")

    # tickets: drop CASCADE FK, make nullable, add SET NULL FK
    op.drop_constraint("tickets_ibfk_2", "tickets", type_="foreignkey")
    op.alter_column("tickets", "onu_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key("tickets_ibfk_2", "tickets", "onus", ["onu_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("tickets_ibfk_2", "tickets", type_="foreignkey")
    op.alter_column("tickets", "onu_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key("tickets_ibfk_2", "tickets", "onus", ["onu_id"], ["id"], ondelete="CASCADE")

    op.drop_constraint("alarms_ibfk_1", "alarms", type_="foreignkey")
    op.alter_column("alarms", "onu_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key("alarms_ibfk_1", "alarms", "onus", ["onu_id"], ["id"], ondelete="CASCADE")

    op.drop_column("alarms", "serial_number")
