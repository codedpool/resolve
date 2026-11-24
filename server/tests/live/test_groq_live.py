"""One cheap structured call, one classify, and one transcription. Marked live."""

import io
import wave

import httpx
import pytest

from app.adapters.cost import CostMeter
from app.adapters.groq_llm import GroqClient
from app.adapters.groq_stt import GroqTranscriber
from app.config import get_settings

pytestmark = pytest.mark.live


def _wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    return buffer.getvalue()


def test_one_structured_call_one_classify_and_one_transcription():
    settings = get_settings()
    assert settings.groq_api_key
    http = httpx.Client(
        base_url="https://api.groq.com/openai/v1",
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        timeout=60,
    )
    client = GroqClient(settings.load_models(), CostMeter(settings.groq_budget_usd), http)
    parsed, _usage = client.structured(
        "extract",
        "Reply with the JSON object only.",
        {"utterance": "The order was about 1200 rupees."},
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "field": {"type": "string"},
                "value": {"type": "string"},
                "certainty": {"type": "string"},
            },
            "required": ["field", "value", "certainty"],
        },
    )
    assert parsed["certainty"]
    label, confidence, _usage = client.classify(
        "classify",
        "Pick one label.",
        "We have processed your refund.",
        ["resolved_claimed", "rejected", "needs_info"],
    )
    assert label in {"resolved_claimed", "rejected", "needs_info"}
    assert 0 <= confidence <= 1
    transcript = GroqTranscriber(client).transcribe("stt_turns", _wav())
    assert "text" in transcript
    assert client.meter.spent_usd < 0.05
    http.close()
