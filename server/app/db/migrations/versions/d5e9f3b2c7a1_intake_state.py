"""intake state

Revision ID: d5e9f3b2c7a1
Revises: c4d8e2a1b6f0
Create Date: 2026-11-27 01:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e9f3b2c7a1"
down_revision: Union[str, Sequence[str], None] = "c4d8e2a1b6f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intake_states",
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("body_enc", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("case_id"),
    )


def downgrade() -> None:
    op.drop_table("intake_states")
