"""Voice calls: minting a call, the websocket gateway, and the kill switch."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import uuid
import wave
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.factory import get_llm
from app.adapters.fakes import FakeTranscriber
from app.adapters.groq_stt import GroqTranscriber
from app.core.errors import AppError
from app.db.models import Call, CallMode, CallRole, Fact, User, VoiceSession, VoiceState
from app.deps import current_user, get_session
from app.privacy.redact import Redactor
from app.services.access import owned_case
from app.services.intake_run import run_intake_event
from app.voice.budgets import CallBudget, KillSwitch, used_today
from app.voice.calls import consume_token, create_call
from app.voice.endpointer import Endpointer
from app.voice.gate import looks_like_speech
from app.voice.sentences import split_sentences
from app.voice.tts import RumikTTS, TTSEngine

log = logging.getLogger("resolve")
router = APIRouter(tags=["voice"])

NARRATION_PAUSE_MS = 1500
TURN_PAUSE_MS = 700
SILENCE_PROMPT_SECONDS = 25.0
PHASES = {"narrating": "narration", "asking": "gap_filling", "confirming": "confirming"}
CRITICAL = ("company_name", "amount", "order_id", "order_date", "desired_remedy")


class CallBody(BaseModel):
    case_id: uuid.UUID
    role: CallRole = CallRole.consumer


def _kill(app) -> KillSwitch:
    if getattr(app.state, "voice_kill", None) is None:
        app.state.voice_kill = KillSwitch()
    return app.state.voice_kill


@router.post("/calls", status_code=201)
def start_call(body: CallBody, request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    if _kill(request.app).engaged:
        raise AppError("voice_disabled", "Voice calls are switched off right now", status_code=503)
    case = owned_case(session, user, body.case_id)
    now = request.app.state.clock.now()
    stt_used, tts_used = used_today(session, user.id, now)
    settings = request.app.state.settings
    if stt_used >= settings.voice_daily_stt_seconds or tts_used >= settings.voice_daily_tts_chars:
        raise AppError("daily_voice_limit", "You have used today's voice time. Please use text, or try again tomorrow", status_code=429)
    call, voice, token = create_call(session, user, case, body.role, now)
    scheme = "wss" if request.url.scheme == "https" else "ws"
    return {"call_id": str(call.id), "ws_url": f"{scheme}://{request.url.netloc}/voice/ws", "ws_token": token, "expires_in": 60}


@router.post("/calls/{call_id}/end")
def end_call(call_id: uuid.UUID, request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    existing = session.get(Call, call_id)
    if existing is not None and existing.mode == CallMode.text:  # a text provider call has no voice session
        from app.api.outreach import end_text_call

        return end_text_call(request, session, user, call_id)
    voice = session.scalar(select(VoiceSession).where(VoiceSession.call_id == call_id, VoiceSession.user_id == user.id))
    if voice is None:
        raise AppError("not_found", "Call was not found", status_code=404)
    if voice.state in {VoiceState.created, VoiceState.active}:
        voice.state = VoiceState.closed
        voice.ended_at = request.app.state.clock.now()
    return {"call_id": str(call_id), "state": voice.state.value}


@router.post("/admin/kill-voice")
def kill_voice(request: Request, session: Session = Depends(get_session)) -> dict:
    """Development switch: no new calls, every open call closes. Not available outside dev and test."""
    if request.app.state.settings.app_env not in {"dev", "test"}:
        raise AppError("not_found", "Not found", status_code=404)
    _kill(request.app).engaged = True
    for voice in session.scalars(select(VoiceSession).where(VoiceSession.state.in_([VoiceState.created, VoiceState.active]))):
        voice.state = VoiceState.killed
        voice.ended_at = request.app.state.clock.now()
    return {"engaged": True}


def _wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(pcm)
    return buf.getvalue()


class CallRunner:
    """One open call: audio in, captions and agent speech out. Everything slow runs off the event loop."""

    def __init__(self, ws: WebSocket, voice_id: uuid.UUID, user_id: uuid.UUID, case_id: uuid.UUID, role: CallRole,
                 tts: TTSEngine, stt, budget: CallBudget, now=time.monotonic) -> None:
        self.ws, self.voice_id, self.user_id, self.case_id, self.role = ws, voice_id, user_id, case_id, role
        self.tts, self.stt, self.budget, self.now = tts, stt, budget, now
        self.app = ws.app
        self.kill = _kill(self.app)
        self.endpointer = Endpointer(NARRATION_PAUSE_MS)
        self.phase = "narration"
        self.muted = False
        self.queue: asyncio.Queue = asyncio.Queue()
        self.speech: asyncio.Task | None = None
        self.interrupted: str | None = None
        self.cards_sent = False
        self.said_anything = False
        self.silence_prompted = False
        self.last_speech = self.now()
        self.closed = False
        self.holder = SimpleNamespace(app=self.app)

    # -- output ---------------------------------------------------------------
    async def send(self, payload: dict) -> None:
        if not self.closed:
            await self.ws.send_text(json.dumps(payload))

    async def close(self, reason: str) -> None:
        if self.closed:
            return
        await self.send({"type": "closed", "reason": reason})
        self.closed = True
        if self.speech and not self.speech.done():
            self.speech.cancel()
        await self.tts.close()
        try:
            await self.ws.close()
        except RuntimeError:
            pass

    async def say(self, text: str) -> None:
        for sentence in split_sentences(text):
            if self.closed:
                return
            if self.budget.over_chars():
                await self.close("speech_budget")
                return
            self.budget.tts_chars += len(sentence)
            await self.send({"type": "caption", "who": "agent", "text": sentence, "final": True})
            self.interrupted = sentence
            async for chunk in self.tts.speak(sentence):
                await self.ws.send_bytes(chunk)
            self.interrupted = None

    def start_speaking(self, text: str) -> None:
        self.speech = asyncio.create_task(self.say(text))

    async def barge_in(self) -> None:
        if self.speech and not self.speech.done():
            await self.tts.cancel()
            self.speech.cancel()
            await self.send({"type": "flush"})
            log.info("agent speech interrupted by the caller")

    async def wait_speech(self) -> None:
        if self.speech:
            try:
                await self.speech
            except asyncio.CancelledError:
                pass

    # -- the turn driver ------------------------------------------------------
    def _graph(self, event: str, text: str) -> dict:
        factory = self.app.state.session_factory
        session = factory()
        try:
            user = session.get(User, self.user_id)
            out = run_intake_event(self.holder, session, user, self.case_id, event, text)
            if out["phase"] == "confirming":
                rows = session.scalars(select(Fact).where(Fact.case_id == self.case_id, Fact.superseded_by.is_(None))).all()
                out["fact_ids"] = [str(r.id) for r in rows if r.field in CRITICAL]
            session.commit()
            return out
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def step(self, event: str, text: str = "") -> None:
        out = await asyncio.to_thread(self._graph, event, text)
        phase = PHASES.get(out["phase"], self.phase)
        if phase != self.phase:
            self.phase = phase
            self.endpointer.set_pause(NARRATION_PAUSE_MS if phase == "narration" else TURN_PAUSE_MS)
            await self.send({"type": "phase", "phase": phase})
        if out.get("text"):
            self.start_speaking(out["text"])
            await self.wait_speech()
        if out["phase"] == "confirming" and not self.cards_sent:
            self.cards_sent = True
            for fact_id in out.get("fact_ids", []):  # confirmation is only ever an explicit tap on the card
                await self.send({"type": "card", "kind": "confirm_field", "fact_id": fact_id})

    async def handle_utterance(self, pcm: bytes) -> None:
        if not looks_like_speech(pcm):
            return
        role = "stt_narration" if self.phase == "narration" else "stt_turns"
        self.budget.stt_seconds += len(pcm) / 32000
        result = await asyncio.to_thread(self.stt.transcribe, role, _wav(pcm))
        text = (result.get("text") or "").strip()
        if not text:
            return
        shown = Redactor().redact_or_withhold(text)
        await self.send({"type": "caption", "who": "user", "text": shown.text if not shown.withheld else "[hidden]", "final": True})
        self.said_anything = True
        await self.step("message", text)

    async def worker(self) -> None:
        while True:
            item = await self.queue.get()
            if item is None:
                return
            try:
                await item()
            except Exception:  # noqa: BLE001 - one bad turn must not end the call
                log.exception("voice turn failed")
                await self.send({"type": "error", "code": "turn_failed"})

    # -- main loop ------------------------------------------------------------
    async def run(self) -> None:
        self.kill.live.add(self)
        worker = asyncio.create_task(self.worker())
        await self.send({"type": "ready", "rate_in": 16000, "rate_out": 24000})
        try:
            while not self.closed:
                if self.kill.engaged:
                    await self.close("voice_disabled")
                    break
                if self.budget.over_time(self.now()):
                    await self.close("call_time")
                    break
                try:
                    message = await asyncio.wait_for(self.ws.receive(), timeout=0.25)
                except asyncio.TimeoutError:
                    await self._idle()
                    continue
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await self._audio(message["bytes"])
                elif message.get("text") is not None:
                    if await self._control(json.loads(message["text"])):
                        break
        except WebSocketDisconnect:
            pass
        finally:
            self.kill.live.discard(self)
            await self.queue.put(None)
            await worker
            if self.speech and not self.speech.done():
                self.speech.cancel()
            await self.tts.close()

    async def _audio(self, frame: bytes) -> None:
        if self.muted:
            return
        for event in self.endpointer.feed(frame):
            if event.kind == "onset":
                self.last_speech = self.now()
                self.silence_prompted = False
                await self.barge_in()
            else:
                pcm = event.pcm
                await self.queue.put(lambda pcm=pcm: self.handle_utterance(pcm))

    async def _idle(self) -> None:
        if (self.phase == "narration" and self.said_anything and not self.silence_prompted
                and self.now() - self.last_speech >= SILENCE_PROMPT_SECONDS and self.queue.empty()):
            self.silence_prompted = True
            await self.queue.put(lambda: self.step("silence"))

    async def _control(self, frame: dict) -> bool:
        kind = frame.get("type")
        if kind == "start":
            await self.send({"type": "phase", "phase": self.phase})
        elif kind == "done_narration":
            for event in self.endpointer.flush():
                if event.kind == "utterance":
                    pcm = event.pcm
                    await self.queue.put(lambda pcm=pcm: self.handle_utterance(pcm))
            await self.queue.put(lambda: self.step("done"))
        elif kind == "mute":
            self.muted = bool(frame.get("on"))
        elif kind == "playback_flushed":
            pass
        elif kind == "end":
            await self.close("ended")
            return True
        return False


def _make_tts(app) -> TTSEngine:
    factory = getattr(app.state, "voice_tts_factory", None)
    if factory is not None:
        return factory()
    models = app.state.settings.load_models().get("tts", {})
    return RumikTTS(app.state.settings.rumik_api_key, models.get("model", "mulberry"), models.get("language", "hinglish"))


def _make_stt(app):
    stt = getattr(app.state, "voice_stt", None)
    if stt is not None:
        return stt
    return GroqTranscriber(get_llm(SimpleNamespace(app=app)))


def _open(app, token: str):
    """Validates the token and daily budgets. Returns (voice session, user id, budget)."""
    factory = app.state.session_factory
    session = factory()
    try:
        try:
            voice = consume_token(session, token, app.state.clock.now())
        finally:
            session.commit()
        if _kill(app).engaged:
            raise AppError("voice_disabled", "Voice calls are switched off right now", status_code=503)
        if voice.role != CallRole.consumer:
            raise AppError("role_not_supported", "This call role is not available yet", status_code=400)
        stt_used, tts_used = used_today(session, voice.user_id, app.state.clock.now())
        settings = app.state.settings
        if stt_used >= settings.voice_daily_stt_seconds or tts_used >= settings.voice_daily_tts_chars:
            raise AppError("daily_voice_limit", "Daily voice limit reached", status_code=429)
        return voice.id, voice.user_id, voice.case_id, voice.role
    finally:
        session.close()


def _finish(app, voice_id: uuid.UUID, runner: CallRunner) -> None:
    session = app.state.session_factory()
    try:
        voice = session.get(VoiceSession, voice_id)
        if voice is not None:
            if voice.state == VoiceState.active:
                voice.state = VoiceState.killed if _kill(app).engaged else VoiceState.closed
            voice.ended_at = app.state.clock.now()
            voice.stt_seconds = runner.budget.stt_seconds
            voice.tts_characters = runner.budget.tts_chars
        session.commit()
    finally:
        session.close()


@router.websocket("/voice/ws")
async def voice_ws(ws: WebSocket, token: str = "") -> None:
    app = ws.app
    try:
        voice_id, user_id, case_id, role = await asyncio.to_thread(_open, app, token)
    except AppError:
        await ws.close(code=4401)
        return
    await ws.accept()
    settings = app.state.settings
    budget = CallBudget(settings.voice_max_call_seconds, settings.voice_daily_tts_chars, time.monotonic())
    runner = CallRunner(ws, voice_id, user_id, case_id, role, _make_tts(app), _make_stt(app), budget,
                        now=getattr(app.state, "voice_time", time.monotonic))
    runner.budget.started_at = runner.now()
    try:
        await runner.run()
    finally:
        await asyncio.to_thread(_finish, app, voice_id, runner)


_ = FakeTranscriber
