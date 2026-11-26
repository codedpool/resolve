"""Latency prototype: clip -> Whisper turbo -> classify -> Qwen first sentence -> guard stub -> Rumik TTS.

One Rumik websocket is kept open for the whole run and each sentence is a frame. Measures time to
first audio per turn, with and without the guard stub, then tests cancel and barge-in.
Writes docs/results/s0.4-latency.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).parent))
from bake_llm import CLASS_PROMPT, CLASS_SCHEMA  # noqa: E402
from vendor import RUMIK, ROOT, chat, groq_client, load_env, transcribe  # noqa: E402

AUDIO = ROOT / "server" / "data" / "audio"
OUT = ROOT / "docs" / "results" / "s0.4-latency.json"
GUARD_MODEL = os.environ.get("GUARD_MODEL", "openai/gpt-oss-20b")
REPLY_PROMPT = (
    "You are a calm assistant calling a company on behalf of a consumer. Reply to the representative in one short "
    "Hinglish sentence (under 20 words). Do not accept any offer."
)
PROVIDER_LINES = [
    "We can offer you a credit of five hundred rupees.", "Aapka order delivered dikha raha hai.",
    "Please share your phone number to verify.", "Please hold while I check with my supervisor.",
]
GUARD_PROMPT = "Reply with JSON {\"safe\": true} if this sentence accepts no offer and reveals no personal data, else {\"safe\": false}."
GUARD_SCHEMA = {"name": "guard", "strict": True, "schema": {"type": "object", "additionalProperties": False,
                "properties": {"safe": {"type": "boolean"}}, "required": ["safe"]}}


async def open_session():
    load_env()
    http = httpx.AsyncClient(base_url=RUMIK, headers={"Authorization": f"Bearer {os.environ['RUMIK_API_KEY']}"}, timeout=60)
    r = await http.post("/v1/tts/ws-connect", json={"model": "mulberry", "language": "hinglish", "text": "Namaste."})
    s = r.json()
    await http.aclose()
    return await websockets.connect(f"{s['ws_url']}?token={s['token']}", max_size=16_000_000, ping_interval=None)


async def speak(ws, text: str) -> float:
    started = time.perf_counter()
    await ws.send(json.dumps({"text": text}))
    first = None
    while True:
        m = await asyncio.wait_for(ws.recv(), timeout=30)
        if isinstance(m, bytes):
            if first is None:
                first = (time.perf_counter() - started) * 1000
            continue
        f = json.loads(m)
        if f.get("type") in {"done", "cancelled"} or f.get("error"):
            return first if first is not None else -1.0


async def main() -> None:
    client = groq_client()
    ws = await open_session()
    await speak(ws, "Namaste.")  # warm
    clips = [p for p in sorted(AUDIO.glob("n0*-quiet.wav"))]
    rows = []
    for guard in (False, True):
        for i in range(12):
            wav = clips[i % len(clips)].read_bytes()
            wav_short = wav[: 44 + 16000 * 2 * 6]  # first 6 s as a turn
            t0 = time.perf_counter()
            tr = await asyncio.to_thread(transcribe, client, "whisper-large-v3-turbo", wav_short, None)
            t_stt = time.perf_counter()
            text = PROVIDER_LINES[i % len(PROVIDER_LINES)]
            await asyncio.to_thread(chat, client, "qwen/qwen3.8-27b", [{"role": "system", "content": CLASS_PROMPT}, {"role": "user", "content": text}],
                 effort="none", schema=CLASS_SCHEMA, max_tokens=60)
            t_cls = time.perf_counter()
            reply, _, _ = await asyncio.to_thread(chat, client, "qwen/qwen3.8-27b", [{"role": "system", "content": REPLY_PROMPT}, {"role": "user", "content": text}],
                               effort="none", max_tokens=60)
            reply = re.split(r"(?<=[.?!])\s", reply.strip())[0] or "Ji, samajh gaya."
            t_llm = time.perf_counter()
            if guard:
                await asyncio.to_thread(chat, client, GUARD_MODEL, [{"role": "system", "content": GUARD_PROMPT}, {"role": "user", "content": reply}],
                     effort="low", schema=GUARD_SCHEMA, max_tokens=200)
            t_guard = time.perf_counter()
            first = await speak(ws, reply)
            total = (time.perf_counter() - t0) * 1000 - ((time.perf_counter() - time.perf_counter()))
            rows.append({"guard": guard, "stt_ms": (t_stt - t0) * 1000, "classify_ms": (t_cls - t_stt) * 1000,
                         "llm_ms": (t_llm - t_cls) * 1000, "guard_ms": (t_guard - t_llm) * 1000, "tts_first_ms": first,
                         "ttfa_ms": (t_guard - t0) * 1000 + first})
            print(guard, round(rows[-1]["ttfa_ms"]))
    # cancel and barge-in
    await ws.send(json.dumps({"text": "Yeh ek lamba vakya hai jo main dheere dheere bol raha hoon taaki beech mein rok sakein."}))
    while not isinstance(await ws.recv(), bytes):
        pass
    t = time.perf_counter()
    await ws.send(json.dumps({"type": "cancel"}))
    stop_ms = None
    late_audio = 0
    while True:
        m = await asyncio.wait_for(ws.recv(), timeout=10)
        if isinstance(m, bytes):
            late_audio += 1
            continue
        f = json.loads(m)
        if f.get("type") in {"cancelled", "done"}:
            stop_ms = (time.perf_counter() - t) * 1000
            kind = f["type"]
            break
    after = await speak(ws, "Theek hai.")  # session still usable after cancel
    await ws.send(json.dumps({"type": "close"}))
    await ws.close()

    def pct(vals, p):
        s = sorted(vals)
        return round(s[min(len(s) - 1, int(len(s) * p))])

    summary = {}
    for g in (False, True):
        v = [r["ttfa_ms"] for r in rows if r["guard"] == g]
        summary["with_guard" if g else "no_guard"] = {"n": len(v), "p50": round(statistics.median(v)), "p95": pct(v, 0.95),
            "parts_median_ms": {k: round(statistics.median([r[k] for r in rows if r["guard"] == g])) for k in ("stt_ms", "classify_ms", "llm_ms", "guard_ms", "tts_first_ms")}}
    result = {"summary": summary, "cancel": {"ack_ms": round(stop_ms), "frame": kind, "audio_chunks_after_cancel": late_audio, "reusable_after": after > 0}, "rows": rows}
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result["summary"], indent=1), result["cancel"])


if __name__ == "__main__":
    asyncio.run(main())
