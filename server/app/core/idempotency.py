"""Remember a result for an idempotency key. The first caller wins."""

from __future__ import annotations

from typing import Any


class IdempotencyStore:
    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._values.get(key)

    def remember(self, key: str, value: Any) -> tuple[Any, bool]:
        if not key:
            raise ValueError("idempotency key is required")
        if key in self._values:
            return self._values[key], False
        self._values[key] = value
        return value, True
