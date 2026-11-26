"""The retrieval question set is well formed and answerable from the fetched texts."""

from __future__ import annotations

import re

import pytest

from app.legal.chunker import build_corpus
from app.legal.evalset import DATASET, is_hit, load_questions

pytestmark = pytest.mark.skipif(not DATASET.exists(), reason="workflows repo not checked out next to server")

def _words(text: str) -> str:
    """Compare on words only, so dashes, quotes and line wraps in the source do not matter."""
    return " ".join(re.findall(r"\w+", text.lower()))


DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def test_counts_and_languages():
    main = load_questions(subset="main")
    held = load_questions(subset="heldout")
    assert len(main) == 30 and len(held) == 10
    hindi = [q for q in main if q["lang"] in ("hi", "hinglish")]
    assert len(hindi) >= 8
    assert any(q["lang"] == "hi" for q in hindi) and any(q["lang"] == "hinglish" for q in hindi)
    for q in main + held:
        assert bool(DEVANAGARI.search(q["question"])) == (q["lang"] == "hi"), q["id"]
    ids = [q["id"] for q in main + held]
    assert len(ids) == len(set(ids))
    assert not {q["question"] for q in main} & {q["question"] for q in held}


def test_every_question_has_an_answering_chunk_in_the_corpus():
    corpus = build_corpus()
    for q in load_questions():
        assert any(is_hit(c, q["expect"]) for c in corpus.chunks), f"{q['id']} has no matching chunk"


def test_the_quoted_basis_of_each_question_is_in_the_source_text():
    corpus = build_corpus()
    folded = {sid: _words(text) for sid, text in corpus.sources.items()}
    for q in load_questions():
        sources = {w["source"] for w in q["expect"]}
        pieces = [p.strip(" \"'.") for p in re.split(r"\s*(?:\.\.\.|;)\s*", q["derived_from"]) if len(p.strip()) > 18]
        assert pieces, q["id"]
        for piece in pieces:
            assert any(_words(piece) in folded[s] for s in sources), f"{q['id']}: not in source: {piece}"
