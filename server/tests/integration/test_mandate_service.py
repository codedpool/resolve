"""Mandate versions, expiry and the disclosure context, against real rows with canary values in every sensitive field."""

import uuid

import pytest
import yaml

from app.config import SERVER_ROOT
from app.core.crypto import unwrap_data_key
from app.db.models import Case, Event
from app.services.case_store import ServerCaseStore
from app.services.mandate_service import check_outreach, mandate_view
from resolve_workflows.graphs.mandate_gate import build_mandate_gate
from resolve_workflows.mandate import MandateBlocked, build_call_context
from tests.integration.test_case_api import _case

SUITE = yaml.safe_load((SERVER_ROOT.parent / "workflows" / "evals" / "datasets" / "safety_suite.yaml").read_text(encoding="utf-8"))
FIXTURE = SUITE["fixture"]
FACTS = {**FIXTURE["disclosable"], **{k: str(v) for k, v in FIXTURE["canaries"].items()}, "company_name": "Zeta Mart", "product": "Zorblax Phone Nine"}


def _step_up(client, headers):
    assert client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers).status_code == 200


def _setup(client, email, disclosure=None):
    headers, case_id = _case(client, email)
    for field, value in FACTS.items():
        made = client.post(f"/cases/{case_id}/facts", json={"field": field, "value": value}, headers=headers)
        assert made.status_code == 201, made.text
        assert client.post(f"/cases/{case_id}/facts/{made.json()['id']}/confirm", headers=headers).status_code == 200
    _step_up(client, headers)
    body = {} if disclosure is None else {"disclosure": disclosure}
    assert client.post(f"/cases/{case_id}/mandate", json=body, headers=headers).status_code == 200
    return headers, case_id


def _store(client, case_id, session):
    case = session.get(Case, uuid.UUID(case_id))
    key = unwrap_data_key(case.data_key_enc, client.app.state.master_key)
    return ServerCaseStore(session, case, key, client.app.state.clock.now), case, key


def test_default_mandate_discloses_only_the_listed_facts_and_no_canary_leaks(client):
    _, case_id = _setup(client, "ms1@example.com")
    with client.app.state.session_factory() as session:
        store, _, _ = _store(client, case_id, session)
        context = build_call_context(store, case_id, None, client.app.state.clock.now(), "Zeta Mart")
        text = context.render()
        assert set(context.disclosed_fields) == set(FIXTURE["disclosure_list"]) | {"company_name"}
        for field, value in FIXTURE["canaries"].items():
            assert str(value) not in text, field
        assert "Zorblax" not in text
        assert FIXTURE["disclosable"]["order_id"] in text
        undisclosable = store.get_undisclosable_values(case_id, 1)
        assert str(FIXTURE["canaries"]["phone"]) in undisclosable and "ms1@example.com" not in text


@pytest.mark.parametrize("listed", [["order_id"], ["phone", "email"], ["card_number", "otp", "amount"], ["address", "pincode", "password"]])
def test_property_for_the_mandate_chosen_on_the_card(client, listed):
    _, case_id = _setup(client, f"ms2{len(listed)}{listed[0]}@example.com", disclosure=listed)
    with client.app.state.session_factory() as session:
        store, _, _ = _store(client, case_id, session)
        text = build_call_context(store, case_id, None, client.app.state.clock.now(), "Zeta Mart").render()
        for field, value in FACTS.items():
            if field in listed:
                assert value in text, field
            elif field != "company_name":
                assert value not in text, field


def test_an_unconfirmed_edit_is_not_disclosed(client):
    headers, case_id = _setup(client, "ms3@example.com", disclosure=["amount"])
    client.post(f"/cases/{case_id}/facts", json={"field": "amount", "value": "6500"}, headers=headers)  # new version, not confirmed
    with client.app.state.session_factory() as session:
        store, _, _ = _store(client, case_id, session)
        assert [f.field for f in store.get_disclosable_facts(case_id, 1)] == ["company_name"]  # neither the new nor the old amount
        assert "4999" not in build_call_context(store, case_id, None, client.app.state.clock.now(), "Zeta Mart").render()


def test_expiry_revocation_and_a_new_version(client):
    headers, case_id = _setup(client, "ms4@example.com", disclosure=["order_id"])
    now = client.app.state.clock.now
    with client.app.state.session_factory() as session:
        store, case, key = _store(client, case_id, session)
        assert check_outreach(session, case.id, key, now()) is None

    _step_up(client, headers)
    second = client.post(f"/cases/{case_id}/mandate", json={"disclosure": ["order_id", "amount"]}, headers=headers).json()["mandate"]
    assert second["version"] == 2
    with client.app.state.session_factory() as session:
        store, case, key = _store(client, case_id, session)
        assert check_outreach(session, case.id, key, now(), version=1) == "superseded"  # a run pinned to version 1 stops
        assert check_outreach(session, case.id, key, now()) is None
        assert mandate_view(session, case.id, key, 1).disclosure == ("order_id",)
        assert mandate_view(session, case.id, key, 2).disclosure == ("order_id", "amount")

    _step_up(client, headers)
    assert client.post(f"/cases/{case_id}/mandate", json={"action": "revoke"}, headers=headers).status_code == 200
    with client.app.state.session_factory() as session:
        store, case, key = _store(client, case_id, session)
        assert check_outreach(session, case.id, key, now()) == "revoked"
        with pytest.raises(MandateBlocked):
            build_call_context(store, case_id, None, now(), "Zeta Mart")

    _step_up(client, headers)
    third = client.post(f"/cases/{case_id}/mandate", json={"expires_in_days": 7}, headers=headers).json()["mandate"]
    assert third["version"] == 3
    client.clock.advance(days=8)
    with client.app.state.session_factory() as session:
        store, case, key = _store(client, case_id, session)
        assert check_outreach(session, case.id, key, now()) == "expired"


def test_the_outreach_gate_blocks_on_an_expired_mandate_and_records_why(client):
    headers, case_id = _setup(client, "ms5@example.com")
    now = client.app.state.clock.now
    client.clock.advance(days=31)
    with client.app.state.session_factory() as session:
        store, case, key = _store(client, case_id, session)
        result = build_mandate_gate(store, now).invoke({"case_id": case_id})
        assert result["status"] == "mandate_required" and result["block_reason"] == "expired"
        session.commit()
        kinds = [e.kind for e in session.query(Event).filter(Event.case_id == case.id)]
        assert "outreach_blocked" in kinds


def test_no_mandate_means_the_gate_is_closed(client):
    _, case_id = _case(client, "ms6@example.com")
    with client.app.state.session_factory() as session:
        store, case, key = _store(client, case_id, session)
        assert build_mandate_gate(store, client.app.state.clock.now).invoke({"case_id": case_id})["block_reason"] == "missing"
