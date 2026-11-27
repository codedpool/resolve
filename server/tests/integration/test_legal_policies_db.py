"""A refund question about a provider returns that provider's own policy (fictional fixtures)."""

from __future__ import annotations

import pytest

from app.legal.retrieval import RetrievalService
from tests.integration.legal_fixtures import hash_embedder, legal_engine, legal_session, loaded_session  # noqa: F401

CASES = [
    ("demo_bazaar", "marketplace", "How many days does Demo Bazaar take to refund an item I returned?", "10 working days"),
    ("demo_gadgets_direct", "direct_seller", "What is the Demo Gadgets Direct refund policy for a defective product?", "7 working days"),
    ("demopay_wallet", "payment_intermediary", "DemoPay Wallet debited my money but the order failed, when is the refund?", "5 working days"),
    ("kalpana_demo_crafts", "seller_on_marketplace", "Who pays return shipping for Kalpana Demo Crafts items?", "return shipping"),
]


@pytest.mark.parametrize("slug,entity_type,question,phrase", CASES)
def test_refund_question_returns_the_providers_own_policy(loaded_session, hash_embedder, slug, entity_type, question, phrase):
    results = RetrievalService(loaded_session, hash_embedder).search(question, entity_type, k=3)
    own = [r for r in results if r.source_id == f"provider_{slug}"]
    assert own, [r.locator for r in results]
    assert results[0].source_id == f"provider_{slug}"
    assert any(phrase in r.text for r in own)
    top = own[0]
    assert top.layer == "provider_policy" and top.fetched_at == "2026-11-26"
    assert top.source_url.startswith("fixture://fictional") and "fictional" in top.heading.lower()


def test_other_providers_policies_do_not_answer_for_this_provider(loaded_session, hash_embedder):
    results = RetrievalService(loaded_session, hash_embedder).search(CASES[0][2], "marketplace", k=3)
    assert not any(r.source_id == "provider_demopay_wallet" for r in results)


def test_a_statute_question_is_not_answered_by_a_provider_policy(loaded_session, hash_embedder):
    results = RetrievalService(loaded_session, hash_embedder).search(
        "How long do I have to file a consumer complaint after the cause of action arose?", None, k=3)
    assert not any(r.layer == "provider_policy" for r in results)
