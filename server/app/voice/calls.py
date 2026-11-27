"""Calls, voice sessions and their single-use connection tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Call, CallMode, CallRole, Case, User, VoiceSession, VoiceState

TOKEN_SECONDS = 60


def _token_id(token: str) -> uuid.UUID:
    return uuid.UUID(bytes=hashlib.sha256(token.encode()).digest()[:16])


def create_call(session: Session, user: User, case: Case, role: CallRole, now: datetime) -> tuple[Call, VoiceSession, str]:
    call = Call(case_id=case.id, role=role, mode=CallMode.voice, simulated=True)
    session.add(call)
    session.flush()
    token = secrets.token_urlsafe(32)
    voice = VoiceSession(
        call_id=call.id, user_id=user.id, case_id=case.id, role=role, ws_token_id=_token_id(token),
        state=VoiceState.created, expires_at=now + timedelta(seconds=TOKEN_SECONDS),
    )
    session.add(voice)
    session.flush()
    return call, voice, token


def consume_token(session: Session, token: str, now: datetime) -> VoiceSession:
    """The token works once, within its window, for the session it was minted for."""
    voice = session.query(VoiceSession).filter(VoiceSession.ws_token_id == _token_id(token)).one_or_none()
    if voice is None:
        raise AppError("bad_token", "This call link is not valid", status_code=401)
    if voice.state != VoiceState.created:
        raise AppError("token_used", "This call link was already used", status_code=401)
    if now > voice.expires_at:
        voice.state = VoiceState.expired
        raise AppError("token_expired", "This call link has expired. Start the call again", status_code=401)
    voice.state = VoiceState.active
    voice.started_at = now
    return voice
