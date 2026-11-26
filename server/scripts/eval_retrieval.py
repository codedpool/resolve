"""Run the retrieval eval against a throwaway database (created if missing, migrated, loaded).

Usage: python scripts/eval_retrieval.py --db resolve_test_legal [--subset main|heldout|all]
       [--model NAME] [--mode hybrid|dense|text] [--dense-weight W] [--text-weight W] [--boost B]
The held-out set is only meant to be run for the final numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.db.models import EMBEDDING_DIM, LegalChunk  # noqa: E402
from app.legal.chunker import build_corpus  # noqa: E402
from app.legal.embeddings import DEFAULT_MODEL, FastEmbedder  # noqa: E402
from app.legal.evalset import load_questions, run_eval  # noqa: E402
from app.legal.ingest import ingest  # noqa: E402
from app.legal.retrieval import RetrievalService  # noqa: E402

ADMIN_URL = "postgresql://resolve:resolve@127.0.0.1:5434/resolve"


def prepare(db: str) -> str:
    if not db.startswith("resolve_test") and not db.startswith("resolve_eval"):
        raise SystemExit("refusing to use a database that is not a test or eval database")
    url = f"postgresql+psycopg://resolve:resolve@127.0.0.1:5434/{db}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {db}")
    os.environ["ALEMBIC_URL"] = url
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--subset", default="main")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--mode", default="hybrid", choices=["hybrid", "dense", "text"])
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--text-weight", type=float, default=1.0)
    parser.add_argument("--boost", type=float, default=0.25)
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()

    url = prepare(args.db)
    embedder = FastEmbedder(args.model)
    if embedder.dim != EMBEDDING_DIM:  # compare a model with another width: resize the throwaway column
        with psycopg.connect(url.replace("+psycopg", ""), autocommit=True) as conn:
            conn.execute("DROP INDEX ix_legal_chunks_embedding")
            conn.execute(f"ALTER TABLE legal_chunks ALTER COLUMN embedding TYPE vector({embedder.dim})")
        LegalChunk.__table__.c.embedding.type.dim = embedder.dim
    with Session(create_engine(url)) as session:
        report = ingest(session, build_corpus(), embedder)
        session.commit()
        dense, text = args.dense_weight, args.text_weight
        if args.mode == "dense":
            text = 0.0
        if args.mode == "text":
            dense = 0.0
        service = RetrievalService(session, embedder, dense_weight=dense, text_weight=text, boost=args.boost)
        questions = load_questions(subset=None if args.subset == "all" else args.subset)
        summary, detail = run_eval(lambda q: service.search(q["question"], q["entity_type"], k=3), questions)
    out = {"model": args.model, "mode": args.mode, "subset": args.subset, "ingest": report.__dict__, "summary": summary}
    if args.detail:
        out["misses"] = [d for d in detail if not d["hit"]]
    print("RESULT " + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
