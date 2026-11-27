"""Follow-up over REST: a company reply or a missed date goes through the follow-up graph; reminders fire with the injectable
clock; only the consumer's own action makes a case `resolved_consumer_confirmed`; nobody else can touch the case."""

import json
import uuid
from datetime import timedelta

from app.core.crypto import seal_text, unwrap_data_key
from app.db.models import Approval, Case, CaseStatus, Deadline, DeadlineStatus, Event, Evidence
from resolve_workflows.nodes.classify_turn import REPLY_LABELS
from tests.integration.test_auth import _signup
from tests.integration.test_case_api import _case
from tests.integration.test_mandate_service import _step_up

CLAIM = "Your refund of Rs 4999 was processed on 20 November 2026, reference ZM-REF-558201."


class ReplyModel:
    """The classifier port for replies: answers with a fixed label, or is down."""

    def __init__(self, label="rejected", down=False):
        self.label, self.down, self.seen = label, down, []

    def classify(self, role, prompt, text, labels):
        self.seen.append(text)
        assert labels == REPLY_LABELS
        if self.down:
            raise RuntimeError("model unavailable")
        return self.label, 0.9, {}


def _model(client, label="rejected", down=False):
    client.app.state.intake_llm = ReplyModel(label, down)
    return client.app.state.intake_llm


def _facts(client, headers, case_id, entity_type="marketplace", certainty="stated", confirm=True):
    for field, value, cert in [("company_name", "Zeta Mart", "stated"), ("amount", "4999", "stated"), ("order_id", "OD43817265", "stated"),
                               ("order_date", "2026-11-12", "stated"), ("provider_entity_type", entity_type, certainty)]:
        made = client.post(f"/cases/{case_id}/facts", json={"field": field, "value": value, "certainty": cert}, headers=headers)
        assert made.status_code == 201, made.text
        if confirm:
            assert client.post(f"/cases/{case_id}/facts/{made.json()['id']}/confirm", headers=headers).status_code == 200


def _credit(client, case_id, amount="4999", date="2026-11-20", reference="ZM-REF-558201"):
    with client.app.state.session_factory() as session:
        case = session.get(Case, uuid.UUID(case_id))
        key = unwrap_data_key(case.data_key_enc, client.app.state.master_key)
        session.add(Evidence(case_id=case.id, file_ref="x", type="refund_confirmation",
                             fields_enc=seal_text(json.dumps({"fields": {"amount": amount, "date": date, "reference": reference}}), key)))
        session.commit()


def _advance(client, headers, email, **delta):
    """Move the clock and sign in again: access tokens last 15 minutes. The headers dict is updated in place."""
    client.clock.advance(**delta)
    login = client.post("/auth/login", json={"email": email, "password": "correct-horse"})
    assert login.status_code == 200, login.text
    headers["Authorization"] = f"Bearer {login.json()['access_token']}"


def _status(client, case_id):
    with client.app.state.session_factory() as session:
        return session.get(Case, uuid.UUID(case_id)).status


def _set_status(client, case_id, status):
    with client.app.state.session_factory() as session:
        session.get(Case, uuid.UUID(case_id)).status = CaseStatus(status)
        session.commit()


def _post(client, headers, case_id, **body):
    sent = client.post(f"/cases/{case_id}/follow-up", json=body, headers=headers)
    assert sent.status_code == 200, sent.text
    return sent.json()


def _notes(client, headers):
    return client.get("/notifications", headers=headers).json()["notifications"]


def _approvals(client, headers, case_id):
    return client.get(f"/approvals?case={case_id}", headers=headers).json()["approvals"]


def test_a_verified_claim_is_only_a_claim_until_the_consumer_confirms(client):
    _model(client, "resolved_claimed")
    headers, case_id = _case(client, "fu1@example.com")
    _facts(client, headers, case_id)
    _credit(client, case_id)
    out = _post(client, headers, case_id, reply_text=CLAIM)
    assert out["label"] == "resolved_claimed" and out["verdict"]["overall"] == "match" and out["action"] == "confirm_receipt"
    assert out["case_status"] == "provider_claimed_resolved" and out["simulated"] is True
    assert client.get(f"/cases/{case_id}", headers=headers).json()["status"] == "provider_claimed_resolved"
    kinds = [e["kind"] for e in client.get(f"/cases/{case_id}", headers=headers).json()["timeline"]]
    assert kinds.count("follow_up") == 1


def test_a_claim_that_does_not_match_the_evidence_goes_back_to_the_consumer(client):
    _model(client, "resolved_claimed")
    headers, case_id = _case(client, "fu2@example.com")
    _facts(client, headers, case_id)
    _credit(client, case_id)
    out = _post(client, headers, case_id, reply_text="We refunded Rs 4500 on 20 November 2026, reference ZM-REF-558201.")
    assert out["verdict"]["overall"] == "mismatch" and out["case_status"] == "awaiting_consumer" and out["action"] == "ask_proof"
    assert len(_approvals(client, headers, case_id)) == 1
    other = client.post("/cases", headers=headers).json()["id"]
    _facts(client, headers, other)
    missing = _post(client, headers, other, reply_text=CLAIM)  # no credit in the evidence: nothing to compare with
    assert missing["verdict"]["overall"] == "missing" and missing["case_status"] == "awaiting_consumer"


def test_every_reply_class_over_the_api(client):
    headers, case_id = _case(client, "fu3@example.com")
    _facts(client, headers, case_id)
    expected = {"partial": "review_offer", "rejected": "escalate", "needs_info": "provide_info", "resolved_claimed": "ask_proof"}
    for index, (label, action) in enumerate(expected.items()):
        _model(client, label)
        out = _post(client, headers, case_id, reply_text=f"Reply number {index} about {label}.")
        assert out["label"] == label and out["action"] == action
        assert out["case_status"] in {"awaiting_consumer", "provider_claimed_resolved"}


def test_with_the_model_down_the_keyword_reader_is_used_and_said(client):
    _model(client, down=True)
    headers, case_id = _case(client, "fu4@example.com")
    _facts(client, headers, case_id)
    out = _post(client, headers, case_id, reply_text="Your request is declined as it is outside the return window.")
    assert out["label"] == "rejected" and out["understood"]["degraded"] is True and out["understood"]["source"] == "keywords"


def test_the_model_sees_the_redacted_reply_and_the_timeline_keeps_that_text_only(client):
    model = _model(client, "rejected")
    headers, case_id = _case(client, "fu5@example.com")
    _facts(client, headers, case_id)
    _post(client, headers, case_id, reply_text="Declined. The OTP 482913 we sent will not be refunded either.")
    assert model.seen and "482913" not in model.seen[0]
    body = json.dumps(client.get(f"/cases/{case_id}", headers=headers).json()["timeline"])
    assert "482913" not in body


def test_a_known_type_picks_its_route_and_the_owner_decides_the_approval_with_step_up(client):
    _model(client, "rejected")
    headers, case_id = _case(client, "fu6@example.com")
    _facts(client, headers, case_id, entity_type="payment_intermediary")
    out = _post(client, headers, case_id, reply_text="Declined.")
    assert out["escalation"]["needs_choice"] is False and out["escalation"]["selected"]["kind"] == "rbi_ombudsman"
    assert [r["kind"] for r in out["escalation"]["candidates"]] == ["rbi_ombudsman", "national_consumer_helpline", "consumer_commission_portal"]
    approvals = _approvals(client, headers, case_id)
    assert len(approvals) == 1 and approvals[0]["status"] == "pending" and approvals[0]["id"] == out["approval_id"]
    payload = json.loads(approvals[0]["payload"])
    assert payload["target"]["kind"] == "rbi_ombudsman" and payload["simulated"] is True
    _step_up(client, headers)
    client.clock.advance(minutes=11)
    assert client.post(f"/approvals/{out['approval_id']}/decision", json={"decision": "approve"}, headers=headers).status_code == 403
    _step_up(client, headers)
    done = client.post(f"/approvals/{out['approval_id']}/decision", json={"decision": "approve"}, headers=headers)
    assert done.status_code == 200 and done.json()["status"] == "approved"
    assert _status(client, case_id) != CaseStatus.resolved_consumer_confirmed


def test_an_unknown_type_shows_every_route_and_waits_for_the_consumer(client):
    _model(client, "rejected")
    headers, case_id = _case(client, "fu7@example.com")
    _facts(client, headers, case_id, entity_type="unknown")
    out = _post(client, headers, case_id, reply_text="Declined.")
    assert out["escalation"]["needs_choice"] is True and out["escalation"]["selected"] is None and out["approval_id"] == ""
    assert {r["kind"] for r in out["escalation"]["candidates"]} == {
        "national_consumer_helpline", "consumer_commission_portal", "rbi_ombudsman", "marketplace_grievance"}
    assert _approvals(client, headers, case_id) == []
    shown = client.get(f"/cases/{case_id}/follow-up", headers=headers).json()
    assert len(shown["pending_choice"]["candidates"]) == 4 and shown["last"]["needs_choice"] is True
    bad = client.post(f"/cases/{case_id}/follow-up/choose-route", json={"kind": "made_up"}, headers=headers)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "bad_route"
    chosen = client.post(f"/cases/{case_id}/follow-up/choose-route", json={"kind": "consumer_commission_portal"}, headers=headers)
    assert chosen.status_code == 200 and chosen.json()["approval_id"]
    approvals = _approvals(client, headers, case_id)
    assert len(approvals) == 1 and json.loads(approvals[0]["payload"])["target"]["kind"] == "consumer_commission_portal"
    assert client.get(f"/cases/{case_id}/follow-up", headers=headers).json()["pending_choice"] is None
    again = client.post(f"/cases/{case_id}/follow-up/choose-route", json={"kind": "consumer_commission_portal"}, headers=headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "no_choice_pending"


def test_a_guessed_type_is_treated_like_an_unknown_one(client):
    _model(client, "rejected")
    headers, case_id = _case(client, "fu8@example.com")
    _facts(client, headers, case_id, entity_type="marketplace", certainty="inferred", confirm=False)
    out = _post(client, headers, case_id, reply_text="Declined.")
    assert out["escalation"]["needs_choice"] is True and len(out["escalation"]["candidates"]) == 4


def test_a_reminder_fires_once_with_the_clock_and_a_missed_date_goes_to_the_graph(client):
    _model(client, "rejected")
    headers, case_id = _case(client, "fu9@example.com")
    _facts(client, headers, case_id, entity_type="marketplace")
    out = _post(client, headers, case_id, reply_text="Declined.")
    reminder = out["reminder"]
    assert reminder["kind"] == "followup_escalation_check"
    due = client.clock.now() + timedelta(days=7)
    assert reminder["due_at"] == due.isoformat()
    shown = client.get(f"/cases/{case_id}/follow-up", headers=headers).json()
    assert [r["id"] for r in shown["reminders"]] == [reminder["id"]]
    assert [n for n in _notes(client, headers) if n["kind"] == "deadline"] == []
    early = client.post(f"/cases/{case_id}/follow-up", json={"deadline_id": reminder["id"]}, headers=headers)
    assert early.status_code == 409 and early.json()["error"]["code"] == "deadline_not_due"
    _advance(client, headers, "fu9@example.com", days=6, hours=23)
    assert [n for n in _notes(client, headers) if n["kind"] == "deadline"] == []
    _advance(client, headers, "fu9@example.com", hours=2)
    fired = [n for n in _notes(client, headers) if n["kind"] == "deadline"]
    assert len(fired) == 1 and fired[0]["payload"]["deadline_id"] == reminder["id"] and fired[0]["payload"]["case_id"] == case_id
    assert len([n for n in _notes(client, headers) if n["kind"] == "deadline"]) == 1  # reading again does not fire it again
    _advance(client, headers, "fu9@example.com", days=30)
    assert len([n for n in _notes(client, headers) if n["kind"] == "deadline"]) == 1
    # the missed date goes through the graph as the company's silence
    silent = _post(client, headers, case_id, deadline_id=reminder["id"])
    assert silent["label"] == "silence" and silent["action"] == "escalate" and silent["approval_id"]
    again = _post(client, headers, case_id, deadline_id=reminder["id"])
    assert again["duplicate"] is True and again["approval_id"] == silent["approval_id"]
    with client.app.state.session_factory() as session:
        assert session.query(Approval).count() == 2


def test_a_reminder_never_fires_before_its_time_even_if_read_many_times(client):
    _model(client, "needs_info")
    headers, case_id = _case(client, "fu10@example.com")
    _facts(client, headers, case_id)
    _post(client, headers, case_id, reply_text="Please share a photo.")
    for _ in range(3):
        assert [n for n in _notes(client, headers) if n["kind"] == "deadline"] == []
    _advance(client, headers, "fu10@example.com", days=3)
    assert len([n for n in _notes(client, headers) if n["kind"] == "deadline"]) == 1


def test_resolved_consumer_confirmed_comes_only_from_the_consumer_endpoint(client):
    headers, case_id = _case(client, "fu11@example.com")
    _facts(client, headers, case_id, entity_type="unknown")
    _credit(client, case_id)
    # every kind of event the graph handles, claim or not, leaves the case short of resolved
    for label, text in [("resolved_claimed", CLAIM), ("partial", "A voucher instead."), ("rejected", "Declined."), ("needs_info", "Please send a photo."), ("silence", "")]:
        _model(client, label)
        if text:
            _post(client, headers, case_id, reply_text=text)
        assert _status(client, case_id) != CaseStatus.resolved_consumer_confirmed
    assert _status(client, case_id) == CaseStatus.awaiting_consumer or _status(client, case_id) == CaseStatus.provider_claimed_resolved
    _set_status(client, case_id, "provider_claimed_resolved")
    # no step-up: refused
    refused = client.post(f"/cases/{case_id}/confirm-resolved", headers=headers)
    assert refused.status_code == 403 and _status(client, case_id) == CaseStatus.provider_claimed_resolved
    _step_up(client, headers)
    done = client.post(f"/cases/{case_id}/confirm-resolved", headers=headers)
    assert done.status_code == 200 and done.json()["status"] == "resolved_consumer_confirmed" and done.json()["simulated"] is True
    assert _status(client, case_id) == CaseStatus.resolved_consumer_confirmed
    assert client.post(f"/cases/{case_id}/confirm-resolved", headers=headers).status_code == 409
    # the open reminders are cancelled, and a late reply cannot reopen the case
    with client.app.state.session_factory() as session:
        assert session.query(Deadline).filter(Deadline.status == DeadlineStatus.scheduled).count() == 0
        assert "consumer_confirmed_resolved" in [e.kind for e in session.query(Event).all()]
    _advance(client, headers, "fu11@example.com", days=30)
    assert [n for n in _notes(client, headers) if n["kind"] == "deadline"] == []
    _model(client, "rejected")
    late = _post(client, headers, case_id, reply_text="Actually declined.")
    assert late["case_status"] == "resolved_consumer_confirmed" and _status(client, case_id) == CaseStatus.resolved_consumer_confirmed


def test_confirm_resolved_is_refused_before_the_case_is_under_way(client):
    headers, case_id = _case(client, "fu12@example.com")
    _step_up(client, headers)
    refused = client.post(f"/cases/{case_id}/confirm-resolved", headers=headers)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_resolvable"


def test_the_follow_up_store_refuses_the_confirmed_status(client):
    headers, case_id = _case(client, "fu13@example.com")
    _facts(client, headers, case_id)
    from app.services.followup_store import ServerFollowUpStore

    with client.app.state.session_factory() as session:
        case = session.get(Case, uuid.UUID(case_id))
        key = unwrap_data_key(case.data_key_enc, client.app.state.master_key)
        store = ServerFollowUpStore(session, case, case.user_id, key, client.clock.now)
        for status in ("resolved_consumer_confirmed", "closed", "deleted"):
            try:
                store.set_status(case_id, status)
            except ValueError:
                continue
            raise AssertionError(f"the follow-up store accepted {status}")
    assert _status(client, case_id) != CaseStatus.resolved_consumer_confirmed


def test_another_user_cannot_touch_the_case(client):
    _model(client, "rejected")
    headers, case_id = _case(client, "fu14@example.com")
    _facts(client, headers, case_id, entity_type="unknown")
    out = _post(client, headers, case_id, reply_text="Declined.")
    other = {"Authorization": f"Bearer {_signup(client, 'fu14-other@example.com')['access_token']}"}
    _step_up(client, other)
    assert client.post(f"/cases/{case_id}/follow-up", json={"reply_text": "hello"}, headers=other).status_code == 404
    assert client.get(f"/cases/{case_id}/follow-up", headers=other).status_code == 404
    assert client.post(f"/cases/{case_id}/follow-up/choose-route", json={"kind": "rbi_ombudsman"}, headers=other).status_code == 404
    assert client.post(f"/cases/{case_id}/confirm-resolved", headers=other).status_code == 404
    shown = client.get(f"/cases/{case_id}/follow-up", headers=headers).json()
    assert shown["pending_choice"] is not None and shown["case_status"] != "resolved_consumer_confirmed" and out["needs_choice"]
    for call in (
        client.post(f"/cases/{case_id}/follow-up", json={"reply_text": "x"}),
        client.get(f"/cases/{case_id}/follow-up"),
        client.post(f"/cases/{case_id}/confirm-resolved"),
    ):
        assert call.status_code == 401
    # a deadline of the owner's case cannot be fed in through another case of the same user
    second = client.post("/cases", headers=headers).json()["id"]
    reminder = out["reminder"]
    _advance(client, headers, "fu14@example.com", days=8)
    assert client.post(f"/cases/{second}/follow-up", json={"deadline_id": reminder["id"]}, headers=headers).status_code == 404


def test_bad_follow_up_bodies_are_refused(client):
    headers, case_id = _case(client, "fu15@example.com")
    for body in ({}, {"reply_text": "x", "deadline_id": str(uuid.uuid4())}, {"reply_text": "   "}):
        sent = client.post(f"/cases/{case_id}/follow-up", json=body, headers=headers)
        assert sent.status_code == 400 and sent.json()["error"]["code"] == "bad_follow_up"
    assert client.post(f"/cases/{case_id}/follow-up", json={"deadline_id": str(uuid.uuid4())}, headers=headers).status_code == 404


def test_a_closed_case_takes_no_follow_up(client):
    headers, case_id = _case(client, "fu16@example.com")
    _set_status(client, case_id, "closed")
    sent = client.post(f"/cases/{case_id}/follow-up", json={"reply_text": "hello"}, headers=headers)
    assert sent.status_code == 409 and sent.json()["error"]["code"] == "case_closed"
