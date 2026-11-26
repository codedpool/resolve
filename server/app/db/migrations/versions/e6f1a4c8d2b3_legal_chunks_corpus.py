"""legal chunks for the retrieval corpus

The first schema kept chunk text encrypted. Legal sources are public and the text must be indexed
for full-text search, so the table is rebuilt with plain text, a pgvector column, a generated
tsvector column and its indexes. The table was empty when this migration was written.

Revision ID: e6f1a4c8d2b3
Revises: d5e9f3b2c7a1
Create Date: 2026-11-27 10:00:00

"""
from typing import Sequence, Union

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6f1a4c8d2b3"
down_revision: Union[str, Sequence[str], None] = "d5e9f3b2c7a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.drop_table("legal_chunks")
    op.create_table(
        "legal_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("layer", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("section", sa.String(length=128), nullable=False),
        sa.Column("clause", sa.String(length=64), server_default="", nullable=False),
        sa.Column("heading", sa.Text(), server_default="", nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', search_text)", persisted=True),
            nullable=True,
        ),
        sa.Column("entity_type_tags", postgresql.ARRAY(sa.String(length=32)), server_default="{}", nullable=False),
        sa.Column(
            "tag_review_state",
            postgresql.ENUM(
                "unreviewed", "llm_reviewed", "needs_attention", "legal_reviewed", name="tag_review_state", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("review_rationale", sa.Text(), nullable=True),
        sa.Column("tagger_model", sa.String(length=128), nullable=True),
        sa.Column("reviewer_model", sa.String(length=128), nullable=True),
        sa.Column("reviewer_confidence", sa.Float(), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "layer in ('statute', 'rules', 'regulator', 'provider_policy', 'escalation')", name="legal_chunks_layer"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
    )
    op.create_index("ix_legal_chunks_source_id", "legal_chunks", ["source_id"])
    op.create_index("ix_legal_chunks_tsv", "legal_chunks", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_legal_chunks_embedding",
        "legal_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("legal_chunks")
    op.create_table(
        "legal_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("layer", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("section", sa.String(length=128), nullable=False),
        sa.Column("chunk_enc", sa.LargeBinary(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.Column("entity_tags_enc", sa.LargeBinary(), nullable=True),
        sa.Column(
            "tag_review_state",
            postgresql.ENUM(
                "unreviewed", "llm_reviewed", "needs_attention", "legal_reviewed", name="tag_review_state", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("rationale_enc", sa.LargeBinary(), nullable=True),
        sa.Column("reviewer_model", sa.String(length=128), nullable=True),
        sa.Column("reviewer_confidence", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
