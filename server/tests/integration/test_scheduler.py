"""Deadline notifications fire once. A failed outbox send is retried later, not twice."""

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.crypto import decode_master_key
from app.db.models import Case, Deadline, DeadlineStatus, OutboxJob
from app.services.outbox import deliver_in_app, drain, enqueue
from app.services.scheduler import fire_due_deadlines
from tests.integration.test_case_api import _case


def _session(client):
    return Session(client.db_engine)


def test_deadline_notifies_exactly_once(client):
    headers, case_id = _case(client, "due@example.com")
    master = decode_master_key(client.app.state.settings.master_key)
    with _session(client) as session:
        session.add(
            Deadline(
                case_id=uuid.UUID(case_id),
                due_at=client.clock.now(),
                kind="followup",
                status=DeadlineStatus.scheduled,
            )
        )
        session.commit()
        assert fire_due_deadlines(session, client.clock, master) == 1
        assert fire_due_deadlines(session, client.clock, master) == 0
        assert drain(session, client.clock, master, deliver_in_app) == 1
        assert drain(session, client.clock, master, deliver_in_app) == 0
        session.commit()
    notes = client.get("/notifications", headers=headers).json()["notifications"]
    assert len(notes) == 1
    assert notes[0]["kind"] == "deadline"
    assert notes[0]["payload"]["deadline_kind"] == "followup"


def test_outbox_retries_then_sends_once(client):
    _headers, case_id = _case(client, "box@example.com")
    master = decode_master_key(client.app.state.settings.master_key)
    calls = {"n": 0}

    def flaky(session, job, master_key, clock):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("downstream down")
        deliver_in_app(session, job, master_key, clock)

    with _session(client) as session:
        case_user = session.get(Case, uuid.UUID(case_id))
        first, fresh = enqueue(
            session,
            key="promise:1",
            kind="deadline",
            payload={"deadline_id": str(uuid.uuid4()), "deadline_kind": "promise"},
            master_key=master,
            when=client.clock.now(),
            user_id=case_user.user_id,
        )
        again, again_fresh = enqueue(
            session,
            key="promise:1",
            kind="deadline",
            payload={"deadline_id": str(uuid.uuid4()), "deadline_kind": "promise"},
            master_key=master,
            when=client.clock.now(),
            user_id=case_user.user_id,
        )
        assert fresh is True
        assert again_fresh is False
        assert again.id == first.id
        assert drain(session, client.clock, master, flaky) == 0
        job = session.get(OutboxJob, first.id)
        assert job.status == "failed"
        assert job.attempts == 1
        assert drain(session, client.clock, master, flaky) == 0
        client.clock.moment = client.clock.now() + timedelta(seconds=2)
        assert drain(session, client.clock, master, flaky) == 1
        assert drain(session, client.clock, master, flaky) == 0
        session.commit()
    assert calls["n"] == 2
