"""Quoting is verified by code: a stored chunk must be an exact slice of its fetched source.

Whitespace is the only thing allowed to differ (line wraps in PDFs, runs of spaces). Any other
change, including one character, fails. See plan section 8.5.
"""

from __future__ import annotations

from typing import Iterable, Mapping


class QuoteCheckError(AssertionError):
    pass


def normalise(text: str) -> str:
    return " ".join(text.split())


def quotecheck(chunk, source_text: str) -> None:
    """Raise QuoteCheckError unless chunk.text is a substring of source_text after whitespace folding."""
    needle = normalise(chunk.text)
    if not needle:
        raise QuoteCheckError(f"{chunk.source_id} section {chunk.section}: empty chunk")
    if needle not in normalise(source_text):
        raise QuoteCheckError(f"{chunk.source_id} section {chunk.section}{chunk.clause}: text is not in the source")


def quotecheck_all(chunks: Iterable, sources: Mapping[str, str]) -> int:
    """Check every chunk against its own source text. Returns the number of chunks checked."""
    folded: dict[str, str] = {}
    count = 0
    for chunk in chunks:
        if chunk.source_id not in sources:
            raise QuoteCheckError(f"{chunk.source_id}: no source text to check against")
        if chunk.source_id not in folded:
            folded[chunk.source_id] = normalise(sources[chunk.source_id])
        needle = normalise(chunk.text)
        if not needle or needle not in folded[chunk.source_id]:
            raise QuoteCheckError(f"{chunk.source_id} section {chunk.section}{chunk.clause}: text is not in the source")
        count += 1
    return count
