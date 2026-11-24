"""outbox jobs

Revision ID: b7e1c0a9d4f2
Revises: 68af8051a2be
Create Date: 2026-11-25 00:40:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e1c0a9d4f2"
down_revision: Union[str, Sequence[str], None] = "68af8051a2be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload_enc", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency"),
    )
    op.create_index("ix_outbox_jobs_next_attempt_at", "outbox_jobs", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_jobs_next_attempt_at", table_name="outbox_jobs")
    op.drop_table("outbox_jobs")
