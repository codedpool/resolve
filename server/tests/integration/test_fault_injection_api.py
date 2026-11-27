"""Faults over REST: Groq rate limits during a call, the spending cap, a worker killed in the middle of a request, and the
once helper. The Groq client is the real one, on a mocked HTTP transport."""

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import Session

from app.adapters.cost import BudgetExceeded, CostMeter, shared_meter
from app.adapters.groq_llm import GroqClient
from app.config import Settings
from app.core.crypto import unwrap_data_key
from app.db.models import Approval, Call, CallMode, CallRole, Case, Deadline, Event, FollowUpState, Promise, SideEffect
from app.runtime.run_service import once, once_in_session
from app.services.followup_store import ServerFollowUpStore
from app.services.outreach_store import ServerApprovalPort, ServerOutreachStore
from resolve_workflows.fakes import FakeRetriever
from resolve_workflows.nodes import call_lines
from tests.integration.test_case_api import _case
from tests.integration.test_followup_api import _facts, _model, _post
from tests.integration.test_mandate_service import _setup

HOLD = call_lines.line("hold_wait", "en")


class WorkerKilled(BaseException):
    """Not caught by any `except Exception`: the process dies mid-request."""


def _ok(content, model="qwen/qwen3.8-27b"):
    return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def _groq(client, limit_drafts=0, retry_after="1", spend_per_call=0.0):
    """A Groq client on a mock transport that answers every kind of request the call makes. The first `limit_drafts` draft
    requests for a provider turn get a 429."""
    plan = {"limit": limit_drafts, "requests": [], "sleeps": []}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        plan["requests"].append(body["model"])
        if body["model"] == "meta-llama/llama-prompt-guard-2-86m":
            return _ok("0.0005", body["model"])
        fmt = body.get("response_format")
        if fmt:
            props = fmt["json_schema"]["schema"]["properties"]
            if "violation" in props:
                return _ok(json.dumps({"violation": False, "categories": [], "rationale": ""}), body["model"])
            return _ok(json.dumps({"label": "stall", "confidence": 0.9}), body["model"])
        said = json.loads(body["messages"][1]["content"])
        if "move" in said:
            if said.get("provider_said") and plan["limit"] > 0:
                plan["limit"] -= 1
                return httpx.Response(429, headers={"retry-after": retry_after}, json={"error": {"message": "rate limit"}})
            return _ok(said["move"]["suggested"], body["model"])
        return _ok("The call has ended. Nothing is confirmed until you confirm it.", body["model"])

    models = Settings().load_models()
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.groq.com/openai/v1")
    groq = GroqClient(models, CostMeter(20.0), http, sleeper=plan["sleeps"].append)
    client.app.state.intake_llm = groq
    client.app.state.retriever = FakeRetriever()
    return groq, plan


def _start(client, headers, case_id):
    made = client.post(f"/cases/{case_id}/outreach/calls", headers=headers)
    assert made.status_code == 201, made.text
    return made.json()


def _events(client):
    with client.app.state.session_factory() as session:
        return [e.kind for e in session.query(Event).all()]


# -- Groq 429 during a call ----------------------------------------------------------------------------------------------


def test_a_429_during_a_call_says_a_holding_line_waits_as_asked_and_then_answers(client):
    headers, case_id = _setup(client, "fi1@example.com")
    _groq_client, plan = _groq(client, limit_drafts=1, retry_after="2")
    call = _start(client, headers, case_id)
    assert HOLD not in call["sentences"]
    turn = client.post(f"/calls/{call['call_id']}/provider-turn", json={"text": "Please hold, we are checking."}, headers=headers)
    assert turn.status_code == 200, turn.text
    sentences = turn.json()["sentences"]
    assert sentences[0] == HOLD and len(sentences) > 1 and turn.json()["ended"] is False  # a holding line, then the real reply
    assert plan["sleeps"] == [2.0]  # Retry-After was honoured
    kinds = _events(client)
    assert "rate_limited_hold" in kinds and "guard_blocked" not in kinds


def test_a_429_that_does_not_clear_never_leaves_the_call_silent_or_crashes_it(client):
    headers, case_id = _setup(client, "fi2@example.com")
    _groq_client, plan = _groq(client, limit_drafts=99, retry_after="1")
    call = _start(client, headers, case_id)
    turn = client.post(f"/calls/{call['call_id']}/provider-turn", json={"text": "Please hold, we are checking."}, headers=headers)
    assert turn.status_code == 200, turn.text
    sentences = turn.json()["sentences"]
    assert sentences[0] == HOLD and len(sentences) >= 2  # the holding line, then the code's own wording once the retries gave up
    assert plan["sleeps"] == [1.0, 1.0]  # backed off twice, then stopped retrying
    assert turn.json()["ended"] is False


def test_a_daily_limit_is_not_waited_out_inside_the_call(client):
    headers, case_id = _setup(client, "fi3@example.com")
    _groq_client, plan = _groq(client, limit_drafts=99, retry_after="3600")
    call = _start(client, headers, case_id)
    turn = client.post(f"/calls/{call['call_id']}/provider-turn", json={"text": "Please hold, we are checking."}, headers=headers)
    assert turn.status_code == 200 and turn.json()["sentences"] and plan["sleeps"] == []


# -- the spending cap ----------------------------------------------------------------------------------------------------


def test_a_used_up_budget_stops_the_call_with_a_clear_message_and_a_summary_for_the_owner(client):
    headers, case_id = _setup(client, "fi4@example.com")
    groq, _plan = _groq(client)
    call = _start(client, headers, case_id)
    groq.meter.spent_usd = groq.meter.limit_usd  # the cap is reached between two turns
    turn = client.post(f"/calls/{call['call_id']}/provider-turn", json={"text": "Please hold, we are checking."}, headers=headers)
    assert turn.status_code == 200, turn.text
    body = turn.json()
    assert body["ended"] is True and body["end_reason"] == "budget_exhausted" and body["approval_id"]
    assert body["sentences"] == [call_lines.line("end_budget", "en")]
    approvals = client.get(f"/approvals?case={case_id}", headers=headers).json()["approvals"]
    summary = [a for a in approvals if a["kind"] == "summary"]
    assert len(summary) == 1 and "usage limit" in json.loads(summary[0]["payload"])["summary"]
    assert "call_ended" in _events(client)
    again = client.post(f"/calls/{call['call_id']}/provider-turn", json={"text": "Hello?"}, headers=headers)
    assert again.status_code == 200 and again.json()["sentences"] == [] and again.json()["ended"] is True


def test_a_used_up_budget_before_a_call_is_a_clear_402_and_nothing_is_made(client):
    headers, case_id = _setup(client, "fi5@example.com")
    groq, _plan = _groq(client)
    groq.meter.spent_usd = groq.meter.limit_usd
    refused = client.post(f"/cases/{case_id}/outreach/calls", headers=headers)
    assert refused.status_code == 402 and refused.json()["error"]["code"] == "budget_exceeded"
    assert "used up" in refused.json()["error"]["message"]
    with client.app.state.session_factory() as session:
        assert session.query(Call).count() == 0 and session.query(Approval).count() == 0


def test_a_used_up_budget_does_not_stop_a_follow_up_reply_from_being_read(client):
    headers, case_id = _case(client, "fi6@example.com")
    _facts(client, headers, case_id)
    groq, _plan = _groq(client)
    groq.meter.spent_usd = groq.meter.limit_usd
    out = _post(client, headers, case_id, reply_text="Your request is declined as it is outside the return window.")
    assert out["label"] == "rejected" and out["understood"]["degraded"] is True


def test_chat_vision_and_speech_share_one_budget(client):
    from app.adapters.factory import get_llm
    from app.services.evidence_store import _vision

    request = SimpleNamespace(app=client.app)
    groq = get_llm(request)  # built by the app itself, not a test double
    assert groq.meter is shared_meter(client.app.state) and _vision(request).meter is groq.meter
    groq.meter.spent_usd = groq.meter.limit_usd
    with pytest.raises(BudgetExceeded):
        _vision(request).meter.ensure_open()


# -- a worker killed in the middle of a request ------------------------------------------------------------------------------


def test_a_call_killed_while_closing_leaves_nothing_half_made_and_the_retry_makes_each_record_once(client, monkeypatch):
    from tests.integration.test_outreach_api import ModelPort

    client.app.state.intake_llm = ModelPort()
    client.app.state.retriever = FakeRetriever()
    headers, case_id = _setup(client, "fi7@example.com")
    call = client.post(f"/cases/{case_id}/outreach/calls", headers=headers).json()
    day = client.clock.now() + __import__("datetime").timedelta(days=10)
    sent = client.post(f"/calls/{call['call_id']}/provider-turn", json={"text": f"I will credit the full refund of 4999 rupees by {day.day} {day.strftime('%B')}."}, headers=headers)
    assert sent.status_code == 200
    real = ServerOutreachStore.save_summary
    armed = {"on": True}

    def killed(self, case_id, call_id, summary):
        if armed["on"]:
            armed["on"] = False
            raise WorkerKilled()  # after the promise row was written in this request
        return real(self, case_id, call_id, summary)

    with client.app.state.session_factory() as session:
        keys_before = session.query(SideEffect).count()  # the offer made by the first turn
    monkeypatch.setattr(ServerOutreachStore, "save_summary", killed)
    with pytest.raises(WorkerKilled):
        client.post(f"/calls/{call['call_id']}/provider-turn", json={"text": "The reference is ZM-REF-558201."}, headers=headers)
    with client.app.state.session_factory() as session:
        assert session.query(Promise).count() == 0 and session.query(Approval).filter(Approval.kind == "summary").count() == 0
        assert session.query(SideEffect).count() == keys_before  # the killed request's keys went back with its rows
    retry = client.post(f"/calls/{call['call_id']}/provider-turn", json={"text": "The reference is ZM-REF-558201."}, headers=headers)
    assert retry.status_code == 200 and retry.json()["end_reason"] == "promise_secured" and retry.json()["approval_id"]
    again = client.post(f"/calls/{call['call_id']}/end", headers=headers)
    assert again.status_code == 200
    with client.app.state.session_factory() as session:
        assert session.query(Promise).count() == 1
        assert session.query(Approval).filter(Approval.kind == "summary").count() == 1
        assert [e.kind for e in session.query(Event).all()].count("call_summary") == 1


def test_a_follow_up_killed_while_the_approval_is_made_leaves_nothing_and_the_retry_makes_one_of_each(client, monkeypatch):
    _model(client, "rejected")
    headers, case_id = _case(client, "fi8@example.com")
    _facts(client, headers, case_id)
    real = ServerApprovalPort.create
    armed = {"on": True}

    def killed(self, case_id, kind, payload, key):
        made = real(self, case_id, kind, payload, key)
        if armed["on"]:
            armed["on"] = False
            raise WorkerKilled()  # the approval row exists in this request's transaction, the worker dies right after
        return made

    monkeypatch.setattr(ServerApprovalPort, "create", killed)
    with pytest.raises(WorkerKilled):
        client.post(f"/cases/{case_id}/follow-up", json={"reply_text": "Declined."}, headers=headers)
    with client.app.state.session_factory() as session:
        assert session.query(Approval).count() == 0 and session.query(Deadline).count() == 0 and session.query(FollowUpState).count() == 0
        assert "follow_up" not in [e.kind for e in session.query(Event).all()]
    out = _post(client, headers, case_id, reply_text="Declined.")
    assert out["approval_id"] and out["reminder"] and out["case_status"] == "awaiting_consumer"
    again = _post(client, headers, case_id, reply_text="Declined.")
    assert again["duplicate"] is True
    with client.app.state.session_factory() as session:
        assert session.query(Approval).count() == 1 and session.query(Deadline).count() == 1
        assert [e.kind for e in session.query(Event).all()].count("follow_up") == 1


def test_a_follow_up_killed_while_the_reminder_is_scheduled_resumes_cleanly(client, monkeypatch):
    _model(client, "partial")
    headers, case_id = _case(client, "fi9@example.com")
    _facts(client, headers, case_id)
    real = ServerFollowUpStore.schedule_reminder
    armed = {"on": True}

    def killed(self, case_id, due_at, kind, key):
        if armed["on"]:
            armed["on"] = False
            real(self, case_id, due_at, kind, key)
            raise WorkerKilled()
        return real(self, case_id, due_at, kind, key)

    monkeypatch.setattr(ServerFollowUpStore, "schedule_reminder", killed)
    with pytest.raises(WorkerKilled):
        client.post(f"/cases/{case_id}/follow-up", json={"reply_text": "A voucher instead."}, headers=headers)
    out = _post(client, headers, case_id, reply_text="A voucher instead.")
    assert out["action"] == "review_offer" and out["approval_id"]
    with client.app.state.session_factory() as session:
        assert session.query(Approval).count() == 1 and session.query(Deadline).count() == 1


# -- the once helper ---------------------------------------------------------------------------------------------------


def test_once_commits_its_key_first_so_an_effect_that_fails_is_lost_and_once_in_session_is_not(client):
    """`once` suits an effect that cannot be undone and must never repeat; it loses an effect that raised. For an effect
    that writes through the request's own session the key and the effect must stand or fall together."""
    factory = client.app.state.session_factory
    lost: list[str] = []

    def explode():
        raise RuntimeError("worker killed before the effect finished")

    with pytest.raises(RuntimeError):
        once(factory, "fi-key-1", explode)
    assert once(factory, "fi-key-1", lambda: lost.append("ran")) is False and lost == []  # the effect never happened, and never will

    kept: list[str] = []
    with Session(client.db_engine) as session:
        with pytest.raises(RuntimeError):
            once_in_session(session, "fi-key-2", explode)
        session.rollback()
        assert once_in_session(session, "fi-key-2", lambda: kept.append("ran")) is True  # the failed effect is run again
        assert once_in_session(session, "fi-key-2", lambda: kept.append("again")) is False  # a finished one is not
        session.commit()
    assert kept == ["ran"]


def test_a_rolled_back_request_takes_the_effect_keys_with_it(client):
    with Session(client.db_engine) as session:
        assert once_in_session(session, "fi-key-3", lambda: None) is True
        session.rollback()
        assert session.get(SideEffect, "fi-key-3") is None
        assert once_in_session(session, "fi-key-3", lambda: None) is True
        session.commit()
    with Session(client.db_engine) as session:
        assert session.get(SideEffect, "fi-key-3") is not None


def test_the_outreach_store_makes_a_promise_and_an_offer_once_per_key(client):
    headers, case_id = _setup(client, "fi10@example.com")
    with client.app.state.session_factory() as session:
        case = session.get(Case, uuid.UUID(case_id))
        key = unwrap_data_key(case.data_key_enc, client.app.state.master_key)
        call = Call(case_id=case.id, role=CallRole.provider_human, mode=CallMode.text, simulated=True)
        session.add(call)
        session.flush()
        store = ServerOutreachStore(session, case, case.user_id, call, key, client.clock.now)
        day = (client.clock.now() + __import__("datetime").timedelta(days=5)).date().isoformat()
        first = store.save_promise(case_id, str(call.id), "provider", "refund", day, "ZM-REF-558201", "promise:x:0")
        second = store.save_promise(case_id, str(call.id), "provider", "refund", day, "ZM-REF-558201", "promise:x:0")
        store.record_offer(case_id, str(call.id), {"kind": "partial", "amount": 2000}, "offer:x:1")
        store.record_offer(case_id, str(call.id), {"kind": "partial", "amount": 2000}, "offer:x:1")
        session.flush()
        assert session.query(Promise).count() == 1 and first != "" and second == "promise:x:0"
        assert [e.kind for e in session.query(Event).all()].count("offer_recorded") == 1
        assert [e.kind for e in session.query(Event).all()].count("promise_recorded") == 1
        session.rollback()
