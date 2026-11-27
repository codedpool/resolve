import array
import asyncio
import json
import math

import websockets

from app.voice.endpointer import Endpointer
from app.voice.sentences import MAX_CHARS, split_sentences
from app.voice.tts import RumikTTS, TTSFailed


def test_sentences_split_on_full_stops_and_the_hindi_danda():
    parts = split_sentences("Aapka order mil gaya hai. Kya aap refund chahte hain? हाँ, बिल्कुल पैसे वापस चाहिए।")
    assert len(parts) == 3 and parts[1].endswith("?") and parts[2].endswith("।")


def test_tiny_fragments_are_merged_and_long_text_is_cut_on_a_space():
    assert split_sentences("Ji. Samajh gaya, main dekhta hoon.") == ["Ji. Samajh gaya, main dekhta hoon."]
    long = " ".join(["word"] * 200)
    chunks = split_sentences(long)
    assert all(len(c) <= MAX_CHARS for c in chunks) and " ".join(chunks).split() == long.split()


def tone(seconds, amp=6000.0):
    out = array.array("h")
    for i in range(int(16000 * seconds)):
        out.append(int(amp * math.sin(2 * math.pi * 200 * i / 16000)))
    return out.tobytes()


def quiet(seconds):
    return bytes(int(16000 * seconds) * 2)


def test_endpointer_returns_one_utterance_after_the_pause():
    ep = Endpointer(pause_ms=700)
    events = ep.feed(quiet(0.3) + tone(1.0) + quiet(1.0))
    kinds = [e.kind for e in events]
    assert kinds == ["onset", "utterance"]
    assert 0.9 < len(events[1].pcm) / 32000 < 1.5  # the closing pause is trimmed to a short tail


def test_a_short_pause_inside_speech_does_not_split_it():
    ep = Endpointer(pause_ms=700)
    events = ep.feed(tone(0.6) + quiet(0.3) + tone(0.6) + quiet(1.0))
    assert [e.kind for e in events].count("utterance") == 1


def test_longer_narration_pause_tolerates_a_gap_that_a_turn_would_not():
    audio = tone(0.6) + quiet(1.0) + tone(0.6) + quiet(2.0)
    turns = [e for e in Endpointer(700).feed(audio) if e.kind == "utterance"]
    narration = [e for e in Endpointer(1500).feed(audio) if e.kind == "utterance"]
    assert len(turns) == 2 and len(narration) == 1


def test_clicks_shorter_than_the_minimum_are_dropped():
    ep = Endpointer(700)
    assert [e for e in ep.feed(quiet(0.2) + tone(0.06) + quiet(1.0)) if e.kind == "utterance"] == []


def test_frames_split_at_odd_boundaries_are_reassembled():
    ep = Endpointer(700)
    audio = quiet(0.2) + tone(1.0) + quiet(1.0)
    events = []
    for i in range(0, len(audio), 777):
        events += ep.feed(audio[i : i + 777])
    assert [e.kind for e in events].count("utterance") == 1


class FakeSocket:
    """Plays back a script of frames per request, and records what was sent."""

    def __init__(self, scripts):
        self.scripts, self.sent, self.queue, self.closed = list(scripts), [], asyncio.Queue(), False

    async def send(self, raw):
        frame = json.loads(raw)
        self.sent.append(frame)
        if "text" in frame:
            for item in self.scripts.pop(0):
                self.queue.put_nowait(item)

    async def recv(self):
        item = await self.queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.closed = True


def run(coro):
    return asyncio.run(coro)


def collect(tts, text):
    async def go():
        return [chunk async for chunk in tts.speak(text)]

    return run(go())


def test_frames_go_out_in_order_and_the_stream_ends_on_done():
    sock = FakeSocket([[b"a", b"b", json.dumps({"type": "done"})], [b"c", json.dumps({"type": "done"})]])

    async def connect():
        return sock

    tts = RumikTTS("key", connect=connect)

    async def go():
        first = [c async for c in tts.speak("one")]
        second = [c async for c in tts.speak("two")]
        return first, second

    first, second = run(go())
    assert first == [b"a", b"b"] and second == [b"c"]
    assert [f["text"] for f in sock.sent] == ["one", "two"]


def test_stale_frames_from_a_cancelled_request_are_drained_before_the_next_one():
    sock = FakeSocket([[b"x", json.dumps({"type": "done"})]])
    sock.queue.put_nowait(json.dumps({"type": "cancelled", "reason": "cancel"}))  # left over from the stopped request
    sock.queue.put_nowait(json.dumps({"type": "done"}))

    async def connect():
        return sock

    assert collect(RumikTTS("key", connect=connect), "next") == [b"x"]


def test_cancel_sends_a_cancel_frame():
    sock = FakeSocket([])

    async def connect():
        return sock

    tts = RumikTTS("key", connect=connect)

    async def go():
        await tts._ensure()
        await tts.cancel()

    run(go())
    assert sock.sent == [{"type": "cancel"}]


def test_an_idle_timeout_reconnects_and_retries_the_sentence():
    first = FakeSocket([[json.dumps({"type": "timeout"})]])
    second = FakeSocket([[b"ok", json.dumps({"type": "done"})]])
    sockets = [first, second]

    async def connect():
        return sockets.pop(0)

    tts = RumikTTS("key", connect=connect)
    assert collect(tts, "hello") == [b"ok"]
    assert tts.reconnects == 1 and second.sent[0]["text"] == "hello"


def test_a_connection_that_keeps_failing_raises():
    class Dead(FakeSocket):
        async def send(self, raw):
            raise websockets.ConnectionClosed(None, None)

    async def connect():
        return Dead([])

    try:
        collect(RumikTTS("key", connect=connect), "hello")
    except TTSFailed:
        return
    raise AssertionError("expected a failure")
