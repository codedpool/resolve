"""Splits text into speakable sentences, one speech frame each. Hindi uses the danda as a full stop."""

from __future__ import annotations

import re

_BREAK = re.compile(r"(?<=[.!?।॥])\s+")
MAX_CHARS = 240
MIN_CHARS = 12


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _BREAK.split(text.strip()) if p.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and (len(merged[-1]) < MIN_CHARS or len(part) < MIN_CHARS) and len(merged[-1]) + len(part) < MAX_CHARS:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    out: list[str] = []
    for sentence in merged:
        while len(sentence) > MAX_CHARS:  # a single frame is cut near 25 seconds of audio, so long text is split on a space
            cut = sentence.rfind(" ", 0, MAX_CHARS)
            cut = cut if cut > 0 else MAX_CHARS
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            out.append(sentence)
    return out
