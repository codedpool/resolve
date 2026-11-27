"""A running count of the characters sent to Rumik for synthesis, kept in a local file.

Rumik's API does not return a balance, a price or `credits_used` (it is 0 on every `done` frame), so spend cannot be read from the
service. This ledger counts what we send, so spend can be estimated once the developer reads the dashboard balance twice and
the rate per character is worked out. The file is git-ignored and holds only counts, never text.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[2] / "data" / "rumik_ledger.jsonl"


def record(characters: int, source: str = "tts") -> None:
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "chars": int(characters), "source": source}) + "\n")
    except OSError:
        pass  # counting must never break a call


def total(since: str = "") -> int:
    if not LEDGER.is_file():
        return 0
    chars = 0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["at"] >= since:
            chars += row["chars"]
    return chars
