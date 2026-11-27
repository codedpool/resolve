"""Speech synthesis over one long-lived Rumik websocket per call.

One frame per sentence. A frame sent while another is generating replaces it; `cancel` stops it with no
replacement. Frames that belong to a stopped request can still arrive, so stale frames are drained before
each new request instead of treating the first `done` as the answer to the next one.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx
import websockets

from app.voice import ledger

RUMIK_BASE = "https://silk-api.rumik.ai"


class TTSEngine(Protocol):
    async def speak(self, text: str) -> AsyncIterator[bytes]: ...

    async def cancel(self) -> None: ...

    async def close(self) -> None: ...


class TTSFailed(Exception):
    pass


class RumikTTS:
    def __init__(self, api_key: str, model: str = "mulberry", language: str = "hinglish", base: str = RUMIK_BASE, connect=None) -> None:
        self.api_key, self.model, self.language, self.base = api_key, model, language, base
        self._connect_fn = connect or self._real_connect
        self._ws = None
        self.reconnects = 0

    async def _real_connect(self):
        async with httpx.AsyncClient(base_url=self.base, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=30) as http:
            reply = await http.post("/v1/tts/ws-connect", json={"model": self.model, "language": self.language, "text": "Namaste."})
            if reply.status_code >= 400:
                reply = await http.post("/v1/tts/ws-connect", json={"model": self.model, "text": "Namaste."})
            if reply.status_code >= 400:
                raise TTSFailed(f"mint failed with status {reply.status_code}")
            session = reply.json()
        return await websockets.connect(f"{session['ws_url']}?token={session['token']}", max_size=16_000_000, ping_interval=None)

    async def _ensure(self):
        if self._ws is None:
            self._ws = await self._connect_fn()
        return self._ws

    async def _drain(self, ws) -> None:
        while True:
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.05)
            except asyncio.TimeoutError:
                return

    async def speak(self, text: str) -> AsyncIterator[bytes]:
        if self._connect_fn == self._real_connect:  # only real synthesis is counted, never a test double
            ledger.record(len(text))
        for attempt in range(2):
            ws = await self._ensure()
            try:
                await self._drain(ws)
                await ws.send(json.dumps({"text": text}))
                while True:
                    message = await asyncio.wait_for(ws.recv(), timeout=30)
                    if isinstance(message, bytes):
                        yield message
                        continue
                    frame = json.loads(message)
                    if frame.get("type") in {"done", "cancelled"}:
                        return
                    if frame.get("type") == "timeout":
                        raise websockets.ConnectionClosed(None, None)  # idle timeout: reconnect and retry the sentence
                    if frame.get("error"):
                        if frame.get("recoverable"):
                            return
                        raise TTSFailed(str(frame.get("code")))
            except websockets.ConnectionClosed:
                self._ws = None
                self.reconnects += 1
                if attempt == 1:
                    raise TTSFailed("connection lost") from None
            else:
                return

    async def cancel(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "cancel"}))
            except websockets.ConnectionClosed:
                self._ws = None

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "close"}))
                await self._ws.close()
            except websockets.ConnectionClosed:
                pass
            self._ws = None


class FakeTTS:
    """Yields fixed chunks per sentence. Used by tests; never touches the network."""

    def __init__(self, chunks: int = 3, chunk_bytes: int = 960) -> None:
        self.chunks, self.chunk_bytes = chunks, chunk_bytes
        self.spoken: list[str] = []
        self.cancels = 0
        self.closed = False
        self._stop = False

    async def speak(self, text: str) -> AsyncIterator[bytes]:
        self._stop = False
        self.spoken.append(text)
        for _ in range(self.chunks):
            if self._stop:
                return
            yield b"\x01\x00" * (self.chunk_bytes // 2)
            await asyncio.sleep(0.01)

    async def cancel(self) -> None:
        self.cancels += 1
        self._stop = True

    async def close(self) -> None:
        self.closed = True
