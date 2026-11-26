"""Deleting a case destroys its key and leaves nothing readable in any store, including notifications."""

import io
import json

from sqlalchemy import text

from app.core.crypto import decode_master_key, open_text
from tests.integration.test_case_api import _case
from tests.integration.test_graph_run import _readable
from tests.integration.test_intake_api import ScriptedModel, _confirm_all, _extraction

NAME = "CANARYNAME9f3a"
AMOUNT = "7771"
RECEIPT = chr(10).join(["Flipkart", "Order ID: OD1234567890", "Order date: 20 Nov 2025", "Order total: Rs. 450"])


class ScriptedOCR:
    def read(self, image):
        return [RECEIPT]


def _notification_texts(client) -> str:
    key = decode_master_key(client.app.state.settings.master_key)
    with client.db_engine.connect() as conn:
        blobs = [bytes(r[0]) for r in conn.execute(text("SELECT payload_enc FROM notifications")).all()]
    return "\n".join(open_text(blob, key) for blob in blobs)


def test_a_fully_used_case_leaves_nothing_readable_after_deletion(client):
    headers, case_id = _case(client, "drill@example.com")
    base = f"/cases/{case_id}"
    # The narration says 7771; reconciliation will later disagree, so a notification quoting the amount exists.
    client.app.state.intake_llm = ScriptedModel(
        _extraction(company_name="Amazon", amount="9999", order_id="AB1", order_date="2026-11-20", desired_remedy="refund"),
        _extraction(amount=AMOUNT, company_name="Amazon", order_id="AB1", order_date="2026-11-20", desired_remedy="refund"),
    )
    client.app.state.evidence_ocr = ScriptedOCR()
    client.post(f"{base}/intake/messages", json={"text": f"My name is {NAME}. Amazon order AB1, {AMOUNT} rupees, refund please since 20 November"}, headers=headers)
    client.post(f"{base}/narration-done", headers=headers)
    client.post(f"{base}/intake/messages", json={"text": "marketplace"}, headers=headers)
    _confirm_all(client, headers, case_id)  # reconciliation disagrees (9999 against 7771) and notifies
    upload = client.post(f"{base}/evidence", headers=headers, files={"file": ("r.png", io.BytesIO(b"png"), "image/png")}, data={"type": "receipt"}).json()
    client.post(f"{base}/evidence/{upload['id']}/process", headers=headers)  # a second notification: the receipt says 450
    call = client.post("/calls", json={"case_id": case_id}, headers=headers)
    assert call.status_code == 201

    before = _notification_texts(client)
    assert AMOUNT in before or case_id in before  # the drill is only meaningful if there was something to remove

    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
    assert client.delete(base, headers=headers).status_code == 200

    after = _notification_texts(client)
    for needle in (case_id, AMOUNT, NAME, "OD1234567890"):
        assert needle not in after, needle
    readable = _readable(client.db_engine)
    for needle in (NAME, AMOUNT, "OD1234567890", "AB1"):
        assert needle not in readable, needle
    # Nothing under the case can be opened any more.
    assert client.get(f"{base}/facts", headers=headers).status_code in {404, 409, 410, 500} or client.get(f"{base}/facts", headers=headers).json().get("facts") in (None, [])
    with client.db_engine.connect() as conn:
        key_left = conn.execute(text("SELECT data_key_enc FROM cases WHERE id = :id"), {"id": case_id}).scalar()
        assert key_left is None
    assert json.dumps(client.get("/notifications", headers=headers).json()).count(case_id) == 0
