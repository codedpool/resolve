"""outreach call state

Revision ID: f7a2b5d9c3e4
Revises: e6f1a4c8d2b3
Create Date: 2026-11-28 09:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a2b5d9c3e4"
down_revision: Union[str, Sequence[str], None] = "e6f1a4c8d2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outreach_states",
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("body_enc", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"]),
        sa.PrimaryKeyConstraint("call_id"),
    )


def downgrade() -> None:
    op.drop_table("outreach_states")
