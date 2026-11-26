"""Corpus ingestion against Postgres with pgvector. Set TEST_DB_NAME to your own database."""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import func, select, text

from app.db.models import LegalChunk, TagReviewState
from app.legal.chunker import build_corpus
from app.legal.ingest import ingest
from app.legal.quotecheck import QuoteCheckError
from tests.integration.legal_fixtures import hash_embedder, legal_engine, legal_session, loaded_session  # noqa: F401


def test_migration_creates_legal_chunks_with_vector_and_full_text_indexes(legal_engine):
    with legal_engine.connect() as conn:
        columns = {r[0]: r[1] for r in conn.execute(text(
            "select column_name, data_type from information_schema.columns where table_name = 'legal_chunks'"))}
        indexes = {r[0]: r[1] for r in conn.execute(text(
            "select indexname, indexdef from pg_indexes where tablename = 'legal_chunks'"))}
    for name in ("content_hash", "source_id", "layer", "source_url", "fetched_at", "section", "text", "embedding",
                 "tsv", "entity_type_tags", "tag_review_state", "review_rationale", "reviewer_model", "reviewer_confidence"):
        assert name in columns, name
    assert columns["tsv"] == "tsvector"
    assert any("USING gin" in d and "tsv" in d for d in indexes.values())
    assert any("USING hnsw" in d and "vector_cosine_ops" in d for d in indexes.values())


def test_ingest_loads_every_chunk_unreviewed_with_embeddings_and_provenance(loaded_session):
    corpus = build_corpus()
    rows = loaded_session.scalars(select(LegalChunk)).all()
    assert len(rows) == len(corpus.chunks)
    assert {r.tag_review_state for r in rows} == {TagReviewState.unreviewed}
    assert all(r.embedding is not None and len(r.embedding) == 384 for r in rows)
    assert all(r.source_url.startswith("http") and r.fetched_at.year == 2026 for r in rows)
    assert {r.layer for r in rows} >= {"statute", "rules", "regulator", "escalation"}
    hits = loaded_session.execute(text(
        "select count(*) from legal_chunks where tsv @@ plainto_tsquery('english', 'grievance officer')")).scalar()
    assert hits > 0


def test_reingestion_is_idempotent(loaded_session, hash_embedder):
    before = {r.id: r.content_hash for r in loaded_session.scalars(select(LegalChunk))}
    report = ingest(loaded_session, build_corpus(), hash_embedder)
    after = {r.id: r.content_hash for r in loaded_session.scalars(select(LegalChunk))}
    assert report.inserted == 0 and report.removed == 0 and report.unchanged == len(before)
    assert before == after


def test_reingestion_keeps_tags_of_unchanged_chunks_and_replaces_changed_ones(loaded_session, hash_embedder):
    corpus = build_corpus()
    row = loaded_session.scalars(select(LegalChunk).where(LegalChunk.source_id == "nch_about")).first()
    row.entity_type_tags = ["marketplace"]
    row.tag_review_state = TagReviewState.llm_reviewed
    loaded_session.flush()
    target = next(c for c in corpus.chunks if c.source_id == "rbi_pr1184" and c.section == "1")
    changed = dataclasses.replace(target, text=target.text.replace("Modi.", "Modi. Added words."))
    corpus.chunks[corpus.chunks.index(target)] = changed
    corpus.sources["rbi_pr1184"] = corpus.sources["rbi_pr1184"].replace("Modi.", "Modi. Added words.")
    report = ingest(loaded_session, corpus, hash_embedder)
    assert report.inserted == 1 and report.removed == 1
    loaded_session.refresh(row)
    assert row.entity_type_tags == ["marketplace"] and row.tag_review_state is TagReviewState.llm_reviewed
    assert loaded_session.scalar(select(func.count()).select_from(LegalChunk)) == len(corpus.chunks)


def test_a_chunk_that_fails_quotecheck_stops_ingestion_before_anything_is_stored(legal_session, hash_embedder):
    corpus = build_corpus()
    corpus.chunks[0] = dataclasses.replace(corpus.chunks[0], text=corpus.chunks[0].text.replace("Act", "Azt", 1))
    with pytest.raises(QuoteCheckError):
        ingest(legal_session, corpus, hash_embedder)
    assert legal_session.scalar(select(func.count()).select_from(LegalChunk)) == 0
