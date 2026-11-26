"""Hybrid retrieval over legal_chunks: pgvector cosine plus Postgres full-text rank, fused by
reciprocal rank fusion, then an entity-type boost. The boost never filters (plan 8.4), and a chunk
whose tags are `needs_attention` gets no boost (plan 8.5)."""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterable

import math

from sqlalchemy import Float, case, cast, func, literal, select
from sqlalchemy.orm import Session

from app.db.models import LegalChunk, TagReviewState
from app.legal.embeddings import Embedder
from app.legal.lexicon import english_terms

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")


@dataclass(frozen=True)
class RetrievedChunk:
    """A retrieval result. `review_state` is the tag review state, shown so answers can say how checked
    the source is. Matches the workflow port Chunk(id, text, layer, source_url, section, review_state)."""

    id: str
    text: str
    layer: str
    source_id: str
    source_url: str
    fetched_at: str
    section: str
    clause: str
    heading: str
    review_state: str
    entity_type_tags: tuple[str, ...] = ()
    score: float = 0.0
    boosted: bool = False
    dense_rank: int | None = None
    text_rank: int | None = None
    clause_numbers: list[int] = field(default_factory=list)

    @property
    def locator(self) -> str:
        return f"{self.source_id}:{self.section}{self.clause}"


def or_query(text: str, expand: bool = True) -> str:
    """Full-text query that matches any Latin-script word. Hindi words found in the small lexicon add
    their English equivalents; Devanagari with no known word yields an empty query."""
    words = [w.lower() for w in _WORD.findall(text)]
    if expand:
        words += [w.lower() for w in english_terms(text) if _WORD.fullmatch(w)]
    return " | ".join(dict.fromkeys(words))


class RetrievalService:
    def __init__(
        self,
        session: Session | Callable[[], Session],
        embedder: Embedder,
        *,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        text_weight: float = 1.0,
        boost: float = 0.25,
        pool: int = 40,
    ) -> None:
        self._session = session
        self.embedder = embedder
        self.rrf_k = rrf_k
        self.dense_weight = dense_weight
        self.text_weight = text_weight
        self.boost = boost
        self.pool = pool

    @contextmanager
    def _use_session(self):
        if isinstance(self._session, Session):
            yield self._session
        else:
            with self._session() as session:
                yield session

    def search(
        self,
        query: str,
        entity_type: str | None = None,
        k: int = 5,
        prefer_sources: Iterable[str] = (),
    ) -> list[RetrievedChunk]:
        """Top k chunks for the query. `entity_type` and `prefer_sources` only raise a chunk's score."""
        vector = self.embedder.embed_query(query)
        tsq = or_query(query)
        with self._use_session() as session:
            dense_ids = session.scalars(
                select(LegalChunk.id)
                .where(LegalChunk.embedding.is_not(None))
                .order_by(LegalChunk.embedding.cosine_distance(vector))
                .limit(self.pool)
            ).all()
            text_ids = self._full_text_ids(session, tsq)
            scores: dict = {}
            for rank, chunk_id in enumerate(dense_ids, start=1):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + self.dense_weight / (self.rrf_k + rank)
            for rank, chunk_id in enumerate(text_ids, start=1):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + self.text_weight / (self.rrf_k + rank)
            rows = {r.id: r for r in session.scalars(select(LegalChunk).where(LegalChunk.id.in_(list(scores))))}
            preferred = set(prefer_sources)
            ranked = []
            for chunk_id, base in scores.items():
                row = rows[chunk_id]
                score, boosted = base, False
                if row.tag_review_state is not TagReviewState.needs_attention:
                    if entity_type and entity_type != "unknown" and entity_type in (row.entity_type_tags or []):
                        score, boosted = score * (1 + self.boost), True
                    if row.source_id in preferred:
                        score, boosted = score * (1 + self.boost), True
                ranked.append((score, boosted, chunk_id))
            ranked.sort(key=lambda item: (-item[0], rows[item[2]].ordinal))
            dense_pos = {cid: i for i, cid in enumerate(dense_ids, start=1)}
            text_pos = {cid: i for i, cid in enumerate(text_ids, start=1)}
            return [
                _result(rows[cid], score, boosted, dense_pos.get(cid), text_pos.get(cid))
                for score, boosted, cid in ranked[:k]
            ]

    def _full_text_ids(self, session: Session, tsq: str) -> list:
        """Chunks matching any query word, ranked by the summed inverse document frequency of the words
        they contain, so a word found in every chunk ("complaint") counts for less than a rare one
        ("forty-eight"). Ties fall back to ts_rank_cd of the whole query."""
        words = tsq.split(" | ") if tsq else []
        if not words:
            return []
        total = session.scalar(select(func.count()).select_from(LegalChunk)) or 0
        matches = {w: LegalChunk.tsv.op("@@")(func.to_tsquery("english", w)) for w in words}
        counts = session.execute(
            select(*[func.count().filter(m).label(f"w{i}") for i, m in enumerate(matches.values())])
        ).one()
        weighted = []
        for (word, match), df in zip(matches.items(), counts):
            if df:
                idf = math.log((total - df + 0.5) / (df + 0.5) + 1.0)
                weighted.append(case((match, literal(idf)), else_=literal(0.0)))
        if not weighted:
            return []
        score = sum(weighted[1:], weighted[0])
        full = func.to_tsquery("english", tsq)
        return list(
            session.scalars(
                select(LegalChunk.id)
                .where(LegalChunk.tsv.op("@@")(full))
                .order_by(cast(score, Float).desc(), func.ts_rank_cd(LegalChunk.tsv, full).desc(), LegalChunk.ordinal)
                .limit(self.pool)
            ).all()
        )


def _result(row: LegalChunk, score: float, boosted: bool, dense_rank, text_rank) -> RetrievedChunk:
    return RetrievedChunk(
        id=str(row.id),
        text=row.text,
        layer=row.layer,
        source_id=row.source_id,
        source_url=row.source_url,
        fetched_at=row.fetched_at.date().isoformat(),
        section=row.section,
        clause=row.clause,
        heading=row.heading,
        review_state=row.tag_review_state.value,
        entity_type_tags=tuple(row.entity_type_tags or ()),
        score=score,
        boosted=boosted,
        dense_rank=dense_rank,
        text_rank=text_rank,
        clause_numbers=[int(n) for n in re.findall(r"\((\d+)\)", row.clause)],
    )
