"""follow-up graph state

Revision ID: a8b3c6d1e5f9
Revises: f7a2b5d9c3e4
Create Date: 2026-11-29 09:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b3c6d1e5f9"
down_revision: Union[str, Sequence[str], None] = "f7a2b5d9c3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "follow_up_states",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("body_enc", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("case_id"),
    )


def downgrade() -> None:
    op.drop_table("follow_up_states")
