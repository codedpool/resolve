"""The retrieval eval with the real local embedding model: plan thresholds for the top 3.

Needs the ONNX model in server/data/models (it downloads on first use, 465 MB). Skipped if the model
can neither be loaded from the cache nor downloaded.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.legal.chunker import build_corpus
from app.legal.embeddings import FastEmbedder
from app.legal.evalset import DATASET, load_questions, run_eval, summarise, top_k_hit
from app.legal.ingest import ingest
from app.legal.retrieval import RetrievalService
from tests.integration.legal_fixtures import legal_engine  # noqa: F401

pytestmark = pytest.mark.skipif(not DATASET.exists(), reason="workflows repo not checked out next to server")


@pytest.fixture(scope="module")
def service(legal_engine):  # noqa: F811
    embedder = FastEmbedder()
    try:
        embedder.embed_query("warm up")
    except Exception as exc:  # no cached model and no network
        pytest.skip(f"embedding model unavailable: {exc}")
    with Session(legal_engine) as session:
        ingest(session, build_corpus(), embedder)
        session.commit()
        yield RetrievalService(session, embedder)


def _run(service, subset):
    return run_eval(lambda q: service.search(q["question"], q["entity_type"], k=3), load_questions(subset=subset))


def test_main_questions_meet_the_retrieval_thresholds(service):
    summary, detail = _run(service, "main")
    assert summary["all"]["rate"] >= 0.85, detail
    assert summary["hindi"]["rate"] >= 0.70, detail
    assert summary["hindi"]["n"] >= 8


def test_held_out_questions_meet_the_overall_threshold(service):
    summary, detail = _run(service, "heldout")
    assert summary["all"]["n"] == 10
    assert summary["all"]["rate"] >= 0.85, detail


def test_hindi_questions_pooled_over_main_and_held_out_meet_the_hindi_threshold(service):
    rows = [(q, top_k_hit(service.search(q["question"], q["entity_type"], k=3), q["expect"])) for q in load_questions()]
    summary = summarise(rows)
    assert summary["hindi"]["n"] >= 13 and summary["hindi"]["rate"] >= 0.70
