"""side effect keys

Revision ID: c4d8e2a1b6f0
Revises: b7e1c0a9d4f2
Create Date: 2026-11-25 00:50:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e2a1b6f0"
down_revision: Union[str, Sequence[str], None] = "b7e1c0a9d4f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "side_effects",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.execute("CREATE SCHEMA IF NOT EXISTS checkpoints")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoints.threads (
            thread_id text PRIMARY KEY,
            blob bytea NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS checkpoints.threads")
    op.execute("DROP SCHEMA IF EXISTS checkpoints")
    op.drop_table("side_effects")
