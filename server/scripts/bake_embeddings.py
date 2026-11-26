"""Embedding model bake-off on the main retrieval questions (dense retrieval only, in memory).

Usage: python scripts/bake_embeddings.py [model ...]   (default: every candidate in the registry)
Never touches the held-out questions. Writes the numbers to stdout as JSON.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.legal.chunker import build_corpus  # noqa: E402
from app.legal.embeddings import MODELS, FastEmbedder  # noqa: E402
from app.legal.evalset import load_questions, summarise, top_k_hit  # noqa: E402


def run(name: str) -> dict:
    corpus = build_corpus()
    questions = load_questions(subset="main")
    embedder = FastEmbedder(name)
    started = time.time()
    embedder._load()
    load_s = time.time() - started
    started = time.time()
    matrix = np.array(embedder.embed_passages([c.search_text for c in corpus.chunks]), dtype=np.float32)
    corpus_s = time.time() - started
    started = time.time()
    queries = np.array([embedder.embed_query(q["question"]) for q in questions], dtype=np.float32)
    query_s = (time.time() - started) / len(questions)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    rows = []
    for question, vec in zip(questions, queries):
        order = np.argsort(-(matrix @ vec))[:3]
        rows.append((question, top_k_hit([corpus.chunks[i] for i in order], question["expect"])))
    return {
        "model": name,
        "dim": embedder.dim,
        "load_seconds": round(load_s, 1),
        "embed_corpus_seconds": round(corpus_s, 1),
        "seconds_per_query": round(query_s, 3),
        "chunks": len(corpus.chunks),
        "top3": summarise(rows),
        "misses": [q["id"] for q, ok in rows if not ok],
    }


if __name__ == "__main__":
    names = sys.argv[1:] or list(MODELS)
    for model in names:
        try:
            print(json.dumps(run(model), ensure_ascii=False), flush=True)
        except Exception as exc:  # a candidate that will not install or run is a result too
            print(json.dumps({"model": model, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}), flush=True)
