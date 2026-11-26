import array
import math
import random

from app.voice.gate import is_known_hallucination, looks_like_speech


def _pcm(values):
    return array.array("h", [max(-32768, min(32767, int(v))) for v in values]).tobytes()


def _speechlike(seconds=3.0):
    out = []
    for i in range(int(16000 * seconds)):
        t = i / 16000
        envelope = 1.0 if (int(t * 4) % 2 == 0) else 0.03  # syllable-rate on/off
        out.append(5000 * envelope * math.sin(2 * math.pi * 180 * t))
    return _pcm(out)


def test_silence_is_not_speech():
    assert not looks_like_speech(_pcm([0] * 48000))


def test_steady_noise_is_not_speech():
    rng = random.Random(1)
    assert not looks_like_speech(_pcm(rng.gauss(0, 900) for _ in range(48000)))


def test_modulated_signal_is_speech():
    assert looks_like_speech(_speechlike())


def test_too_short_is_not_speech():
    assert not looks_like_speech(_pcm([4000] * 1000))


def test_known_hallucinations_are_dropped():
    assert is_known_hallucination("Thank you for watching.")
    assert is_known_hallucination(" . ")
    assert not is_known_hallucination("Mera refund abhi tak nahi aaya")
