"""Live Rumik smoke test. Reads RUMIK_API_KEY from the environment or the repo-root .env.

Saves short WAVs and a secret-free JSON report. Never prints the key or websocket token.
"""

from __future__ import annotations

import asyncio
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
OUT = ROOT / "docs" / "results" / "s0.2-rumik.json"
AUDIO = ROOT / "docs" / "results" / "s0.2-audio"
BASE = "https://silk-api.rumik.ai"

SENTENCES = (
    ("mulberry", "hinglish", "Aapka refund abhi tak nahi aaya hai.", "hinglish-mulberry.wav"),
    ("mulberry", "hindi", "आपका रिफंड अभी तक नहीं आया है।", "hindi-mulberry.wav"),
    ("muga", "hinglish", "Aapka refund abhi tak nahi aaya hai.", "hinglish-muga.wav"),
    ("muga", "hindi", "आपका रिफंड अभी तक नहीं आया है।", "hindi-muga.wav"),
)


def load_env(path: Path) -> None:
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
    text = re.sub(r"gsk_[A-Za-z0-9]+", "[redacted]", text)
    return text


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(pcm)


async def collect(ws, timeout: float = 30) -> tuple[bytes, list[dict], float | None]:
    pcm = bytearray()
    frames: list[dict] = []
    first_audio_ms = None
    started = time.perf_counter()
    while True:
        message = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(message, bytes):
            if first_audio_ms is None:
                first_audio_ms = (time.perf_counter() - started) * 1000
            pcm.extend(message)
            continue
        frame = json.loads(message)
        frames.append({k: frame.get(k) for k in ("type", "reason", "error", "code", "credits_used") if k in frame})
        if frame.get("error") and frame.get("recoverable") is not True:
            break
        if frame.get("type") in {"done", "cancelled", "timeout"} or frame.get("error"):
            break
    return bytes(pcm), frames, first_audio_ms


async def mint(client: httpx.AsyncClient, body: dict) -> dict:
    response = await client.post("/v1/tts/ws-connect", json=body)
    if response.status_code >= 400:
        raise RuntimeError(redact(f"{response.status_code} {response.text[:400]}"))
    payload = response.json()
    return {
        "ws_url": payload["ws_url"],
        "token": payload["token"],
        "expires_in": payload.get("expires_in"),
    }


async def synthesize(client: httpx.AsyncClient, model: str, language: str, text: str, path: Path) -> dict:
    note = "text and language sent on mint"
    try:
        session = await mint(client, {"model": model, "language": language, "text": text})
    except RuntimeError as exc:
        note = f"mint with language failed ({exc}); retried with text only"
        session = await mint(client, {"model": model, "text": text})
    started = time.perf_counter()
    async with websockets.connect(f"{session['ws_url']}?token={session['token']}", max_size=8_000_000) as ws:
        await ws.send(json.dumps({"text": text}))
        pcm, frames, first_audio = await collect(ws)
        await ws.send(json.dumps({"type": "close"}))
    write_wav(path, pcm)
    return {
        "model": model,
        "language": language,
        "note": note,
        "expires_in": session["expires_in"],
        "time_to_first_audio_ms": None if first_audio is None else round(first_audio, 1),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "pcm_bytes": len(pcm),
        "wav": str(path.relative_to(ROOT)).replace("\\", "/"),
        "frames": frames,
    }


async def interrupt(client: httpx.AsyncClient) -> dict:
    session = await mint(
        client,
        {
            "model": "mulberry",
            "language": "hinglish",
            "text": "Aapka refund abhi tak nahi aaya hai.",
        },
    )
    async with websockets.connect(f"{session['ws_url']}?token={session['token']}", max_size=8_000_000) as ws:
        await ws.send(json.dumps({"text": "Aapka refund abhi tak nahi aaya hai, aur main poori baat dheere dheere dohra raha hoon."}))
        await asyncio.wait_for(ws.recv(), timeout=20)
        await ws.send(json.dumps({"text": "Theek hai, main rukta hoon."}))
        interrupt_frames = []
        saw_audio = False
        deadline = time.perf_counter() + 25
        while time.perf_counter() < deadline:
            message = await asyncio.wait_for(ws.recv(), timeout=20)
            if isinstance(message, bytes):
                saw_audio = True
                continue
            frame = json.loads(message)
            interrupt_frames.append({k: frame[k] for k in ("type", "reason", "error", "code") if k in frame})
            if frame.get("type") == "done":
                break
        await ws.send(json.dumps({"text": "Ek aur vakya."}))
        await asyncio.wait_for(ws.recv(), timeout=20)
        await ws.send(json.dumps({"type": "cancel"}))
        cancel_frames = []
        deadline = time.perf_counter() + 15
        while time.perf_counter() < deadline:
            message = await asyncio.wait_for(ws.recv(), timeout=15)
            if isinstance(message, bytes):
                continue
            frame = json.loads(message)
            cancel_frames.append({k: frame[k] for k in ("type", "reason", "error", "code") if k in frame})
            if frame.get("type") in {"cancelled", "done", "timeout"} or frame.get("error"):
                break
        await ws.send(json.dumps({"type": "close"}))
    return {
        "replacement_produced_audio": saw_audio,
        "interrupt_frames": interrupt_frames,
        "cancel_frames": cancel_frames,
    }


async def main_async() -> int:
    load_env(ROOT / ".env")
    key = os.environ.get("RUMIK_API_KEY", "")
    if not key:
        print("RUMIK_API_KEY is missing", file=sys.stderr)
        return 1
    AUDIO.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {key}"}
    report: dict = {"failures": []}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=60) as client:
        for name, path in (("voices", "/v1/voices"), ("limits", "/v1/agent/limits")):
            response = await client.get(path)
            body = response.json() if response.content else {}
            if response.status_code >= 400:
                report["failures"].append(f"{name}: {redact(response.text[:300])}")
            report[name] = body if response.status_code < 400 else {"status": response.status_code}

        report["syntheses"] = []
        for model, language, text, filename in SENTENCES:
            try:
                report["syntheses"].append(
                    await synthesize(client, model, language, text, AUDIO / filename)
                )
            except Exception as exc:  # noqa: BLE001
                report["failures"].append(f"{model}/{language}: {redact(str(exc))}")

        try:
            report["barge_in"] = await interrupt(client)
        except Exception as exc:  # noqa: BLE001
            report["failures"].append(f"barge-in: {redact(str(exc))}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"failures={len(report['failures'])}")
    for failure in report["failures"]:
        print(failure)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
