"""How fast the assistant stops talking when the other person starts. Marked live: it uses real Rumik synthesis, about 100 characters a trial.

    BARGE_TRIALS=30 pytest -m live tests/integration/test_barge_in_live.py -s

Each trial opens a provider call, waits until the assistant's opening line is audible (a caption and the first audio chunk have arrived),
then sends 0.6 s of speech-like audio. Stop time is measured on the test side from the frame that completes 100 ms of speech to the `flush` frame the
server sends to tell the browser to empty its playback queue. Audio is sent faster than real time, so the figure is server processing
time; the 90 ms of speech the endpointer needs before it reports a start is real time on top of it, and the browser's own playback
flush and the network are not included. After the flush, any audio that still arrives within 300 ms counts against the trial.
Results are written to docs/results/barge-in-live.json.
"""

import json
import os
import statistics
import sys
import time
from pathlib import Path

import pytest

from tests.integration.test_mandate_service import _setup
from tests.integration.test_voice_gateway import FRAME, speech, url
from tests.integration.test_voice_safety_live import _recv

pytestmark = pytest.mark.live

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from vendor import load_env  # noqa: E402

TRIALS = int(os.environ.get("BARGE_TRIALS", "3"))
OUT = Path(__file__).resolve().parents[3] / "docs" / "results" / "barge-in-live.json"
ROWS: list[dict] = []


@pytest.mark.parametrize("trial", range(TRIALS))
def test_agent_stops_when_the_caller_talks_over_it(client, trial):
    load_env()
    settings = client.app.state.settings
    settings.groq_api_key = os.environ["GROQ_API_KEY"]
    settings.rumik_api_key = os.environ["RUMIK_API_KEY"]
    app = client.app
    for name in ("intake_llm", "voice_stt", "voice_tts_factory", "retriever"):
        setattr(app.state, name, None)
    app.state.voice_kill = None
    headers, case_id = _setup(client, f"bi{trial}@example.com")
    made = client.post("/calls", json={"case_id": case_id, "role": "provider_human"}, headers=headers)
    assert made.status_code == 201, made.text
    row = {"trial": trial, "stop_ms": None, "stray_audio_after_flush": 0, "note": ""}
    with client.websocket_connect(url(made.json())) as ws:
        assert json.loads(ws.receive()["text"])["type"] == "ready"
        captioned = chunks = 0
        deadline = time.time() + 60
        while time.time() < deadline and not (captioned and chunks >= 2):
            message = _recv(ws, 30)
            if message is None:
                break
            if message.get("bytes") is not None:
                chunks += 1
            elif json.loads(message["text"]).get("who") == "agent":
                captioned += 1
        if not (captioned and chunks >= 2):
            row["note"] = "the assistant never started speaking"
        else:
            payload = speech(0.6)
            frames = [payload[i : i + FRAME] for i in range(0, len(payload), FRAME)]
            onset_frame = 5  # 100 ms of speech, the first point at which the endpointer (90 ms) can report a start
            for frame in frames[:onset_frame - 1]:
                ws.send_bytes(frame)
            sent_at = time.perf_counter()
            for frame in frames[onset_frame - 1:]:
                ws.send_bytes(frame)
            flushed_at = None
            stray = 0
            until = time.time() + 20
            while time.time() < until:
                message = _recv(ws, 3 if flushed_at is None else 0.3)
                if message is None:
                    break
                if message.get("type") == "websocket.close":
                    break
                if message.get("bytes") is not None:
                    if flushed_at is not None:
                        stray += 1
                    continue
                if json.loads(message["text"]).get("type") == "flush" and flushed_at is None:
                    flushed_at = time.perf_counter()
            if flushed_at is not None:
                row["stop_ms"] = round((flushed_at - sent_at) * 1000)
            else:
                row["note"] = "no flush frame"
            row["stray_audio_after_flush"] = stray
    ROWS.append(row)
    kept = []
    if OUT.is_file():
        kept = [r for r in json.loads(OUT.read_text(encoding="utf-8")).get("rows", []) if r["trial"] not in {x["trial"] for x in ROWS}]
    rows = sorted(kept + ROWS, key=lambda r: r["trial"])
    done = [r["stop_ms"] for r in rows if r["stop_ms"] is not None]
    summary = {"trials": len(rows), "measured": len(done), "within_500ms": sum(1 for v in done if v <= 500),
               "median_ms": statistics.median(done) if done else None, "max_ms": max(done) if done else None}
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1) + "\n", encoding="utf-8")
    assert row["stop_ms"] is not None, row["note"]
