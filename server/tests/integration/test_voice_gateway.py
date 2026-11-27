"""The voice gateway with scripted speech recognition, speech synthesis and model. No vendor is called."""

import array
import math
import wave
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from app.voice.tts import FakeTTS
from tests.integration.test_case_api import _case
from tests.integration.test_intake_api import ScriptedModel, _extraction

FRAME = 640  # 20 ms of 16 kHz PCM16
AUDIO = Path(__file__).resolve().parents[2] / "data" / "audio"


def speech(seconds=2.0):
    out = array.array("h")
    for i in range(int(16000 * seconds)):
        t = i / 16000
        envelope = 1.0 if int(t * 4) % 2 == 0 else 0.03
        out.append(int(6000 * envelope * math.sin(2 * math.pi * 180 * t)))
    return out.tobytes()


def silence(seconds):
    return bytes(int(16000 * seconds) * 2)


def noise(seconds):
    import random

    rng = random.Random(3)
    return array.array("h", [int(rng.gauss(0, 700)) for _ in range(int(16000 * seconds))]).tobytes()


class ScriptedSTT:
    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []

    def transcribe(self, role, audio, filename="clip.wav"):
        self.calls.append(role)
        return {"text": self.texts.pop(0) if self.texts else "", "dropped_segments": 0, "duration_seconds": 1}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def setup(client, email, stt=None, tts=None, model=None, role="consumer"):
    headers, case_id = _case(client, email)
    app = client.app
    app.state.voice_stt = stt or ScriptedSTT()
    app.state.voice_tts = tts or FakeTTS()
    app.state.voice_tts_factory = lambda: app.state.voice_tts
    app.state.intake_llm = model or ScriptedModel()
    app.state.voice_time = Clock()
    app.state.voice_kill = None
    call = client.post("/calls", json={"case_id": case_id, "role": role}, headers=headers)
    assert call.status_code == 201, call.text
    return headers, case_id, call.json()


def url(call):
    return f"/voice/ws?token={call['ws_token']}"


def stream(ws, pcm):
    for i in range(0, len(pcm), FRAME):
        ws.send_bytes(pcm[i : i + FRAME])


def collect(ws, until, limit=400):
    """Reads frames until `until(json_frame)` is true. Returns (json frames, binary chunk count)."""
    frames, chunks = [], 0
    for _ in range(limit):
        message = ws.receive()
        if message["type"] == "websocket.close":
            break
        if message.get("bytes") is not None:
            chunks += 1
            continue
        import json

        frame = json.loads(message["text"])
        frames.append(frame)
        if until(frame):
            break
    return frames, chunks


def take_chunks(ws, count):
    """Reads until `count` binary audio chunks have arrived (they follow the caption of a sentence)."""
    seen = 0
    while seen < count:
        if ws.receive().get("bytes") is not None:
            seen += 1


def test_token_works_once(client):
    _, _, call = setup(client, "v1@example.com")
    with client.websocket_connect(url(call)) as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "end"})
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url(call)):
            pass


def test_unknown_and_expired_tokens_are_refused(client):
    _, _, call = setup(client, "v2@example.com")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/voice/ws?token=not-a-real-token"):
            pass
    client.clock.advance(seconds=61)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url(call)):
            pass


def test_a_token_for_another_users_case_cannot_be_minted(client):
    _, case_id, _ = setup(client, "v3@example.com")
    other, _ = _case(client, "v3b@example.com")
    assert client.post("/calls", json={"case_id": case_id}, headers=other).status_code == 404


def test_narration_is_transcribed_redacted_and_the_agent_stays_silent(client):
    stt = ScriptedSTT("Flipkart se phone mangaya mera number 9876543210 hai aur OTP 482913 maang rahe the")
    tts = FakeTTS()
    _, _, call = setup(client, "v4@example.com", stt, tts)
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        stream(ws, speech(2.5) + silence(2.0))
        frames, chunks = collect(ws, lambda f: f.get("type") == "caption" and f.get("who") == "user")
        user = [f for f in frames if f.get("who") == "user"][0]
        assert "9876543210" not in user["text"] and "482913" not in user["text"] and "[PHONE]" in user["text"]
        assert chunks == 0 and tts.spoken == []  # nothing is said while the person narrates
        assert stt.calls == ["stt_narration"]
        ws.send_json({"type": "end"})


def test_done_makes_the_agent_ask_the_first_missing_field_aloud(client):
    stt = ScriptedSTT("Flipkart se phone mangaya aur refund nahi mila")
    tts = FakeTTS()
    model = ScriptedModel(_extraction(company_name="Flipkart"))
    _, _, call = setup(client, "v5@example.com", stt, tts, model)
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        stream(ws, speech(2.5) + silence(2.0))
        collect(ws, lambda f: f.get("who") == "user")
        ws.send_json({"type": "done_narration"})
        frames, chunks = collect(ws, lambda f: f.get("type") == "caption" and f.get("who") == "agent")
        assert [f["phase"] for f in frames if f.get("type") == "phase"] == ["gap_filling"]
        assert "How much did you pay" in [f for f in frames if f.get("who") == "agent"][0]["text"]
        take_chunks(ws, 3)  # the sentence's audio arrives after its caption
        assert tts.spoken and tts.spoken[0].startswith("How much")
        ws.send_json({"type": "end"})


def test_silence_and_noise_never_reach_speech_recognition(client):
    stt = ScriptedSTT("should never be used")
    _, _, call = setup(client, "v6@example.com", stt)
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        stream(ws, silence(3.0) + noise(3.0) + silence(2.0))
        ws.send_json({"type": "done_narration"})
        ws.send_json({"type": "end"})
        collect(ws, lambda f: f.get("type") == "closed")
    assert stt.calls == []


@pytest.mark.skipif(not (AUDIO / "n01-quiet.wav").is_file(), reason="the synthetic narration clips are not on this machine")
def test_a_real_wav_clip_goes_through_the_gateway(client):
    stt = ScriptedSTT("Flipkart se phone mangaya aur refund nahi mila")
    _, _, call = setup(client, "v7@example.com", stt)
    with wave.open(str(AUDIO / "n01-quiet.wav")) as handle:
        pcm = handle.readframes(handle.getnframes())
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        stream(ws, pcm + silence(2.0))
        frames, _ = collect(ws, lambda f: f.get("who") == "user", limit=2000)
        assert any(f.get("who") == "user" for f in frames)
        ws.send_json({"type": "end"})


def test_the_kill_switch_closes_open_calls_and_blocks_new_ones(client):
    headers, case_id, call = setup(client, "v8@example.com")
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        assert client.post("/admin/kill-voice").json() == {"engaged": True}
        frames, _ = collect(ws, lambda f: f.get("type") == "closed")
        assert frames[-1] == {"type": "closed", "reason": "voice_disabled"}
    assert client.post("/calls", json={"case_id": case_id}, headers=headers).status_code == 503


def test_a_killed_session_cannot_reconnect(client):
    headers, case_id, call = setup(client, "v9@example.com")
    client.post("/admin/kill-voice")
    client.app.state.voice_kill.engaged = False  # even with the switch cleared, the session itself is dead
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url(call)):
            pass


def test_a_call_over_its_time_budget_is_closed(client):
    _, _, call = setup(client, "v10@example.com")
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        client.app.state.voice_time.t += client.app.state.settings.voice_max_call_seconds + 1
        frames, _ = collect(ws, lambda f: f.get("type") == "closed")
        assert frames[-1]["reason"] == "call_time"


def test_barge_in_stops_the_agent_and_tells_the_browser_to_flush(client):
    stt = ScriptedSTT("Flipkart se phone mangaya aur refund nahi mila")
    tts = FakeTTS(chunks=200)  # a long sentence, so there is something to interrupt
    model = ScriptedModel(_extraction(company_name="Flipkart"))
    _, _, call = setup(client, "v11@example.com", stt, tts, model)
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        stream(ws, speech(2.5) + silence(2.0))
        collect(ws, lambda f: f.get("who") == "user")
        ws.send_json({"type": "done_narration"})
        collect(ws, lambda f: f.get("who") == "agent")
        stream(ws, speech(0.6))  # the caller talks over the agent
        frames, _ = collect(ws, lambda f: f.get("type") == "flush")
        assert frames[-1] == {"type": "flush"}
        assert tts.cancels >= 1
        ws.send_json({"type": "end"})


def test_a_spoken_yes_never_confirms_a_fact(client):
    stt = ScriptedSTT("Amazon order AB1 five hundred refund since 20 November", "haan sab theek hai")
    model = ScriptedModel(_extraction(company_name="Amazon", amount="500", order_id="AB1", order_date="2026-11-20", desired_remedy="refund"))
    headers, case_id, call = setup(client, "v12@example.com", stt, FakeTTS(), model)
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        stream(ws, speech(2.5) + silence(2.0))
        collect(ws, lambda f: f.get("who") == "user")
        ws.send_json({"type": "done_narration"})
        collect(ws, lambda f: f.get("who") == "agent")  # the provider-type question
        take_chunks(ws, 3)
        stream(ws, speech(2.0) + silence(1.0))
        frames, _ = collect(ws, lambda f: f.get("type") == "card", limit=600)
        cards = [f for f in frames if f.get("type") == "card"]
        assert cards and cards[0]["kind"] == "confirm_field"
        ws.send_json({"type": "end"})
    facts = client.get(f"/cases/{case_id}/facts", headers=headers).json()["facts"]
    assert facts and all(f["confirmation_state"] == "unconfirmed" for f in facts)


def test_ending_a_call_is_recorded(client):
    headers, _, call = setup(client, "v14@example.com")
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        ws.send_json({"type": "end"})
        collect(ws, lambda f: f.get("type") == "closed")
    assert client.post(f"/calls/{call['call_id']}/end", headers=headers).json()["state"] == "closed"


def test_a_call_over_its_speech_budget_is_closed(client):
    stt = ScriptedSTT("Amazon order AB1 five hundred refund since 20 November", "marketplace")
    model = ScriptedModel(_extraction(company_name="Amazon", amount="500", order_id="AB1", order_date="2026-11-20", desired_remedy="refund"))
    _, _, call = setup(client, "v15@example.com", stt, FakeTTS(), model)
    client.app.state.settings.voice_daily_tts_chars = 100  # the provider-type question alone is longer than this
    with client.websocket_connect(url(call)) as ws:
        ws.receive_json()
        stream(ws, speech(2.5) + silence(2.0))
        collect(ws, lambda f: f.get("who") == "user")
        ws.send_json({"type": "done_narration"})
        collect(ws, lambda f: f.get("who") == "agent")
        take_chunks(ws, 3)
        stream(ws, speech(2.0) + silence(1.0))
        frames, _ = collect(ws, lambda f: f.get("type") == "closed", limit=600)
        assert frames[-1] == {"type": "closed", "reason": "speech_budget"}


def test_a_user_over_their_daily_voice_time_cannot_start_a_call(client):
    from sqlalchemy import text

    headers, case_id, _ = setup(client, "v16@example.com")
    with client.db_engine.begin() as conn:
        conn.execute(text("UPDATE voice_sessions SET stt_seconds = 999999"))
    blocked = client.post("/calls", json={"case_id": case_id}, headers=headers)
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "daily_voice_limit"
