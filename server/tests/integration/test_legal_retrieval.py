"""Hybrid retrieval behaviour: fusion, entity boost that never filters, no boost for needs_attention."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.models import LegalChunk, TagReviewState
from app.legal.retrieval import RetrievalService, or_query
from tests.integration.legal_fixtures import hash_embedder, legal_engine, legal_session, loaded_session  # noqa: F401

QUERY = "seller shall not refuse to take back goods or refuse to refund consideration if goods are defective"


def _row(session, source_id, section, clause_contains=""):
    for row in session.scalars(select(LegalChunk).where(LegalChunk.source_id == source_id, LegalChunk.section == section)):
        if clause_contains in row.clause:
            return row
    raise AssertionError(f"no chunk {source_id} {section}")


def test_or_query_keeps_latin_words_and_expands_known_hindi_words():
    assert or_query("Refund ka order, kya hai?", expand=False) == "refund | order | kya | hai"
    assert or_query("उपभोक्ता शिकायत", expand=False) == ""
    assert or_query("उपभोक्ता शिकायत") == "complaint | consumer"
    assert or_query("kharab saman ka refund") == "kharab | saman | refund | defective | defect | goods"
    assert or_query("मौसम कैसा है?") == ""


def test_results_carry_source_layer_date_and_review_state(loaded_session, hash_embedder):
    results = RetrievalService(loaded_session, hash_embedder).search(QUERY, k=5)
    assert results
    top = results[0]
    assert top.source_url.startswith("http") and top.fetched_at == "2026-11-26"
    assert top.layer in {"statute", "rules", "regulator", "escalation"}
    assert top.review_state == "unreviewed" and top.id and top.text


def test_full_text_and_vector_both_contribute_to_the_fusion(loaded_session, hash_embedder):
    results = RetrievalService(loaded_session, hash_embedder).search(QUERY, k=10)
    assert any(r.text_rank for r in results) and any(r.dense_rank for r in results)
    assert any(r.text_rank and r.dense_rank for r in results)


def test_rule_6_3_is_found_without_any_entity_tag(loaded_session, hash_embedder):
    results = RetrievalService(loaded_session, hash_embedder).search(QUERY, entity_type="seller_on_marketplace", k=5)
    assert any(r.source_id == "ecom_rules_2020_egazette" and r.section == "6" for r in results)


def test_a_wrong_entity_tag_does_not_hide_the_right_chunk(loaded_session, hash_embedder):
    right = _row(loaded_session, "ecom_rules_2020_egazette", "6", "(3)")
    right.entity_type_tags = ["payment_intermediary"]  # wrong on purpose
    right.tag_review_state = TagReviewState.llm_reviewed
    other = _row(loaded_session, "nch_about", "1")
    other.entity_type_tags = ["seller_on_marketplace"]
    other.tag_review_state = TagReviewState.llm_reviewed
    loaded_session.flush()
    results = RetrievalService(loaded_session, hash_embedder).search(QUERY, entity_type="seller_on_marketplace", k=5)
    assert str(right.id) in [r.id for r in results], "the boost must never act as a filter"


def test_boost_raises_a_matching_chunk_but_needs_attention_gets_none(loaded_session, hash_embedder):
    service = RetrievalService(loaded_session, hash_embedder, boost=5.0)
    base = [r.id for r in service.search(QUERY, k=8)]
    target = loaded_session.get(LegalChunk, uuid.UUID(base[3]))
    target.entity_type_tags = ["seller_on_marketplace"]
    target.tag_review_state = TagReviewState.llm_reviewed
    loaded_session.flush()
    boosted = service.search(QUERY, entity_type="seller_on_marketplace", k=8)
    assert boosted[0].id == str(target.id) and boosted[0].boosted
    target.tag_review_state = TagReviewState.needs_attention
    loaded_session.flush()
    after = service.search(QUERY, entity_type="seller_on_marketplace", k=8)
    assert [r.id for r in after] == base and not any(r.boosted for r in after)


def test_unknown_entity_type_boosts_nothing(loaded_session, hash_embedder):
    target = _row(loaded_session, "cpa2019_egazette", "41")
    target.entity_type_tags = ["unknown"]
    loaded_session.flush()
    results = RetrievalService(loaded_session, hash_embedder, boost=5.0).search(QUERY, entity_type="unknown", k=8)
    assert not any(r.boosted for r in results)
