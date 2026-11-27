"""Reconciliation through the API with a scripted model."""

from tests.integration.test_case_api import _case
from tests.integration.test_intake_api import ScriptedModel, _confirm_all, _extraction

FULL = dict(company_name="Amazon", order_id="AB1", order_date="2026-11-20", desired_remedy="refund")


def _story(client, email, first_amount, later_amount):
    headers, case_id = _case(client, email)
    client.app.state.intake_llm = ScriptedModel(
        _extraction(amount=first_amount, **FULL),  # extraction at Done
        _extraction(amount=later_amount, **FULL),  # extraction by reconciliation
    )
    base = f"/cases/{case_id}"
    client.post(f"{base}/intake/messages", json={"text": "Amazon order AB1 about nine hundred rupees refund please since 20 November"}, headers=headers)
    client.post(f"{base}/narration-done", headers=headers)
    client.post(f"{base}/intake/messages", json={"text": "marketplace"}, headers=headers)
    return headers, base


def test_matching_values_unlock_the_case(client):
    headers, base = _story(client, "rec1@example.com", "900", "900")
    _confirm_all(client, headers, base.split("/")[-1])
    assert client.get(base, headers=headers).json()["status"] == "ready_for_mandate"
    assert client.post(f"{base}/reconcile", headers=headers).json()["open"] == []


def test_a_disagreement_keeps_the_case_in_confirming_with_one_question(client):
    headers, base = _story(client, "rec2@example.com", "9000", "900")
    _confirm_all(client, headers, base.split("/")[-1])
    detail = client.get(base, headers=headers).json()
    assert detail["status"] == "confirming"
    open_items = client.post(f"{base}/reconcile", headers=headers).json()["open"]
    assert open_items[0]["field"] == "amount" and "Which is right?" in open_items[0]["question"]
    notes = [n for n in client.get("/notifications", headers=headers).json()["notifications"] if n["kind"] == "reconcile_question"]
    assert len(notes) == 1
    client.post(f"{base}/reconcile", headers=headers)  # asking again never repeats the notification
    notes = [n for n in client.get("/notifications", headers=headers).json()["notifications"] if n["kind"] == "reconcile_question"]
    assert len(notes) == 1


def test_mandate_stays_locked_until_the_disagreement_is_settled(client):
    headers, base = _story(client, "rec3@example.com", "9000", "900")
    _confirm_all(client, headers, base.split("/")[-1])
    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
    blocked = client.post(f"{base}/mandate", json={}, headers=headers)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "confirm_details_first"
    fixed = client.post(f"{base}/facts", json={"field": "amount", "value": "900"}, headers=headers).json()
    client.post(f"{base}/facts/{fixed['id']}/confirm", headers=headers)
    assert client.get(base, headers=headers).json()["status"] == "ready_for_mandate"
    assert client.post(f"{base}/mandate", json={}, headers=headers).status_code == 200


def test_a_reconciliation_failure_does_not_trap_the_consumer(client):
    headers, base = _story(client, "rec4@example.com", "900", "900")

    class Down(ScriptedModel):
        def structured(self, *args, **kwargs):
            raise RuntimeError("vendor down")

    client.app.state.intake_llm = Down()
    _confirm_all(client, headers, base.split("/")[-1])
    assert client.get(base, headers=headers).json()["status"] == "ready_for_mandate"
