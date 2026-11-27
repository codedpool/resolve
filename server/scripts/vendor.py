"""Shared helpers for the live evaluation scripts: env loading, Groq calls, Rumik synthesis."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
import time
import wave
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]
GROQ = "https://api.groq.com/openai/v1"
RUMIK = "https://silk-api.rumik.ai"


def load_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def redact(text: str) -> str:
    for name in ("GROQ_API_KEY", "RUMIK_API_KEY"):
        secret = os.environ.get(name, "")
        if secret:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"rk_(?:live|test)_[A-Za-z0-9_\-]+", "[redacted]", text)
    return re.sub(r"gsk_[A-Za-z0-9]+", "[redacted]", text)


def groq_client() -> httpx.Client:
    load_env()
    return httpx.Client(base_url=GROQ, headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}, timeout=120)


def chat(client: httpx.Client, model: str, messages: list[dict], effort: str | None = None,
         schema: dict | None = None, max_tokens: int = 700) -> tuple[str, dict, float]:
    body: dict = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if effort:
        body["reasoning_effort"] = effort
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": schema}
    for attempt in range(5):
        started = time.perf_counter()
        r = client.post("/chat/completions", json=body)
        elapsed = time.perf_counter() - started
        if r.status_code == 429:
            time.sleep(float(r.headers.get("retry-after", 2 + attempt * 2)))
            continue
        if r.status_code >= 400:
            raise RuntimeError(redact(f"{r.status_code} {r.text[:300]}"))
        data = r.json()
        return data["choices"][0]["message"].get("content") or "", data.get("usage", {}), elapsed
    raise RuntimeError("rate limited")


def transcribe(client: httpx.Client, model: str, wav_bytes: bytes, language: str | None) -> dict:
    data = {"model": model, "response_format": "verbose_json", "temperature": "0"}
    if language:
        data["language"] = language
    for attempt in range(5):
        r = client.post("/audio/transcriptions", data=data, files={"file": ("clip.wav", io.BytesIO(wav_bytes), "audio/wav")})
        if r.status_code == 429:
            time.sleep(float(r.headers.get("retry-after", 2 + attempt * 2)))
            continue
        if r.status_code >= 400:
            raise RuntimeError(redact(f"{r.status_code} {r.text[:300]}"))
        return r.json()
    raise RuntimeError("rate limited")


def pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def resample_16k(pcm24: bytes) -> bytes:
    """24 kHz to 16 kHz by linear interpolation (3 samples out for every 2... ratio 2/3)."""
    import array

    src = array.array("h")
    src.frombytes(pcm24)
    n = int(len(src) * 2 / 3)
    out = array.array("h", [0]) * n
    for i in range(n):
        pos = i * 1.5
        j = int(pos)
        frac = pos - j
        a = src[j]
        b = src[j + 1] if j + 1 < len(src) else a
        out[i] = int(a + (b - a) * frac)
    return out.tobytes()


async def rumik_session(http: httpx.AsyncClient, model: str, language: str, text: str) -> dict:
    r = await http.post("/v1/tts/ws-connect", json={"model": model, "language": language, "text": text})
    if r.status_code >= 400:
        r = await http.post("/v1/tts/ws-connect", json={"model": model, "text": text})
    if r.status_code >= 400:
        raise RuntimeError(redact(f"{r.status_code} {r.text[:300]}"))
    return r.json()


async def synthesize_pcm(text: str, model: str = "mulberry", language: str = "hinglish") -> tuple[bytes, float | None]:
    """One text frame to PCM int16 24 kHz. Returns (pcm, ms to first audio)."""
    load_env()
    sys.path.insert(0, str(ROOT / "server"))
    from app.voice import ledger

    ledger.record(len(text), "script")
    async with httpx.AsyncClient(base_url=RUMIK, headers={"Authorization": f"Bearer {os.environ['RUMIK_API_KEY']}"}, timeout=60) as http:
        s = await rumik_session(http, model, language, text)
    pcm = bytearray()
    first = None
    started = time.perf_counter()
    async with websockets.connect(f"{s['ws_url']}?token={s['token']}", max_size=16_000_000) as ws:
        await ws.send(json.dumps({"text": text}))
        while True:
            m = await asyncio.wait_for(ws.recv(), timeout=60)
            if isinstance(m, bytes):
                if first is None:
                    first = (time.perf_counter() - started) * 1000
                pcm.extend(m)
                continue
            f = json.loads(m)
            if f.get("type") in {"done", "cancelled", "timeout"} or f.get("error"):
                break
        await ws.send(json.dumps({"type": "close"}))
    return bytes(pcm), first
