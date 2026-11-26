"""Per-call and per-day limits, and the global kill switch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import VoiceSession


@dataclass
class CallBudget:
    max_seconds: float
    max_tts_chars: int
    started_at: float
    tts_chars: int = 0
    stt_seconds: float = 0.0

    def elapsed(self, now: float) -> float:
        return now - self.started_at

    def over_time(self, now: float) -> bool:
        return self.elapsed(now) >= self.max_seconds

    def over_chars(self) -> bool:
        return self.tts_chars >= self.max_tts_chars


def used_today(session: Session, user_id, now: datetime) -> tuple[float, int]:
    since = now - timedelta(hours=24)
    row = session.execute(
        select(func.coalesce(func.sum(VoiceSession.stt_seconds), 0.0), func.coalesce(func.sum(VoiceSession.tts_characters), 0))
        .where(VoiceSession.user_id == user_id, VoiceSession.expires_at >= since)
    ).one()
    return float(row[0]), int(row[1])


@dataclass
class KillSwitch:
    """Process-wide. `live` holds the open connections so a kill can close every socket and Rumik session."""

    engaged: bool = False
    live: set = field(default_factory=set)
