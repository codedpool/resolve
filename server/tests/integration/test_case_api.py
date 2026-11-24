"""Case API: evidence, mandates, approvals, runs, and notifications."""

import io

from fastapi.testclient import TestClient

from tests.integration.test_auth import _signup


def _case(client: TestClient, email: str) -> tuple[dict, str]:
    tokens = _signup(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    case_id = client.post("/cases", headers=headers).json()["id"]
    return headers, case_id


def test_evidence_upload_and_vision_request_does_not_decide(client):
    headers, case_id = _case(client, "ev@example.com")
    uploaded = client.post(
        f"/cases/{case_id}/evidence",
        headers=headers,
        files={"file": ("receipt.txt", io.BytesIO(b"order 12"), "text/plain")},
        data={"type": "receipt"},
    )
    assert uploaded.status_code == 201, uploaded.text
    evidence_id = uploaded.json()["id"]
    asked = client.post(f"/cases/{case_id}/evidence/{evidence_id}/approve-vision", headers=headers)
    assert asked.status_code == 201
    assert asked.json()["status"] == "pending"
    assert asked.json()["sent_to_vision"] is False
    detail = client.get(f"/cases/{case_id}", headers=headers).json()
    assert detail["open_approvals"][0]["kind"] == "send_image_to_llm"
    assert any(item["kind"] == "evidence_uploaded" for item in detail["timeline"])


def test_mandate_version_and_expiry(client):
    headers, case_id = _case(client, "man@example.com")
    denied = client.post(f"/cases/{case_id}/mandate", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "step_up_required"
    assert client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers).status_code == 200
    first = client.post(f"/cases/{case_id}/mandate", json={"expires_in_days": 7}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["mandate"]["version"] == 1
    assert first.json()["mandate"]["active"] is True
    second = client.post(f"/cases/{case_id}/mandate", json={"expires_in_days": 0}, headers=headers)
    assert second.json()["mandate"]["version"] == 2
    assert second.json()["mandate"]["active"] is False


def test_approval_decision_needs_step_up_and_notifies(client):
    headers, case_id = _case(client, "ap@example.com")
    uploaded = client.post(
        f"/cases/{case_id}/evidence",
        headers=headers,
        files={"file": ("receipt.txt", io.BytesIO(b"order 12"), "text/plain")},
    )
    evidence_id = uploaded.json()["id"]
    approval_id = client.post(f"/cases/{case_id}/evidence/{evidence_id}/approve-vision", headers=headers).json()["approval_id"]
    blocked = client.post(f"/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=headers)
    assert blocked.status_code == 403
    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
    decided = client.post(f"/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=headers)
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    listed = client.get(f"/cases/{case_id}/evidence", headers=headers).json()["evidence"][0]
    assert listed["sent_to_vision"] is True
    notes = client.get("/notifications", headers=headers).json()["notifications"]
    assert notes[0]["payload"]["decision"] == "approve"
    marked = client.post(f"/notifications/{notes[0]['id']}/read", headers=headers)
    assert marked.status_code == 200
    assert marked.json()["read_at"]


def test_run_creation_is_idempotent(client):
    headers, case_id = _case(client, "run@example.com")
    missing = client.post(f"/cases/{case_id}/runs", json={"graph": "intake"}, headers=headers)
    assert missing.status_code == 400
    created = client.post(
        f"/cases/{case_id}/runs",
        json={"graph": "intake"},
        headers={**headers, "Idempotency-Key": "same-key"},
    )
    again = client.post(
        f"/cases/{case_id}/runs",
        json={"graph": "intake"},
        headers={**headers, "Idempotency-Key": "same-key"},
    )
    assert created.status_code == 201
    assert again.json()["run_id"] == created.json()["run_id"]
    assert again.json()["replayed"] is True
    stream = client.get(f"/runs/{created.json()['run_id']}/events", headers=headers)
    assert stream.status_code == 200
    assert "queued" in stream.text


def test_other_user_is_rejected_across_case_endpoints(client):
    headers, case_id = _case(client, "owner@example.com")
    other = {"Authorization": f"Bearer {_signup(client, 'other@example.com')['access_token']}"}
    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=other)
    assert client.get(f"/cases/{case_id}/facts", headers=other).status_code == 404
    assert client.get(f"/cases/{case_id}/evidence", headers=other).status_code == 404
    assert client.post(f"/cases/{case_id}/mandate", json={}, headers=other).status_code == 404
    assert client.get(f"/approvals?case={case_id}", headers=other).status_code == 404
    assert client.post(f"/cases/{case_id}/runs", json={"graph": "intake"}, headers={**other, "Idempotency-Key": "x"}).status_code == 404
    note_id = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/notifications/{note_id}/read", headers=other).status_code == 404
    assert client.get(f"/cases/{case_id}", headers=headers).status_code == 200
