"""Build the synthetic speech set: Rumik narrations (quiet and noisy) and 20 noise clips.

Synthetic stand-in for recorded audio. Output goes to data/audio (git-ignored) with a manifest.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vendor import ROOT, pcm_to_wav, resample_16k, synthesize_pcm  # noqa: E402

DATA = ROOT / "workflows" / "evals" / "datasets"
OUT = ROOT / "server" / "data" / "audio"
random.seed(7)

CHATTER = [
    "Haan bhai, kal match dekha tha tumne? Kya zabardast khel tha, last over mein sab badal gaya.",
    "Please take the next left and then continue straight for two kilometres.",
    "Aaj sabzi mandi mein tamatar bahut mehnge hain, kuch samajh nahi aata.",
    "The meeting has been moved to four thirty, please update your calendars.",
    "Beta, khana kha lo, thanda ho raha hai. Phir padhai karna.",
    "Breaking news, the market closed higher today as investors welcomed the announcement.",
]


def samples(pcm: bytes) -> array.array:
    a = array.array("h")
    a.frombytes(pcm)
    return a


def rms(a: array.array) -> float:
    return math.sqrt(sum(x * x for x in a) / max(1, len(a)))


def noise(n: int, level: float) -> array.array:
    """Low-passed random noise at the given rms level."""
    out = array.array("h", [0]) * n
    prev = 0.0
    for i in range(n):
        prev = 0.9 * prev + 0.1 * random.gauss(0, 1)
        out[i] = max(-32768, min(32767, int(prev * level * 3)))
    return out


def mix(a: array.array, b: array.array, gain_b: float) -> array.array:
    out = array.array("h", [0]) * len(a)
    for i in range(len(a)):
        v = a[i] + (b[i] * gain_b if i < len(b) else 0)
        out[i] = max(-32768, min(32767, int(v)))
    return out


def wav16(a: array.array) -> bytes:
    return pcm_to_wav(a.tobytes(), 16000)


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"narrations": [], "noise": []}
    narrations = json.loads((DATA / "narrations.json").read_text(encoding="utf-8"))
    for item in narrations:
        pcm = b""
        for sentence in [x.strip() for x in re.split(r"(?<=[.?!])\s+", item["text"]) if x.strip()]:
            part, _ = await synthesize_pcm(sentence)
            pcm += part + bytes(2 * 7200)  # 300 ms gap at 24 kHz
        clean = samples(resample_16k(pcm))
        target = rms(clean) / (10 ** (12 / 20))  # about 12 dB signal to noise
        noisy = mix(clean, noise(len(clean), 1.0), 1.0)
        n = noise(len(clean), 1.0)
        scale = target / max(1.0, rms(n))
        noisy = mix(clean, n, scale)
        (OUT / f"{item['id']}-quiet.wav").write_bytes(wav16(clean))
        (OUT / f"{item['id']}-noisy.wav").write_bytes(wav16(noisy))
        manifest["narrations"].append({"id": item["id"], "seconds": round(len(clean) / 16000, 1)})
        print(item["id"], manifest["narrations"][-1]["seconds"], "s")

    rate = 16000
    clips = []
    for i in range(6):  # digital silence and very quiet hiss
        n = rate * (4 + i)
        clips.append((f"silence-{i+1}", "silence", noise(n, 2.0 * i) if i else array.array("h", [0]) * n))
    for i in range(8):  # room noise at rising levels
        clips.append((f"room-{i+1}", "room", noise(rate * 6, 80.0 * (i + 1))))
    for i, line in enumerate(CHATTER):  # background speech only, low level
        pcm, _ = await synthesize_pcm(line, language="hinglish" if i % 2 == 0 else "english")
        speech = samples(resample_16k(pcm))
        gain = 0.15
        base = noise(len(speech), 120.0)
        clips.append((f"background-{i+1}", "background_speech", mix(base, speech, gain)))
    for name, kind, a in clips:
        (OUT / f"{name}.wav").write_bytes(wav16(a))
        manifest["noise"].append({"id": name, "kind": kind, "seconds": round(len(a) / rate, 1)})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("clips", len(manifest["noise"]), "narrations", len(manifest["narrations"]))


if __name__ == "__main__":
    asyncio.run(main())
