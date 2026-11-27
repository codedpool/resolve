"""JSON logs. Secret values and key-like strings are stripped before a record is emitted."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

_KEY_PATTERNS = (
    re.compile(r"gsk_[A-Za-z0-9]+"),
    re.compile(r"rk_(?:live|test)_[A-Za-z0-9_\-]+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)


class RedactionFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self.secrets = [item for item in (secrets or []) if item]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()  # format first, so numeric formats such as %.2f work, then strip secrets from the result
        except (TypeError, ValueError):
            message = str(record.msg)
        record.msg = self.redact(message)
        record.args = None
        return True

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        for pattern in _KEY_PATTERNS:
            text = pattern.sub("[redacted]", text)
        return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(secrets: list[str] | None = None) -> logging.Logger:
    logger = logging.getLogger("resolve")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter(secrets))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
