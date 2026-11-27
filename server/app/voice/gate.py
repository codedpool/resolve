"""Pre-transcription gate. Whisper invents text on silence and steady noise, and its own
confidence numbers do not separate that from speech (measured in docs/results/s0.3-bakeoff.md),
so audio that does not look like speech never reaches it.

The test is energy modulation: speech alternates loud and quiet 30 ms frames, steady noise does not.
This is the fallback detector. A trained VAD can replace it behind the same `looks_like_speech` call.
"""

from __future__ import annotations

import array
import math

FRAME = 480  # 30 ms at 16 kHz
MIN_LOUD_RMS = 120.0
MIN_RATIO = 4.0
MIN_SPEECH_FRAMES = 8

KNOWN_HALLUCINATIONS = (
    "thank you for watching",
    "thanks for watching",
    "takk for watching",
    "subscribe to",
    "kansai international airport",
    "please subscribe",
    "dhanyavad dekhne ke liye",
    "देखने के लिए धन्यवाद",
    "सब्सक्राइब",
)


def frame_energies(pcm16: bytes) -> list[float]:
    samples = array.array("h")
    samples.frombytes(pcm16[: len(pcm16) - (len(pcm16) % 2)])
    out = []
    for start in range(0, len(samples) - FRAME + 1, FRAME):
        chunk = samples[start : start + FRAME]
        out.append(math.sqrt(sum(x * x for x in chunk) / FRAME))
    return out


def looks_like_speech(pcm16: bytes) -> bool:
    energies = frame_energies(pcm16)
    if len(energies) < MIN_SPEECH_FRAMES:
        return False
    ordered = sorted(energies)
    low = ordered[int(len(ordered) * 0.1)]
    high = ordered[int(len(ordered) * 0.9)]
    if high < MIN_LOUD_RMS:
        return False
    loud = sum(1 for e in energies if e > max(MIN_LOUD_RMS, low * MIN_RATIO))
    return high / max(low, 1.0) >= MIN_RATIO and loud >= MIN_SPEECH_FRAMES


def is_known_hallucination(text: str) -> bool:
    lowered = text.strip().lower().strip(".! ")
    if not lowered:
        return True
    return any(phrase in lowered for phrase in KNOWN_HALLUCINATIONS)
