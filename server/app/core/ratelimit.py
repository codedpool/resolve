"""Fixed-window rate limiter. The clock is injected so tests can move time."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from app.core.clock import Clock


class RateLimiter:
    def __init__(self, limit: int, window: timedelta, clock: Clock) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, list[datetime]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = self.clock.now()
        cutoff = now - self.window
        recent = [moment for moment in self._hits[key] if moment > cutoff]
        if len(recent) >= self.limit:
            self._hits[key] = recent
            return False
        recent.append(now)
        self._hits[key] = recent
        return True
