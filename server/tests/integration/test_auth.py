import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Fact


def _signup(client: TestClient, email: str, password: str = "correct-horse") -> dict:
    response = client.post("/auth/signup", json={"email": email, "password": password, "language": "en"})
    assert response.status_code == 201, response.text
    return response.json()


def test_wrong_password_then_rate_limit(client):
    _signup(client, "a@example.com")
    for _ in range(5):
        response = client.post("/auth/login", json={"email": "a@example.com", "password": "nope-nope"})
        assert response.status_code == 401
    blocked = client.post("/auth/login", json={"email": "a@example.com", "password": "nope-nope"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


def test_access_token_expires(client):
    tokens = _signup(client, "b@example.com")
    client.clock.advance(minutes=16)
    response = client.get("/cases", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 401


def test_step_up_window(client):
    tokens = _signup(client, "c@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    started = client.clock.now()
    assert client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers).status_code == 200
    case_id = client.post("/cases", headers=headers).json()["id"]
    client.clock.moment = started + timedelta(minutes=9, seconds=59)
    assert client.delete(f"/cases/{case_id}", headers=headers).status_code == 200

    other = _signup(client, "c2@example.com")
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    created = client.post("/cases", headers=other_headers)
    granted = client.clock.now()
    assert client.post("/auth/step-up", json={"password": "correct-horse"}, headers=other_headers).status_code == 200
    client.clock.moment = granted + timedelta(minutes=10, seconds=1)
    denied = client.delete(f"/cases/{created.json()['id']}", headers=other_headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "step_up_required"


def test_user_cannot_read_another_users_case(client):
    first = _signup(client, "d@example.com")
    second = _signup(client, "e@example.com")
    created = client.post("/cases", headers={"Authorization": f"Bearer {first['access_token']}"})
    case_id = created.json()["id"]
    hidden = client.get(f"/cases/{case_id}", headers={"Authorization": f"Bearer {second['access_token']}"})
    assert hidden.status_code == 404


def test_fact_correction_invalidates_confirmation_and_keeps_approximate_text(client):
    tokens = _signup(client, "f@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    case_id = client.post("/cases", headers=headers).json()["id"]
    created = client.post(
        f"/cases/{case_id}/facts",
        json={"field": "amount", "value": "around 1200", "certainty": "approximate", "phrase": "around 1200"},
        headers=headers,
    )
    fact_id = created.json()["id"]
    confirmed = client.post(f"/cases/{case_id}/facts/{fact_id}/confirm", headers=headers)
    assert confirmed.json()["confirmed_version"] == 1
    replacement = client.post(
        f"/cases/{case_id}/facts",
        json={"field": "amount", "value": "1250", "certainty": "stated"},
        headers=headers,
    )
    assert replacement.json()["version"] == 2
    assert replacement.json()["confirmation_state"] == "unconfirmed"
    detail = client.get(f"/cases/{case_id}", headers=headers).json()
    amounts = [item for item in detail["facts"] if item["field"] == "amount"]
    assert len(amounts) == 1
    assert amounts[0]["value"] == "1250"
    assert amounts[0]["confirmation_state"] == "unconfirmed"


def test_two_cases_use_different_keys_and_destroy_blocks_reads(client):
    tokens = _signup(client, "g@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    first = client.post("/cases", headers=headers).json()["id"]
    second = client.post("/cases", headers=headers).json()["id"]
    client.post(f"/cases/{first}/facts", json={"field": "product", "value": "phone"}, headers=headers)
    client.post(f"/cases/{second}/facts", json={"field": "product", "value": "phone"}, headers=headers)
    from sqlalchemy.orm import Session

    with Session(client.db_engine) as session:
        rows = session.query(Fact).filter(Fact.field == "product").all()
        assert len(rows) == 2
        assert rows[0].value_enc != rows[1].value_enc
    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
    assert client.delete(f"/cases/{first}", headers=headers).status_code == 200
    blocked = client.get(f"/cases/{first}", headers=headers)
    assert blocked.status_code == 410
    assert blocked.json()["error"]["code"] == "key_destroyed"
    still = client.get(f"/cases/{second}", headers=headers)
    assert still.status_code == 200
    assert still.json()["facts"][0]["value"] == "phone"
