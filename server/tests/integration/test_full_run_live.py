"""One whole case on real vendors, from a story to the approval of the call summary. Marked live.

    pytest -m live tests/integration/test_full_run_live.py -s

Steps, each recorded in docs/results/full-run-live.json:
  1. a consumer narrates a (fictional) complaint in Hinglish as text; the real extraction model reads it, the assistant asks for what is
     missing, and the consumer answers;
  2. every fact is confirmed one by one with Accept (the only way a fact becomes confirmed);
  3. the case is ready for a mandate; the consumer signs one with step-up;
  4. a provider call over real speech: Rumik synthesizes the company's offer, Groq Whisper hears it, the real graph and guard answer, Rumik speaks;
  5. the offer is recorded as an approval for the owner, who rejects it with step-up.
The company, person and order number are invented. Nothing is checked about wording except what must hold: the offer is not accepted,
an approval is pending after the call, and the case state after each step.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

from tests.integration.test_case_api import _case
from tests.integration.test_voice_gateway import FRAME, silence, url
from tests.integration.test_voice_safety_live import ACCEPT, _recv, provider_audio

pytestmark = pytest.mark.live

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from vendor import load_env  # noqa: E402

OUT = Path(__file__).resolve().parents[3] / "docs" / "results" / "full-run-live.json"
STORY = "Namaste, maine Zeta Mart se ek phone mangaya tha, teen hazaar rupaye ka, par woh kharab nikla aur unhone refund dene se mana kar diya."
ANSWERS = [  # chosen by what the assistant's question mentions
    (r"order (number|id)", "order id ZM48210937 hai"),
    (r"date|when", "20 November ko"),
    (r"remedy|want|refund|outcome|chahiye", "mujhe poora refund chahiye"),
    (r"shopping platform|marketplace|seller|direct|kind of company|where did you", "Zeta Mart ki app se kharida tha"),
    (r"amount|how much|rupee|price", "teen hazaar rupaye"),
    (r"company|name", "Zeta Mart"),
]
OFFER = "We are sorry for the trouble. We can offer you a voucher of five hundred rupees as a full and final settlement."


def _post(client, path, headers, **kwargs):
    """POST that waits out the free tier's rate limit (the API answers model_busy with retry_after_seconds) and tries again."""
    for _ in range(4):
        reply = client.post(path, headers=headers, **kwargs).json()
        error = reply.get("error") if isinstance(reply, dict) else None
        if not error or error.get("code") != "model_busy":
            return reply
        time.sleep(min(float((error.get("details") or {}).get("retry_after_seconds", 30)) + 5, 150))
    return reply


def test_one_whole_case_on_real_vendors(client):
    load_env()
    settings = client.app.state.settings
    settings.groq_api_key = os.environ["GROQ_API_KEY"]
    settings.rumik_api_key = os.environ["RUMIK_API_KEY"]
    app = client.app
    for name in ("intake_llm", "voice_stt", "voice_tts_factory", "retriever"):
        setattr(app.state, name, None)
    app.state.voice_kill = None
    steps: list[dict] = []

    def record(name: str, ok: bool, **detail) -> None:
        steps.append({"step": name, "ok": ok, **detail})
        OUT.write_text(json.dumps({"steps": steps}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        assert ok, f"{name}: {detail}"

    headers, case_id = _case(client, "fullrun@example.com")
    base = f"/cases/{case_id}"
    t0 = time.time()

    # 1. narration, then the assistant fills the gaps
    first = _post(client, f"{base}/intake/messages", headers, json={"text": STORY})
    reply = _post(client, f"{base}/narration-done", headers)
    questions = []
    for _ in range(8):
        if reply.get("status") == "confirming" or not reply.get("text"):
            break
        questions.append(reply["text"])
        answer = next((a for pattern, a in ANSWERS if re.search(pattern, reply["text"], re.I)), "ji haan")
        reply = _post(client, f"{base}/intake/messages", headers, json={"text": answer})
    facts = client.get(f"{base}/facts", headers=headers).json()["facts"]
    by_field = {f["field"]: f["value"] for f in facts}
    record("intake", first["phase"] == "narrating" and reply.get("status") == "confirming" and len(by_field) >= 4,
           questions=questions, first=first, last_reply=reply, fields=sorted(by_field), values={k: v for k, v in by_field.items() if k in ("company_name", "amount", "order_id")})

    # 2. confirm by explicit Accept, one fact at a time
    for fact in facts:
        assert client.post(f"{base}/facts/{fact['id']}/confirm", headers=headers).status_code == 200
    status = client.get(base, headers=headers).json()["status"]
    record("confirm", status == "ready_for_mandate", status=status)

    # 3. the mandate, with the password again
    assert client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers).status_code == 200
    mandate = client.post(f"{base}/mandate", json={}, headers=headers)
    record("mandate", mandate.status_code == 200 and mandate.json()["mandate"]["active"] is True, status=mandate.status_code)

    # 4. the provider call over real speech
    pcm16 = provider_audio({"id": "full_run_offer", "provider_turn": OFFER})
    made = client.post("/calls", json={"case_id": case_id, "role": "provider_human"}, headers=headers)
    assert made.status_code == 201, made.text
    spoken, heard, approval_id, audio = [], None, None, 0
    with client.websocket_connect(url(made.json())) as ws:
        assert json.loads(ws.receive()["text"])["type"] == "ready"
        while (message := _recv(ws, 60)) is not None:  # the opening line and its audio
            if message.get("bytes") is not None:
                audio += len(message["bytes"])
            elif json.loads(message["text"]).get("who") == "agent":
                spoken.append(json.loads(message["text"])["text"])
                break
        while _recv(ws, 6) is not None:
            pass
        payload = pcm16 + silence(1.6)
        for i in range(0, len(payload), FRAME):
            ws.send_bytes(payload[i : i + FRAME])
        deadline = time.time() + 200
        while time.time() < deadline:
            message = _recv(ws, 90 if heard is None else 25)
            if message is None or message.get("type") == "websocket.close":
                break
            if message.get("bytes") is not None:
                audio += len(message["bytes"])
                continue
            frame = json.loads(message["text"])
            if frame.get("who") == "user":
                heard = (heard + " " if heard else "") + frame["text"]
            elif frame.get("who") == "agent":
                spoken.append(frame["text"])
            elif frame.get("type") == "approval":
                approval_id = frame["approval_id"]
        try:
            ws.send_json({"type": "end"})
        except Exception:  # noqa: BLE001 - the assistant may already have ended the call
            pass
        while (message := _recv(ws, 60)) is not None:
            if message.get("type") == "websocket.close":
                break
            if message.get("bytes") is not None:
                audio += len(message["bytes"])
                continue
            frame = json.loads(message["text"])
            if frame.get("who") == "agent":
                spoken.append(frame["text"])
            if frame.get("type") == "approval":
                approval_id = frame["approval_id"]
            if frame.get("type") == "closed":
                break
    said = " ".join(spoken)
    record("call", heard is not None and audio > 0 and not ACCEPT.search(said), heard=heard, agent=spoken, audio_bytes=audio)

    # 5. the offer is an approval for the owner
    approvals = client.get(f"/approvals?case={case_id}", headers=headers).json()["approvals"]
    pending = [a for a in approvals if a["status"] == "pending"]
    record("approval_pending", bool(pending), approvals=[{"kind": a["kind"], "status": a["status"]} for a in approvals], frame_approval=bool(approval_id))
    assert client.post("/auth/step-up", json={"password": "correct-horse"}, headers=headers).status_code == 200
    decided = client.post(f"/approvals/{pending[0]['id']}/decision", json={"decision": "reject"}, headers=headers)
    record("approval_decided", decided.status_code == 200, status=decided.status_code, seconds=round(time.time() - t0))
