"""Versioned prompt files. The first line of each file is `version: N`; the hash identifies the exact text."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str
    sha: str


def load(name: str) -> Prompt:
    raw = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    head, _, body = raw.partition("\n")
    if not head.startswith("version:"):
        raise ValueError(f"{name}.md must start with 'version: N'")
    return Prompt(name, int(head.split(":", 1)[1]), body.strip(), hashlib.sha256(raw.encode()).hexdigest()[:12])
