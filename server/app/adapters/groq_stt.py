"""Whisper transcription. Segments that look like silence are dropped."""

from __future__ import annotations

import io
import logging
import wave

import httpx

from app.adapters.cost import audio_cost
from app.adapters.groq_llm import GroqClient
from app.core.errors import AppError
from app.voice.gate import is_known_hallucination, looks_like_speech

log = logging.getLogger("resolve")


def _hallucinated(segment: dict, limits: dict) -> bool:
    if float(segment.get("no_speech_prob") or 0) > float(limits.get("max_no_speech_prob") or 1):
        return True
    if float(segment.get("avg_logprob") or 0) < float(limits.get("min_avg_logprob") or -99):
        return True
    if float(segment.get("compression_ratio") or 0) > float(limits.get("max_compression_ratio") or 99):
        return True
    return False


class GroqTranscriber:
    def __init__(self, client: GroqClient) -> None:
        self.client = client

    def transcribe(self, role: str, audio: bytes, filename: str = "clip.wav") -> dict:
        self.client.meter.ensure_open()
        if not self._speech(audio):
            return {"text": "", "dropped_segments": 0, "duration_seconds": 0.0, "skipped": "no_speech"}
        spec = self.client.models["roles"][role]
        model = spec["model"]
        language = (self.client.models.get("stt") or {}).get("language")
        data = {"model": model, "response_format": "verbose_json", "temperature": "0"}
        if language:
            data["language"] = language
        response = self.client.http.post(
            "/audio/transcriptions",
            data=data,
            files={"file": (filename, io.BytesIO(audio), "audio/wav")},
        )
        if response.status_code >= 400:
            raise AppError("groq_error", "Groq transcription failed", status_code=502, details={"status": response.status_code})
        payload = response.json()
        limits = ((self.client.models.get("stt") or {}).get("hallucination") or {})
        kept = []
        dropped = 0
        for segment in payload.get("segments") or []:
            if _hallucinated(segment, limits):
                dropped += 1
                continue
            kept.append(segment.get("text") or "")
        seconds = float(payload.get("duration") or 0)
        usage_usd = audio_cost(self.client.models.get("prices") or {}, model, seconds)
        self.client.meter.add(usage_usd)
        text = "".join(kept).strip()
        if is_known_hallucination(text):
            text = ""
        log.info("whisper model=%s seconds=%s dropped=%s", model, seconds, dropped)
        return {"text": text, "dropped_segments": dropped, "duration_seconds": seconds}

    @staticmethod
    def _speech(audio: bytes) -> bool:
        try:
            with wave.open(io.BytesIO(audio)) as handle:
                if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
                    return True
                return looks_like_speech(handle.readframes(handle.getnframes()))
        except (wave.Error, EOFError):
            return True
