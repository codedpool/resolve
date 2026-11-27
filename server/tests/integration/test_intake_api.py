"""Text intake through the API with a scripted model. No vendor is called."""

import json

from sqlalchemy import text

from tests.integration.test_case_api import _case

FIELDS = (
    "company_name", "product", "order_id", "order_date", "amount", "currency", "payment_mode", "issue_summary",
    "company_said", "promised_date", "refund_reference", "desired_remedy", "provider_entity_type",
)


def _extraction(**stated):
    data = {name: {"value": "", "certainty": "not_stated", "original_phrase": "", "ambiguity_note": ""} for name in FIELDS}
    for name, value in stated.items():
        data[name] = {"value": value, "certainty": "stated", "original_phrase": value, "ambiguity_note": ""}
    return data


class ScriptedModel:
    """Stands in for Groq: structured calls pop scripted extractions, classify answers by role."""

    def __init__(self, *extractions, provider="marketplace"):
        self.extractions = list(extractions)
        self.provider = provider
        self.seen: list[str] = []

    def structured(self, role, prompt_id, variables, schema, mode="instruct"):
        self.seen.append(json.dumps(variables, ensure_ascii=False))
        return (self.extractions.pop(0) if self.extractions else _extraction()), {}

    def classify(self, role, prompt_id, text, labels):
        self.seen.append(text)
        if "done" in labels:
            return "more", 0.9, {}
        return self.provider, 0.9, {}

    def score(self, text):
        return 0.0


def _confirm_all(client, headers, case_id):
    facts = client.get(f"/cases/{case_id}/facts", headers=headers).json()["facts"]
    for fact in facts:
        assert client.post(f"/cases/{case_id}/facts/{fact['id']}/confirm", headers=headers).status_code == 200


def test_intake_from_story_to_ready_for_mandate(client):
    headers, case_id = _case(client, "intake@example.com")
    client.app.state.intake_llm = ScriptedModel(
        _extraction(company_name="Flipkart", amount="900"),
        _extraction(order_id="[NUM_1]"),
        _extraction(order_date="2026-11-20"),
        _extraction(desired_remedy="full refund"),
    )
    base = f"/cases/{case_id}"
    first = client.post(f"{base}/intake/messages", json={"text": "Flipkart se phone mangaya tha, 900 rupaye, refund nahi aaya aur support sunta nahi"}, headers=headers)
    assert first.status_code == 200 and first.json()["text"] is None and first.json()["phase"] == "narrating"
    done = client.post(f"{base}/narration-done", headers=headers).json()
    assert done["phase"] == "asking" and "order number" in done["text"]
    assert client.post(f"{base}/narration-done", headers=headers).json()["text"] is None  # second Done changes nothing
    reply = client.post(f"{base}/intake/messages", json={"text": "order id OD1234567890 hai"}, headers=headers).json()
    assert "date" in reply["text"]
    reply = client.post(f"{base}/intake/messages", json={"text": "20 November ko"}, headers=headers).json()
    assert "refund" in reply["text"]
    reply = client.post(f"{base}/intake/messages", json={"text": "poora refund chahiye"}, headers=headers).json()
    assert "shopping platform" in reply["text"]
    final = client.post(f"{base}/intake/messages", json={"text": "Flipkart app se"}, headers=headers).json()
    assert final["status"] == "confirming" and final["handoff_fields"] == []
    facts = {f["field"]: f for f in client.get(f"{base}/facts", headers=headers).json()["facts"]}
    assert facts["order_id"]["value"] == "OD1234567890"  # the stored fact has the real value, not the token
    assert facts["company_name"]["confirmation_state"] == "unconfirmed"
    _confirm_all(client, headers, case_id)
    assert client.get(base, headers=headers).json()["status"] == "ready_for_mandate"


def test_editing_a_confirmed_critical_fact_moves_the_case_back_to_confirming(client):
    headers, case_id = _case(client, "edit@example.com")
    client.app.state.intake_llm = ScriptedModel(
        _extraction(company_name="Amazon", amount="500", order_id="AB1", order_date="2026-11-20", desired_remedy="refund"),
    )
    base = f"/cases/{case_id}"
    client.post(f"{base}/intake/messages", json={"text": "Amazon order AB1, five hundred rupees, refund wanted since 20 November"}, headers=headers)
    client.post(f"{base}/narration-done", headers=headers)
    client.post(f"{base}/intake/messages", json={"text": "marketplace"}, headers=headers)
    _confirm_all(client, headers, case_id)
    assert client.get(base, headers=headers).json()["status"] == "ready_for_mandate"
    client.post(f"{base}/facts", json={"field": "amount", "value": "550"}, headers=headers)
    assert client.get(base, headers=headers).json()["status"] == "confirming"


def test_personal_strings_never_reach_the_model_and_are_not_stored_in_the_clear(client):
    headers, case_id = _case(client, "canary@example.com")
    model = ScriptedModel(_extraction(company_name="Swiggy"))
    client.app.state.intake_llm = model
    base = f"/cases/{case_id}"
    story = "Swiggy order was wrong. My card number 4111 1111 1111 1111 and OTP 482913 and phone 9876543210 were asked. address flat 4B, Rose Apartments, MG Road, pin code 560001"
    client.post(f"{base}/intake/messages", json={"text": story}, headers=headers)
    client.post(f"{base}/narration-done", headers=headers)
    sent = " ".join(model.seen)
    for canary in ("4111", "482913", "9876543210", "Rose Apartments", "560001"):
        assert canary not in sent, canary
    with client.db_engine.connect() as conn:
        rows = [bytes(r[0]) for r in conn.execute(text("SELECT body_enc FROM intake_states")).all()]
        rows += [bytes(r[0]) for r in conn.execute(text("SELECT body_enc FROM events")).all()]
    assert rows and all(b"4111" not in r and b"482913" not in r for r in rows)


def test_a_segment_that_cannot_be_redacted_is_withheld(client, monkeypatch):
    from app.privacy import redact as redact_module

    headers, case_id = _case(client, "withheld@example.com")
    model = ScriptedModel()
    client.app.state.intake_llm = model

    def boom(_text):
        raise ValueError("detector failed")

    monkeypatch.setattr(redact_module, "_find", boom)
    reply = client.post(f"/cases/{case_id}/intake/messages", json={"text": "mera OTP 123456"}, headers=headers).json()
    assert "type" in reply["text"] and model.seen == []


def test_silence_asks_once_and_never_confirms(client):
    headers, case_id = _case(client, "silence@example.com")
    client.app.state.intake_llm = ScriptedModel()
    base = f"/cases/{case_id}"
    assert client.post(f"{base}/intake/silence", headers=headers).json()["text"] is None
    client.post(f"{base}/intake/messages", json={"text": "I ordered a phone from a shop online and it never arrived despite many reminders"}, headers=headers)
    assert "Done" in client.post(f"{base}/intake/silence", headers=headers).json()["text"]
    assert client.post(f"{base}/intake/silence", headers=headers).json()["text"] is None
    assert client.get(f"/cases/{case_id}/facts", headers=headers).json()["facts"] == []


def test_another_user_cannot_use_the_intake(client):
    _, case_id = _case(client, "owner-intake@example.com")
    other, _ = _case(client, "other-intake@example.com")
    client.app.state.intake_llm = ScriptedModel()
    assert client.post(f"/cases/{case_id}/intake/messages", json={"text": "hi"}, headers=other).status_code == 404
    assert client.post(f"/cases/{case_id}/narration-done", headers=other).status_code == 404
