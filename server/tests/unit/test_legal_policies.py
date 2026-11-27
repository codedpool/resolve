"""Provider policy chunks: layer, date, url from the fixtures, and exact quotes of the policy text."""

from __future__ import annotations

from app.legal.policies import chunk_policy, policy_corpus, policy_source_id
from app.legal.providers import load_providers
from app.legal.quotecheck import quotecheck_all


def test_every_fixture_policy_is_chunked_with_layer_date_url_and_passes_quotecheck():
    chunks, sources = policy_corpus()
    providers = load_providers()
    assert len(sources) == len(providers) == 4
    assert quotecheck_all(chunks, sources) == len(chunks)
    for provider in providers:
        own = [c for c in chunks if c.source_id == policy_source_id(provider)]
        assert own and all(c.layer == "provider_policy" for c in own)
        assert all(c.fetched_at == str(provider.contact_candidates[0].fetched_at) for c in own)
        assert all(c.source_url.startswith(provider.contact_candidates[0].source_url) for c in own)
        assert all(c.entity_type_tags == (provider.entity_type.value,) for c in own)
        assert all("fictional" in c.heading.lower() for c in own)
        assert own[0].text.startswith("FICTIONAL POLICY")


def test_a_policy_is_split_into_short_sentence_groups_that_rejoin_to_the_policy():
    provider = load_providers()[0]
    chunks = chunk_policy(provider, target=200)
    assert len(chunks) >= 2
    assert " ".join(c.text for c in chunks) == " ".join(provider.policy.text.split())
