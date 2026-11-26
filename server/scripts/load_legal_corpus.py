"""Load the legal corpus into the database (idempotent) and optionally restore the saved legal check.

Usage: python scripts/load_legal_corpus.py [--database-url URL] [--reviews docs/results/legal-check.json]
Run `alembic upgrade head` first. The first run downloads the embedding model into data/models.
Saved reviews are matched to chunks by content hash, so a chunk whose text changed is not tagged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.db.models import LegalChunk, TagReviewState  # noqa: E402
from app.legal.chunker import build_corpus  # noqa: E402
from app.legal.embeddings import FastEmbedder  # noqa: E402
from app.legal.ingest import ingest  # noqa: E402


def apply_saved_reviews(session: Session, path: Path) -> int:
    saved = json.loads(path.read_text(encoding="utf-8"))["chunks"]
    applied = 0
    for row in session.scalars(select(LegalChunk)):
        review = saved.get(row.content_hash)
        if not review:
            continue
        row.entity_type_tags = list(review["tags"])
        row.tag_review_state = TagReviewState(review["state"])
        row.review_rationale = review["rationale"]
        row.reviewer_confidence = review["reviewer_confidence"]
        row.tagger_model = review["tagger_model"]
        row.reviewer_model = review["reviewer_model"]
        row.prompt_hash = review["prompt_hash"]
        applied += 1
    return applied


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=Settings().database_url)
    parser.add_argument("--reviews", type=Path, default=None)
    args = parser.parse_args()
    with Session(create_engine(args.database_url)) as session:
        report = ingest(session, build_corpus(), FastEmbedder())
        print("ingest", report)
        if args.reviews:
            print("saved reviews applied to", apply_saved_reviews(session, args.reviews), "chunks")
        session.commit()


if __name__ == "__main__":
    main()
