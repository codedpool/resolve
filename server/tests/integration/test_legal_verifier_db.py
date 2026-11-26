"""The legal check stored on chunk rows, and what it does to retrieval."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.models import LegalChunk, TagReviewState
from app.legal.retrieval import RetrievalService
from app.legal.verifier import LlmLegalVerifier, review_rows
from tests.integration.legal_fixtures import hash_embedder, legal_engine, legal_session, loaded_session  # noqa: F401
from tests.unit.test_legal_verifier import MODELS, ScriptedLLM

QUERY = "seller shall not refuse to take back goods or refuse to refund consideration if goods are defective"


def _rows(session, source_id, section):
    return list(session.scalars(select(LegalChunk).where(LegalChunk.source_id == source_id, LegalChunk.section == section)))


def test_review_is_stored_with_models_prompt_hash_and_confidence(loaded_session):
    rows = _rows(loaded_session, "ecom_rules_2020_egazette", "6")
    reviews = review_rows(loaded_session, LlmLegalVerifier(ScriptedLLM(), MODELS), rows)
    assert len(reviews) == len(rows)
    row = rows[0]
    assert row.entity_type_tags == ["seller_on_marketplace"]
    assert row.tag_review_state is TagReviewState.llm_reviewed
    assert row.tagger_model == "qwen/qwen3.8-27b" and row.reviewer_model == "openai/gpt-oss-120b"
    assert row.reviewer_confidence == 0.9 and "+" in row.prompt_hash
    assert row.review_rationale.startswith("tagger:")


def test_disagreement_is_stored_as_needs_attention_and_turns_the_boost_off(loaded_session, hash_embedder):
    service = RetrievalService(loaded_session, hash_embedder, boost=5.0)
    base = service.search(QUERY, k=8)
    target = loaded_session.get(LegalChunk, uuid.UUID(base[3].id))
    disagree = ScriptedLLM(review={"verdict": "disagree", "correct_tags": [], "rationale": "no", "evidence": "", "confidence": 0.9})
    review_rows(loaded_session, LlmLegalVerifier(disagree, MODELS), [target])
    assert target.tag_review_state is TagReviewState.needs_attention
    after = service.search(QUERY, entity_type="seller_on_marketplace", k=8)
    assert [r.id for r in after] == [r.id for r in base] and not any(r.boosted for r in after)
    agree = ScriptedLLM(review={"verdict": "agree", "correct_tags": ["seller_on_marketplace"], "rationale": "yes",
                                "evidence": "", "confidence": 0.9})
    review_rows(loaded_session, LlmLegalVerifier(agree, MODELS), [target])
    assert target.tag_review_state is TagReviewState.llm_reviewed
    boosted = service.search(QUERY, entity_type="seller_on_marketplace", k=8)
    assert boosted[0].id == str(target.id) and boosted[0].boosted and boosted[0].review_state == "llm_reviewed"


def test_nothing_sets_legal_reviewed(loaded_session):
    rows = _rows(loaded_session, "nch_about", "1")
    review_rows(loaded_session, LlmLegalVerifier(ScriptedLLM(), MODELS), rows)
    assert all(r.tag_review_state is not TagReviewState.legal_reviewed for r in rows)
