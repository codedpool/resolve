"""Nothing personal and no key material reaches the logs during a full text and evidence run."""

import io
import logging

from tests.integration.test_case_api import _case
from tests.integration.test_intake_api import ScriptedModel, _extraction

CANARIES = ("CANARYNAME9f3a", "9876543210", "482913", "4111 1111 1111 1111", "Rose Apartments", "560001", "OD1234567890")
RECEIPT = chr(10).join(["Flipkart", "Order ID: OD1234567890", "Order date: 20 Nov 2025", "Order total: Rs. 450"])


class ScriptedOCR:
    def read(self, image):
        return [RECEIPT]


def test_logs_from_a_full_run_hold_no_canaries_or_keys(client, caplog):
    settings = client.app.state.settings
    headers, case_id = _case(client, "logs@example.com")
    base = f"/cases/{case_id}"
    client.app.state.intake_llm = ScriptedModel(_extraction(company_name="Amazon", amount="500", order_id="[NUM_1]", order_date="2026-11-20", desired_remedy="refund"))
    client.app.state.evidence_ocr = ScriptedOCR()
    story = ("My name is CANARYNAME9f3a. Amazon order id OD1234567890, 500 rupees. Card 4111 1111 1111 1111, OTP 482913, phone 9876543210, "
             "address flat 4B, Rose Apartments, MG Road, pin code 560001. Refund please since 20 November")
    with caplog.at_level(logging.DEBUG):
        client.post(f"{base}/intake/messages", json={"text": story}, headers=headers)
        client.post(f"{base}/narration-done", headers=headers)
        client.post(f"{base}/intake/messages", json={"text": "marketplace"}, headers=headers)
        upload = client.post(f"{base}/evidence", headers=headers, files={"file": ("r.png", io.BytesIO(b"png"), "image/png")}, data={"type": "receipt"}).json()
        client.post(f"{base}/evidence/{upload['id']}/process", headers=headers)
        client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
        client.delete(base, headers=headers)
    logged = caplog.text
    for canary in CANARIES:
        assert canary not in logged, canary
    for secret in settings.secret_values() + ["correct-horse"]:
        assert secret not in logged
    assert "gsk_" not in logged and "rk_live_" not in logged
