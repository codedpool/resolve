"""Approval graph pauses, survives a killed worker, and keeps personal text out of checkpoints."""

import io

from sqlalchemy import text

from tests.integration.test_case_api import _case

CANARIES = ("CANARYNAME9f3a", "9001110002", "CANARYROAD42")


def _readable(engine) -> str:
    chunks: list[str] = []
    with engine.connect() as conn:
        columns = conn.execute(
            text(
                """
                SELECT table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema IN ('public', 'checkpoints')
                """
            )
        ).all()
        for schema, table, column, data_type in columns:
            quoted = f'"{schema}"."{table}"'
            rows = conn.execute(text(f'SELECT "{column}" FROM {quoted}')).all()
            for (value,) in rows:
                if value is None:
                    continue
                if data_type == "bytea":
                    raw = bytes(value)
                    chunks.append(raw.decode("utf-8", "ignore"))
                    chunks.append(raw.decode("latin-1", "ignore"))
                else:
                    chunks.append(str(value))
    return "\n".join(chunks)


def _assert_canaries_absent(engine, objects_root):
    readable = _readable(engine)
    for canary in CANARIES:
        assert canary not in readable
    if objects_root.exists():
        for path in objects_root.rglob("*"):
            if path.is_file():
                blob = path.read_bytes().decode("latin-1", "ignore")
                for canary in CANARIES:
                    assert canary not in blob


def test_approval_run_pauses_and_a_killed_worker_does_not_repeat_the_effect(client):
    headers, case_id = _case(client, "graph@example.com")
    created = client.post(
        f"/cases/{case_id}/runs",
        json={"graph": "approval"},
        headers={**headers, "Idempotency-Key": "approval-1"},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    runner = client.app.state.runner
    runner.wait(run_id)
    paused = client.get(f"/runs/{run_id}", headers=headers).json()
    assert paused["status"] == "paused_for_approval"
    detail = client.get(f"/cases/{case_id}", headers=headers).json()
    approval_id = detail["open_approvals"][0]["id"]

    runner.crash = True
    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
    decided = client.post(f"/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=headers)
    assert decided.status_code == 200, decided.text
    runner.wait(run_id)
    assert runner.effects == [case_id]

    runner.crash = False
    runner.resume(run_id, "approve")
    runner.wait(run_id)
    assert runner.effects == [case_id]
    assert client.get(f"/runs/{run_id}", headers=headers).json()["status"] == "completed"


def test_checkpoints_and_deletion_keep_canaries_unreadable(client):
    headers, case_id = _case(client, "canary@example.com")
    client.post(
        f"/cases/{case_id}/facts",
        json={"field": "consumer_name", "value": CANARIES[0], "phrase": CANARIES[2]},
        headers=headers,
    )
    client.post(
        f"/cases/{case_id}/evidence",
        headers=headers,
        files={"file": ("note.txt", io.BytesIO(CANARIES[1].encode()), "text/plain")},
    )
    created = client.post(
        f"/cases/{case_id}/runs",
        json={"graph": "approval"},
        headers={**headers, "Idempotency-Key": "approval-canary"},
    )
    run_id = created.json()["run_id"]
    client.app.state.runner.wait(run_id)
    _assert_canaries_absent(client.db_engine, client.app.state.objects.root)

    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
    assert client.delete(f"/cases/{case_id}", headers=headers).status_code == 200
    blocked = client.get(f"/cases/{case_id}", headers=headers)
    assert blocked.status_code == 410
    assert blocked.json()["error"]["code"] == "key_destroyed"
    _assert_canaries_absent(client.db_engine, client.app.state.objects.root)
