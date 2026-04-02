"""add Others OLT model and description column

Revision ID: 0001
Revises:
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extend the model ENUM to include 'Others'
    op.execute(
        "ALTER TABLE olts MODIFY COLUMN model ENUM("
        "'C300','C320','C600','C620','C650','HSGQ-2','Others'"
        ") NOT NULL"
    )
    # Add description column
    op.add_column(
        "olts",
        sa.Column("description", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("olts", "description")
    op.execute(
        "ALTER TABLE olts MODIFY COLUMN model ENUM("
        "'C300','C320','C600','C620','C650','HSGQ-2'"
        ") NOT NULL"
    )
