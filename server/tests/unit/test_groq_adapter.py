"""Groq adapter behaviour against a mocked HTTP transport."""

import json

import httpx

from app.adapters.cost import BlockedApiAccess, BudgetExceeded, CostMeter
from app.adapters.fakes import FakeLLM, FakeTranscriber
from app.adapters.groq_llm import GroqClient
from app.adapters.groq_stt import GroqTranscriber
from app.config import Settings


def _models():
    return Settings(models_path=Settings().models_path).load_models()


def _client(handler, limit=20.0, sleeps=None):
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.groq.com/openai/v1")
    return GroqClient(_models(), CostMeter(limit), http, sleeper=(sleeps.append if sleeps is not None else (lambda _seconds: None)))


def _ok(content: str, model: str = "qwen/qwen3.8-27b"):
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def test_retry_after_429_then_success():
    seen = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        if seen["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "1.5"}, json={"error": {"message": "slow down"}})
        return _ok(json.dumps({"value": "phone"}))

    client = _client(handler, sleeps=sleeps)
    parsed, usage = client.structured("extract", "extract_fact", {"text": "phone"}, {"type": "object"})
    assert parsed["value"] == "phone"
    assert usage["prompt_tokens"] == 10
    assert sleeps == [1.5]
    assert seen["n"] == 2


def test_withdrawn_model_falls_back_and_warns():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["model"] == "qwen/qwen3.8-27b":
            return httpx.Response(400, json={"error": {"message": "model does not exist"}})
        return _ok("drafted", model=body["model"])

    from app.adapters import groq_llm

    notes: list[str] = []
    real = groq_llm.log.warning

    def spy(message, *args, **kwargs):
        notes.append(message % args if args else str(message))
        return real(message, *args, **kwargs)

    groq_llm.log.warning = spy
    client = _client(handler)
    try:
        text, _usage = client.text("draft", "draft_reply", {"case": "1"})
    finally:
        groq_llm.log.warning = real
    assert text == "drafted"
    assert any("using openai/gpt-oss-120b" in line for line in notes)


def test_budget_blocks_before_the_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("request was sent after the budget was closed")

    client = _client(handler, limit=0)
    try:
        client.text("draft", "draft_reply", {})
    except BudgetExceeded:
        return
    raise AssertionError("budget did not stop the call")


def test_blocked_api_access_is_a_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "blocked_api_access", "message": "blocked_api_access"}})

    client = _client(handler)
    try:
        client.text("draft", "draft_reply", {})
    except BlockedApiAccess:
        return
    raise AssertionError("blocked call was not reported")


def test_whisper_drops_a_hallucinated_segment():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "duration": 2.0,
                "text": "refund thanks for watching",
                "segments": [
                    {"text": "refund", "no_speech_prob": 0.1, "avg_logprob": -0.2, "compression_ratio": 1.1},
                    {"text": " thanks for watching", "no_speech_prob": 0.9, "avg_logprob": -0.2, "compression_ratio": 1.1},
                ],
            },
        )

    transcriber = GroqTranscriber(_client(handler))
    result = transcriber.transcribe("stt_turns", b"RIFFfake")
    assert result["text"] == "refund"
    assert result["dropped_segments"] == 1


def test_fakes_do_not_need_a_network():
    llm = FakeLLM(parsed={"field": "amount"})
    parsed, _usage = llm.structured("extract", "extract_fact", {}, {"type": "object"})
    assert parsed["field"] == "amount"
    assert FakeTranscriber("hello").transcribe("stt_turns", b"")["text"] == "hello"
