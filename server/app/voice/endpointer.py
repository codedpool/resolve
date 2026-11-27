"""Turns a stream of 16 kHz PCM16 frames into utterances.

A frame is speech when its energy rises well above the running noise floor. An utterance ends after enough
trailing silence (longer while the consumer is narrating, shorter in a turn-by-turn exchange). `onset` reports
the first speech frame so the gateway can cut off agent speech (barge-in).
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass

RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = RATE * FRAME_MS // 1000
MIN_RMS = 150.0
RATIO = 3.0
MIN_SPEECH_MS = 240
MAX_UTTERANCE_S = 25.0


@dataclass
class Event:
    kind: str  # onset | utterance
    pcm: bytes = b""


class Endpointer:
    def __init__(self, pause_ms: int = 700) -> None:
        self.pause_ms = pause_ms
        self.floor = 0.0
        self._buffer = bytearray()
        self._pending = b""
        self._in_speech = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._announced = False
        self._calm = 0

    def set_pause(self, pause_ms: int) -> None:
        self.pause_ms = pause_ms

    def reset(self) -> None:
        self._buffer.clear()
        self._in_speech = False
        self._speech_frames = self._silence_frames = 0
        self._announced = False

    @staticmethod
    def _rms(frame: bytes) -> float:
        samples = array.array("h")
        samples.frombytes(frame)
        return math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))

    def feed(self, pcm: bytes) -> list[Event]:
        events: list[Event] = []
        data = self._pending + pcm
        step = FRAME_SAMPLES * 2
        usable = len(data) - (len(data) % step)
        self._pending = data[usable:]
        for start in range(0, usable, step):
            frame = data[start : start + step]
            energy = self._rms(frame)
            speech = energy > max(MIN_RMS, self.floor * RATIO)
            if not speech:  # the floor follows quiet frames only, so speech never raises it
                self.floor = energy if self.floor == 0 else 0.95 * self.floor + 0.05 * energy
            if speech:
                self._speech_frames += 1
                self._silence_frames = 0
                if not self._in_speech:
                    self._in_speech = True
                if not self._announced and self._speech_frames * FRAME_MS >= 90:
                    self._announced = True
                    events.append(Event("onset"))
                self._buffer.extend(frame)
            elif self._in_speech:
                self._silence_frames += 1
                self._buffer.extend(frame)
                if self._silence_frames * FRAME_MS >= self.pause_ms:
                    events.extend(self._finish())
            if self._in_speech and len(self._buffer) / (RATE * 2) >= MAX_UTTERANCE_S:
                events.extend(self._finish())
        return events

    def flush(self) -> list[Event]:
        return self._finish() if self._in_speech else []

    def _finish(self) -> list[Event]:
        keep_tail = min(self._silence_frames, 5)  # about 150 ms of the closing pause, so words are not clipped
        drop = (self._silence_frames - keep_tail) * FRAME_SAMPLES * 2
        pcm = bytes(self._buffer[: len(self._buffer) - drop]) if drop > 0 else bytes(self._buffer)
        voiced_ms = self._speech_frames * FRAME_MS
        self.reset()
        return [Event("utterance", pcm)] if voiced_ms >= MIN_SPEECH_MS else []
