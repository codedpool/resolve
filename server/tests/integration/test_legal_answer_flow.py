"""The grounded-answer node over the real retrieval service, with a scripted model."""

from __future__ import annotations

import app.legal.verifier  # noqa: F401  (puts workflows/src on the path)
from app.legal.retrieval import RetrievalService
from resolve_workflows.nodes.answer import DISCLAIMER, answer_with_citations
from tests.integration.legal_fixtures import hash_embedder, legal_engine, legal_session, loaded_session  # noqa: F401


class CitingLLM:
    """Cites every retrieved chunk whose text contains a given phrase, as a model following the prompt would."""

    def __init__(self, phrase: str, statement: str):
        self.phrase, self.statement, self.calls = phrase, statement, []

    def structured(self, role, prompt_text, variables, schema, mode="instruct"):
        self.calls.append(variables)
        cites = [c["id"] for c in variables["chunks"] if self.phrase in c["text"]]
        if not cites:
            return {"answerable": False, "statements": [], "clarifying_question": "Which company is this about?"}, {}
        return {"answerable": True, "clarifying_question": "",
                "statements": [{"text": self.statement, "kind": "rule", "cites": cites[:1]}]}, {}


def test_grounded_answer_cites_a_retrieved_chunk_and_carries_the_disclaimer(loaded_session, hash_embedder):
    service = RetrievalService(loaded_session, hash_embedder)
    llm = CitingLLM("forty-eight hours", "The grievance officer must acknowledge your complaint within 48 hours.")
    result = answer_with_citations(
        llm, service, "Within how many hours must the grievance officer acknowledge my complaint?", entity_type="marketplace")
    assert result.kind == "grounded"
    ids = {c["id"] for c in llm.calls[0]["chunks"]}
    assert {c.chunk_id for c in result.citations} <= ids
    assert result.citations[0].source_url.startswith("http") and result.citations[0].review_state == "unreviewed"
    assert "E-Commerce" in result.text and DISCLAIMER in result.text


def test_hindi_question_gets_a_grounded_hindi_answer(legal_session):
    """Uses the real local embedding model (cached), because Hindi needs the multilingual vectors."""
    import pytest

    from app.legal.chunker import build_corpus
    from app.legal.embeddings import FastEmbedder
    from app.legal.ingest import ingest

    embedder = FastEmbedder()
    try:
        embedder.embed_query("warm up")
    except Exception as exc:
        pytest.skip(f"embedding model unavailable: {exc}")
    ingest(legal_session, build_corpus(), embedder)
    service = RetrievalService(legal_session, embedder)
    llm = CitingLLM("forty-eight hours", "शिकायत अधिकारी को 48 घंटे के भीतर शिकायत की पावती देनी होगी।")
    result = answer_with_citations(llm, service, "शिकायत अधिकारी कितने घंटे में शिकायत की पावती देगा?", entity_type="marketplace")
    assert llm.calls[0]["language"] == "hi"
    assert result.kind == "grounded" and "पावती" in result.text and DISCLAIMER in result.text
    assert any("E-Commerce" in c.label for c in result.citations)
