"""Groq faults against a mocked transport: rate limits, withdrawn models, the spending cap."""

import json

import httpx
import pytest

from app.adapters import groq_llm
from app.adapters.cost import BudgetExceeded, CostMeter, shared_meter
from app.adapters.groq_llm import MAX_ATTEMPTS, MAX_WAIT_SECONDS, GroqClient, RateLimited
from app.adapters.groq_stt import GroqTranscriber
from tests.unit.test_groq_adapter import _client, _models, _ok

PRIMARY = "qwen/qwen3.8-27b"


def _sequence(*responses):
    seen: list[httpx.Request] = []
    items = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return items.pop(0) if len(items) > 1 else items[0]

    return handler, seen


def _429(retry_after=None):
    headers = {} if retry_after is None else {"retry-after": retry_after}
    return httpx.Response(429, headers=headers, json={"error": {"message": "rate limit"}})


# -- 429 ----------------------------------------------------------------------------------------------------------------


def test_two_429s_are_waited_out_with_backoff_and_the_third_try_succeeds():
    handler, seen = _sequence(_429(), _429(), _ok("done"))
    sleeps: list[float] = []
    text, _usage = _client(handler, sleeps=sleeps).text("draft", "p", {})
    assert text == "done" and len(seen) == 3
    assert sleeps == [0.5, 1.0]  # no Retry-After: our own delay, doubling


def test_retry_after_is_honoured():
    handler, _seen = _sequence(_429("3"), _ok("done"))
    sleeps: list[float] = []
    _client(handler, sleeps=sleeps).text("draft", "p", {})
    assert sleeps == [3.0]


def test_a_retry_after_that_is_not_a_number_does_not_crash_the_call():
    handler, _seen = _sequence(_429("Wed, 21 Oct 2026 07:28:00 GMT"), _ok("done"))
    sleeps: list[float] = []
    assert _client(handler, sleeps=sleeps).text("draft", "p", {})[0] == "done"
    assert sleeps == [0.5]


def test_giving_up_after_the_last_attempt_is_a_clear_busy_error_not_a_generic_failure():
    handler, seen = _sequence(_429("1"))
    sleeps: list[float] = []
    with pytest.raises(RateLimited) as caught:
        _client(handler, sleeps=sleeps).text("draft", "p", {})
    assert caught.value.code == "model_busy" and caught.value.status_code == 503
    assert len(seen) == MAX_ATTEMPTS and len(sleeps) == MAX_ATTEMPTS - 1


def test_a_very_long_retry_after_is_not_slept_through():
    handler, seen = _sequence(_429(str(int(MAX_WAIT_SECONDS) + 1)), _ok("never reached"))
    sleeps: list[float] = []
    with pytest.raises(RateLimited) as caught:
        _client(handler, sleeps=sleeps).text("draft", "p", {})
    assert sleeps == [] and len(seen) == 1  # a daily limit must not hold a request (or a call) for an hour
    assert caught.value.details["retry_after_seconds"] > MAX_WAIT_SECONDS


def test_the_listener_hears_each_wait_before_the_sleep_and_a_failing_listener_does_not_stop_the_retry():
    handler, _seen = _sequence(_429("2"), _429("4"), _ok("done"))
    events: list[tuple[str, float]] = []
    client = _client(handler, sleeps=None)
    client.sleeper = lambda seconds: events.append(("sleep", seconds))

    def listener(seconds):
        events.append(("heard", seconds))
        raise RuntimeError("listener bug")

    with client.watch_backoff(listener):
        assert client.text("draft", "p", {})[0] == "done"
    assert events == [("heard", 2.0), ("sleep", 2.0), ("heard", 4.0), ("sleep", 4.0)]


def test_the_listener_is_not_told_when_there_is_no_wait_and_is_scoped_to_the_block():
    handler, _seen = _sequence(_ok("one"), _429("1"), _ok("two"))
    heard: list[float] = []
    client = _client(handler)
    with client.watch_backoff(heard.append):
        client.text("draft", "p", {})
    assert heard == []
    client.text("draft", "p", {})  # outside the block: the 429 is waited out but nobody is told
    assert heard == []


def test_a_transcription_429_is_retried_and_sends_the_whole_clip_again():
    audio = b"RIFFfake-audio-bytes"
    bodies: list[int] = []
    answers = [_429("1"), httpx.Response(200, json={"duration": 1.0, "text": "refund", "segments": [{"text": "refund", "no_speech_prob": 0.0, "avg_logprob": -0.1, "compression_ratio": 1.0}]})]

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.count(b"RIFF"))
        return answers.pop(0)

    sleeps: list[float] = []
    out = GroqTranscriber(_client(handler, sleeps=sleeps)).transcribe("stt_turns", audio)
    assert out["text"] == "refund" and sleeps == [1.0] and bodies == [1, 1]


# -- a withdrawn model ---------------------------------------------------------------------------------------------------


def test_the_fallback_is_used_and_a_warning_is_logged_once_for_a_withdrawn_model(monkeypatch):
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body["model"])
        if body["model"] == PRIMARY:
            return httpx.Response(404, json={"error": {"message": "The model does not exist"}})
        return _ok("drafted", model=body["model"])

    notes: list[str] = []
    monkeypatch.setattr(groq_llm.log, "warning", lambda message, *args, **kw: notes.append(message % args if args else str(message)))
    client = _client(handler)
    assert client.text("draft", "p", {})[0] == "drafted"
    assert client.text("draft", "p", {})[0] == "drafted"
    assert requests == [PRIMARY, "openai/gpt-oss-120b", "openai/gpt-oss-120b"]  # the second call does not try the gone model again
    assert len([n for n in notes if "was rejected" in n]) == 1 and any(f"{PRIMARY} was rejected; using openai/gpt-oss-120b" in n for n in notes)


def test_the_fallback_model_is_not_sent_the_primary_models_reasoning_setting():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if body["model"] == PRIMARY:
            return httpx.Response(400, json={"error": {"message": "model not found"}})
        return _ok("drafted", model=body["model"])

    _client(handler).text("draft", "p", {})
    assert bodies[0].get("reasoning_effort") == "none" and "reasoning_effort" not in bodies[1]  # another family may refuse "none"


def test_when_the_fallback_is_gone_too_the_error_is_reported_not_looped():
    handler, seen = _sequence(httpx.Response(404, json={"error": {"message": "model does not exist"}}))
    with pytest.raises(groq_llm.ModelRejected):
        _client(handler).text("draft", "p", {})
    assert len(seen) == 2


# -- the spending cap ----------------------------------------------------------------------------------------------------


def test_the_call_that_crosses_the_cap_keeps_its_answer_and_the_next_one_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": PRIMARY, "choices": [{"message": {"content": "paid for"}}], "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0}})

    models = _models()
    models["prices"] = {PRIMARY: {"input_per_million": 1.0, "output_per_million": 1.0}}
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.groq.com/openai/v1")
    client = GroqClient(models, CostMeter(0.5), http, sleeper=lambda _s: None)
    assert client.text("draft", "p", {})[0] == "paid for"  # $1 spent against a $0.50 cap: the answer is not thrown away
    with pytest.raises(BudgetExceeded) as caught:
        client.text("draft", "p", {})
    assert caught.value.status_code == 402 and caught.value.code == "budget_exceeded"
    assert caught.value.details["limit_usd"] == 0.5 and caught.value.details["spent_usd"] == 1.0


def test_the_meter_is_one_per_app_so_chat_vision_and_speech_share_a_budget():
    from types import SimpleNamespace

    from app.config import Settings

    state = SimpleNamespace(settings=Settings(groq_budget_usd=3.0))
    assert shared_meter(state) is shared_meter(state) and shared_meter(state).limit_usd == 3.0
