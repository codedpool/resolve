"""The output guard against real case rows: canaries in every sensitive field, events on the timeline."""

import json
import uuid

import yaml

from app.config import SERVER_ROOT
from app.core.crypto import open_text, unwrap_data_key
from app.db.models import Case, Event
from app.services.case_store import ServerCaseStore
from app.services.output_guard import ServerOutputGuard
from resolve_workflows.guards.output_guard import HOLDING
from tests.integration.test_mandate_service import FACTS, FIXTURE, _setup

SUITE = yaml.safe_load((SERVER_ROOT.parent / "workflows" / "evals" / "datasets" / "safety_suite.yaml").read_text(encoding="utf-8"))


class DownLLM:
    def structured(self, *args, **kwargs):
        raise RuntimeError("vendor down")


class QuietLLM:
    def __init__(self):
        self.calls = []

    def structured(self, role, prompt_text, variables, schema, mode="instruct"):
        self.calls.append((role, variables))
        return {"violation": False, "categories": [], "rationale": ""}, {}


def _guard(client, case_id, session, llm):
    case = session.get(Case, uuid.UUID(case_id))
    key = unwrap_data_key(case.data_key_enc, client.app.state.master_key)
    store = ServerCaseStore(session, case, key, client.app.state.clock.now)
    return ServerOutputGuard(store, case_id, 1, llm), case, key


def _events(session, case, key, kinds):
    rows = session.query(Event).filter(Event.case_id == case.id, Event.kind.in_(kinds)).all()
    return [(r.kind, json.loads(open_text(r.body_enc, key))) for r in rows]


def test_every_suite_reply_is_judged_against_real_rows_and_logged_without_the_text(client):
    _, case_id = _setup(client, "og1@example.com")
    with client.app.state.session_factory() as session:
        guard, case, key = _guard(client, case_id, session, QuietLLM())
        for case_row in SUITE["cases"]:
            guard.hear(case_row["provider_turn"])
            for reply in case_row["bad_replies"]:
                assert guard.check(reply, case_row["provider_turn"]).blocked, (case_row["id"], reply)
            for reply in case_row["safe_replies"]:
                assert not guard.check(reply, case_row["provider_turn"]).blocked, (case_row["id"], reply)
            guard.heard.clear()
        session.flush()
        blocked = _events(session, case, key, ["guard_blocked"])
        assert len(blocked) == sum(len(c["bad_replies"]) for c in SUITE["cases"])
        dump = json.dumps([{k: v for k, v in b.items() if k != "text_sha"} for _, b in blocked])
        for value in FIXTURE["canaries"].values():
            assert str(value) not in dump


def test_a_blocked_sentence_is_replaced_and_a_vendor_outage_degrades_and_is_logged(client):
    _, case_id = _setup(client, "og2@example.com")
    with client.app.state.session_factory() as session:
        guard, case, key = _guard(client, case_id, session, DownLLM())
        spoken = guard.speak("Her phone number is 9871234560.")
        assert spoken.text == HOLDING["en"] and spoken.verdict.blocked
        fine = guard.speak("Could you give me the ticket number?")
        assert fine.text.startswith("Could you") and fine.verdict.degraded
        session.flush()
        kinds = [k for k, _ in _events(session, case, key, ["guard_blocked", "guard_degraded"])]
        assert kinds.count("guard_blocked") == 1 and kinds.count("guard_degraded") == 1


def test_the_model_sees_the_policy_but_never_a_withheld_value(client):
    _, case_id = _setup(client, "og3@example.com")
    llm = QuietLLM()
    with client.app.state.session_factory() as session:
        guard, _, _ = _guard(client, case_id, session, llm)
        guard.check("I am calling about my order.")
    assert llm.calls and llm.calls[0][0] == "guard_policy"
    dump = json.dumps(llm.calls[0][1], ensure_ascii=False)
    for field, value in FACTS.items():
        if field not in FIXTURE["disclosure_list"] and field != "company_name":
            assert value not in dump, field
    assert "og3@example.com" not in dump


def test_the_account_email_is_a_withheld_value(client):
    _, case_id = _setup(client, "og4@example.com")
    with client.app.state.session_factory() as session:
        case = session.get(Case, uuid.UUID(case_id))
        key = unwrap_data_key(case.data_key_enc, client.app.state.master_key)
        store = ServerCaseStore(session, case, key, client.app.state.clock.now, account_email="og4@example.com")
        guard = ServerOutputGuard(store, case_id, 1, None)
        assert guard.check("You can mail the customer at og4@example.com.").blocked
