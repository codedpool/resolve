"""Load the chunked corpus into legal_chunks. Idempotent: a chunk is keyed by its content hash."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import LegalChunk, TagReviewState
from app.legal.chunker import Chunk, Corpus
from app.legal.embeddings import Embedder
from app.legal.quotecheck import quotecheck_all


@dataclass
class IngestReport:
    inserted: int = 0
    unchanged: int = 0
    removed: int = 0
    reembedded: int = 0
    checked: int = 0


def _as_datetime(day: str | date) -> datetime:
    if isinstance(day, str):
        day = date.fromisoformat(day)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def ingest(session: Session, corpus: Corpus, embedder: Embedder, batch_size: int = 32) -> IngestReport:
    """Quotecheck every chunk first (any failure stops before the database is touched), then upsert.

    Chunks already stored under the same hash keep their tags and review state. Chunks of the same
    sources whose hash is no longer produced are removed, so a changed source replaces its old chunks.
    """
    report = IngestReport()
    report.checked = quotecheck_all(corpus.chunks, corpus.sources)
    wanted: dict[str, Chunk] = {}
    for chunk in corpus.chunks:
        wanted[chunk.key] = chunk
    source_ids = {c.source_id for c in corpus.chunks} | set(corpus.sources)

    existing = {
        row.content_hash: row
        for row in session.scalars(select(LegalChunk).where(LegalChunk.source_id.in_(source_ids)))
    }
    stale = [row.id for key, row in existing.items() if key not in wanted]
    if stale:
        session.execute(delete(LegalChunk).where(LegalChunk.id.in_(stale)))
        report.removed = len(stale)

    pending: list[tuple[Chunk, LegalChunk | None]] = []
    for key, chunk in wanted.items():
        row = existing.get(key)
        if row is None:
            pending.append((chunk, None))
        elif row.embedding is None or row.embedding_model != embedder.name:
            pending.append((chunk, row))
        else:
            report.unchanged += 1

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = embedder.embed_passages([chunk.search_text for chunk, _ in batch])
        for (chunk, row), vector in zip(batch, vectors):
            if row is None:
                session.add(
                    LegalChunk(
                        content_hash=chunk.key,
                        source_id=chunk.source_id,
                        layer=chunk.layer,
                        source_url=chunk.source_url,
                        fetched_at=_as_datetime(chunk.fetched_at),
                        section=chunk.section,
                        clause=chunk.clause,
                        heading=chunk.heading,
                        ordinal=chunk.ordinal,
                        text=chunk.text,
                        search_text=chunk.search_text,
                        embedding=vector,
                        embedding_model=embedder.name,
                        entity_type_tags=list(chunk.entity_type_tags),
                        tag_review_state=TagReviewState.unreviewed,
                    )
                )
                report.inserted += 1
            else:
                row.embedding = vector
                row.embedding_model = embedder.name
                report.reembedded += 1
    session.flush()
    return report
