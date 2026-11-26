"""Evidence processing through the API. OCR and vision are scripted unless a test says otherwise."""

import io
from pathlib import Path

import pytest

from app.adapters.ocr import TesseractOCR
from tests.integration.test_case_api import _case

RECEIPT = chr(10).join(["Flipkart", "Order Confirmation", "Order ID: OD1234567890", "Order date: 20 Nov 2025", "Order total: Rs. 10,900.00"])
DOCS = Path(__file__).resolve().parents[2] / "data" / "evidence_docs"


class ScriptedOCR:
    def __init__(self, *texts):
        self.texts = list(texts)

    def read(self, image):
        return self.texts


class CountingVision:
    def __init__(self, text=RECEIPT):
        self.text, self.calls = text, 0

    def read_text(self, image):
        self.calls += 1
        return self.text


class NoModel:
    """Fills no gaps; the deterministic finder does the work in these tests."""

    def structured(self, role, prompt_id, variables, schema, mode="instruct"):
        return {name: {"value": "", "certainty": "not_stated", "original_phrase": "", "ambiguity_note": ""} for name in schema["properties"]}, {}


def _upload(client, headers, case_id, payload=b"png-bytes"):
    resp = client.post(f"/cases/{case_id}/evidence", headers=headers, files={"file": ("doc.png", io.BytesIO(payload), "image/png")}, data={"type": "receipt"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _setup(client, email, ocr, vision=None):
    headers, case_id = _case(client, email)
    client.app.state.evidence_ocr = ocr
    client.app.state.evidence_vision = vision or CountingVision()
    client.app.state.intake_llm = NoModel()
    return headers, case_id, _upload(client, headers, case_id)


def test_readable_receipt_is_read_locally_with_no_vision_call(client):
    vision = CountingVision()
    headers, case_id, evidence_id = _setup(client, "ev1@example.com", ScriptedOCR(RECEIPT), vision)
    out = client.post(f"/cases/{case_id}/evidence/{evidence_id}/process", headers=headers).json()
    assert out["state"] == "read" and vision.calls == 0
    listed = client.get(f"/cases/{case_id}/evidence", headers=headers).json()["evidence"][0]
    assert listed["read"]["fields"]["order_id"]["value"] == "OD1234567890"
    assert listed["read"]["source"] == "local_ocr" and listed["sent_to_vision"] is False


def test_unreadable_image_waits_for_approval_and_nothing_is_sent(client):
    vision = CountingVision()
    headers, case_id, evidence_id = _setup(client, "ev2@example.com", ScriptedOCR(""), vision)
    out = client.post(f"/cases/{case_id}/evidence/{evidence_id}/process", headers=headers).json()
    assert out["state"] == "waiting_approval" and vision.calls == 0
    detail = client.get(f"/cases/{case_id}", headers=headers).json()
    assert detail["open_approvals"][0]["kind"] == "send_image_to_llm"
    listed = client.get(f"/cases/{case_id}/evidence", headers=headers).json()["evidence"][0]
    assert listed["sent_to_vision"] is False


def test_approval_sends_exactly_that_image_then_reads_it(client):
    vision = CountingVision()
    headers, case_id, evidence_id = _setup(client, "ev3@example.com", ScriptedOCR(""), vision)
    client.post(f"/cases/{case_id}/evidence/{evidence_id}/process", headers=headers)
    approval_id = client.get(f"/cases/{case_id}", headers=headers).json()["open_approvals"][0]["id"]
    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
    assert client.post(f"/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=headers).status_code == 200
    assert vision.calls == 1
    listed = client.get(f"/cases/{case_id}/evidence", headers=headers).json()["evidence"][0]
    assert listed["sent_to_vision"] is True and listed["read"]["source"] == "vision"


def test_rejected_approval_means_the_consumer_types_the_fields(client):
    vision = CountingVision()
    headers, case_id, evidence_id = _setup(client, "ev4@example.com", ScriptedOCR(""), vision)
    client.post(f"/cases/{case_id}/evidence/{evidence_id}/process", headers=headers)
    approval_id = client.get(f"/cases/{case_id}", headers=headers).json()["open_approvals"][0]["id"]
    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
    client.post(f"/approvals/{approval_id}/decision", json={"decision": "reject"}, headers=headers)
    listed = client.get(f"/cases/{case_id}/evidence", headers=headers).json()["evidence"][0]
    assert vision.calls == 0 and listed["sent_to_vision"] is False and listed["read"]["state"] == "type_it_yourself"


def test_a_vision_failure_does_not_undo_the_decision(client):
    class Broken:
        def read_text(self, image):
            raise RuntimeError("vendor down")

    headers, case_id, evidence_id = _setup(client, "ev5@example.com", ScriptedOCR(""), Broken())
    client.post(f"/cases/{case_id}/evidence/{evidence_id}/process", headers=headers)
    approval_id = client.get(f"/cases/{case_id}", headers=headers).json()["open_approvals"][0]["id"]
    client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers)
    decided = client.post(f"/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=headers)
    assert decided.status_code == 200 and decided.json()["status"] == "approved"


def test_evidence_that_contradicts_a_confirmed_fact_is_flagged_with_one_question(client):
    headers, case_id, evidence_id = _setup(client, "ev6@example.com", ScriptedOCR(RECEIPT))
    fact = client.post(f"/cases/{case_id}/facts", json={"field": "amount", "value": "9000"}, headers=headers).json()
    client.post(f"/cases/{case_id}/facts/{fact['id']}/confirm", headers=headers)
    out = client.post(f"/cases/{case_id}/evidence/{evidence_id}/process", headers=headers).json()
    assert out["state"] == "needs_attention" and out["flags"][0]["field"] == "amount"
    notes = client.get("/notifications", headers=headers).json()["notifications"]
    assert any(n["kind"] == "evidence_mismatch" for n in notes)


def test_another_user_cannot_process_evidence(client):
    _, case_id, evidence_id = _setup(client, "ev7@example.com", ScriptedOCR(RECEIPT))
    other, _ = _case(client, "ev8@example.com")
    assert client.post(f"/cases/{case_id}/evidence/{evidence_id}/process", headers=other).status_code == 404


@pytest.mark.skipif(not (TesseractOCR().available and (DOCS / "ev01.png").is_file()), reason="Tesseract or the drawn documents are missing")
def test_real_tesseract_reads_a_drawn_receipt(client):
    headers, case_id = _case(client, "ev9@example.com")
    client.app.state.evidence_vision = CountingVision()
    client.app.state.intake_llm = NoModel()
    evidence_id = _upload(client, headers, case_id, (DOCS / "ev01.png").read_bytes())
    out = client.post(f"/cases/{case_id}/evidence/{evidence_id}/process", headers=headers).json()
    listed = client.get(f"/cases/{case_id}/evidence", headers=headers).json()["evidence"][0]
    assert out["state"] in {"read", "needs_attention"} and listed["read"]["fields"]["order_id"]["value"]
