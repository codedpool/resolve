import random
from datetime import datetime, timedelta, timezone

import pytest

from resolve_workflows import datasets
from resolve_workflows.fakes import FakeCaseStore, make_mandate
from resolve_workflows.graphs.mandate_gate import build_mandate_gate
from resolve_workflows.mandate import ALWAYS_ALLOWED, DisclosableFact, MandateBlocked, build_call_context, mandate_problem

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
FIXTURE = datasets.load_safety_suite()["fixture"]
# Every sensitive field plus the ordinary fact fields, each with a value that is unique and easy to search for.
EXTRA = {
    "product": "Zorblax Phone Nine", "payment_mode": "canarypay wallet", "promised_date": "2026-11-30",
    "refund_reference": "RFND-CANARY-771", "company_said": "canary said it will be soon", "desired_remedy": "canary remedy",
}
CASE_FACTS = {**FIXTURE["disclosable"], **FIXTURE["canaries"], **EXTRA, "company_name": "Zeta Mart"}
UNLISTABLE = [f for f in CASE_FACTS if f not in ALWAYS_ALLOWED]


def _store(disclosure, **kw):
    return FakeCaseStore(CASE_FACTS, [make_mandate(disclosure=disclosure, now=NOW, **kw)])


def test_no_unlisted_value_appears_in_any_built_context():
    rng = random.Random(7)
    for _ in range(300):
        listed = [f for f in UNLISTABLE if rng.random() < 0.4]
        store = _store(listed)
        text = build_call_context(store, "case-1", None, NOW, "Zeta Mart").render()
        for field in UNLISTABLE:
            value = CASE_FACTS[field]
            if field in listed:
                assert value in text, (field, listed)
            else:
                assert value not in text, (field, listed)


def test_every_single_field_alone_and_every_field_but_one():
    for field in UNLISTABLE:
        text = build_call_context(_store([field]), "case-1", 1, NOW, "Zeta Mart").render()
        assert CASE_FACTS[field] in text
        assert all(CASE_FACTS[o] not in text for o in UNLISTABLE if o != field)
        others = [f for f in UNLISTABLE if f != field]
        text = build_call_context(_store(others), "case-1", 1, NOW, "Zeta Mart").render()
        assert CASE_FACTS[field] not in text


def test_the_default_mandate_shows_only_the_default_facts():
    store = _store(FIXTURE["disclosure_list"])
    context = build_call_context(store, "case-1", None, NOW, "Zeta Mart")
    assert set(context.disclosed_fields) == set(FIXTURE["disclosure_list"]) | {"company_name"}
    for field, value in FIXTURE["canaries"].items():
        assert value not in context.render(), field


class LeakyStore(FakeCaseStore):
    """A store with a bug: it hands over every fact as disclosable. The builder must still filter by the mandate."""

    def get_disclosable_facts(self, case_id, mandate_version):
        return [DisclosableFact(f, v) for f, v in self.facts.items()]


def test_the_builder_filters_even_when_the_store_over_returns():
    store = LeakyStore(CASE_FACTS, [make_mandate(disclosure=["order_id"], now=NOW)])
    text = build_call_context(store, "case-1", None, NOW, "Zeta Mart").render()
    assert CASE_FACTS["order_id"] in text
    for field in UNLISTABLE:
        if field != "order_id":
            assert CASE_FACTS[field] not in text, field


def test_a_value_inside_an_allowed_field_is_masked():
    facts = dict(CASE_FACTS, issue_summary=f"refund missing, call me on {FIXTURE['canaries']['phone']} or mail {FIXTURE['canaries']['email']}")
    store = FakeCaseStore(facts, [make_mandate(disclosure=["issue_summary"], now=NOW)])
    text = build_call_context(store, "case-1", None, NOW, "Zeta Mart").render()
    assert FIXTURE["canaries"]["phone"] not in text and FIXTURE["canaries"]["email"] not in text
    assert "[withheld]" in text and "refund missing" in text


def test_approximate_certainty_is_carried():
    store = FakeCaseStore({"amount": "15000"}, [make_mandate(disclosure=["amount"], now=NOW)], certainty={"amount": "approximate"})
    context = build_call_context(store, "case-1", None, NOW, "Zeta Mart")
    assert context.variables["disclosable_facts"] == [{"field": "amount", "value": "15000", "certainty": "approximate"}]


def test_partial_settlement_is_never_allowed_even_if_the_mandate_says_so():
    store = FakeCaseStore(CASE_FACTS, [make_mandate(disclosure=["amount"], now=NOW, limits={"accept_partial": True})])
    assert build_call_context(store, "case-1", None, NOW, "Zeta Mart").variables["boundaries"]["accept_partial_settlement"] is False


@pytest.mark.parametrize(
    "kwargs, reason",
    [({"days": -1}, "expired"), ({"revoked": True}, "revoked"), ({"version": 1, "latest_version": 2}, "superseded")],
)
def test_a_blocked_mandate_stops_the_context_and_the_gate(kwargs, reason):
    store = FakeCaseStore(CASE_FACTS, [make_mandate(now=NOW, **kwargs)])
    if kwargs.get("latest_version"):
        store.mandates.append(make_mandate(version=2, now=NOW))
    with pytest.raises(MandateBlocked) as caught:
        build_call_context(store, "case-1", kwargs.get("version"), NOW, "Zeta Mart")
    assert caught.value.reason == reason
    result = build_mandate_gate(store, lambda: NOW).invoke({"case_id": "case-1", "mandate_version": kwargs.get("version")})
    assert result["status"] == "mandate_required" and result["block_reason"] == reason
    assert store.events[-1][1] == "outreach_blocked" and store.events[-1][2] == {"reason": reason}


def test_no_mandate_blocks():
    store = FakeCaseStore(CASE_FACTS, [])
    with pytest.raises(MandateBlocked) as caught:
        build_call_context(store, "case-1", None, NOW, "Zeta Mart")
    assert caught.value.reason == "missing"
    assert build_mandate_gate(store, lambda: NOW).invoke({"case_id": "case-1"})["status"] == "mandate_required"


def test_a_good_mandate_opens_the_gate_and_the_clock_decides_expiry():
    store = _store(["order_id"], days=1)
    gate = build_mandate_gate(store, lambda: NOW)
    assert gate.invoke({"case_id": "case-1"})["status"] == "ready"
    later = build_mandate_gate(store, lambda: NOW + timedelta(days=1, seconds=1))
    assert later.invoke({"case_id": "case-1"})["block_reason"] == "expired"


def test_a_new_mandate_version_supersedes_a_run_pinned_to_the_old_one():
    store = FakeCaseStore(CASE_FACTS, [make_mandate(version=1, disclosure=["order_id"], now=NOW)])
    assert mandate_problem(store.get_mandate("case-1", 1), NOW) is None
    store.mandates.append(make_mandate(version=2, disclosure=["order_id", "amount"], now=NOW))
    assert mandate_problem(store.get_mandate("case-1", 1), NOW) == "superseded"
    assert mandate_problem(store.get_mandate("case-1"), NOW) is None
    assert "4999" in build_call_context(store, "case-1", None, NOW, "Zeta Mart").render()


def test_the_prompt_file_is_versioned():
    context = build_call_context(_store(["order_id"]), "case-1", None, NOW, "Zeta Mart")
    assert context.prompt.name == "provider_call" and context.prompt.version == 1
