"""Chunking and quotecheck for the legal corpus. No database needed."""

from __future__ import annotations

import pytest

from app.legal.chunker import Chunk, build_corpus, chunk_numbered, chunk_paragraphs
from app.legal.quotecheck import QuoteCheckError, normalise, quotecheck, quotecheck_all

SAMPLE = """preamble noise
1. (1) This Act may be called the Test Act.
(2) It extends to everywhere.
2. In this Act, unless the context otherwise requires,
(1) "alpha" means the first thing;
(2) "beta" means the second thing;
(3) "gamma" means the third thing.
3. A short section with no sub-clauses at all.
tail noise
"""


def _cfg(**over):
    cfg = {
        "layer": "statute",
        "short_title": "Test Act",
        "mode": "numbered",
        "start": r"(?m)^1\. \(1\)",
        "end": r"\ntail noise",
        "first_number": 1,
    }
    cfg.update(over)
    return cfg


def _chunks(text=SAMPLE, target=60, maximum=120, **over):
    return chunk_numbered("test_src", text, _cfg(**over), "https://example.test/act", "2026-11-26", target, maximum)


def test_numbered_sections_are_found_in_order_and_noise_is_excluded():
    chunks = _chunks(target=10_000, maximum=20_000)
    assert [c.section for c in chunks] == ["1", "2", "3"]
    assert all("noise" not in c.text for c in chunks)
    assert chunks[0].text.startswith("1. (1) This Act")


def test_long_sections_split_at_subclauses_and_keep_the_section_number():
    chunks = _chunks(target=50, maximum=200)
    second = [c for c in chunks if c.section == "2"]
    assert len(second) >= 2
    assert second[0].clause.startswith("(1)")
    assert second[-1].clause.endswith("(3)")


def test_numbering_must_be_sequential_so_stray_numbers_do_not_open_sections():
    text = SAMPLE.replace("(3) \"gamma\"", "7. \"gamma\"")
    sections = [c.section for c in _chunks(text, target=10_000, maximum=20_000)]
    assert sections == ["1", "2", "3"]


def test_chunk_text_is_whitespace_normalised_and_every_chunk_passes_quotecheck():
    chunks = _chunks()
    for c in chunks:
        assert "\n" not in c.text and "  " not in c.text
        quotecheck(c, SAMPLE)
    assert quotecheck_all(chunks, {"test_src": SAMPLE}) == len(chunks)


def test_a_chunk_altered_by_one_character_fails_quotecheck():
    chunk = _chunks()[0]
    altered = Chunk(**{**chunk.__dict__, "text": chunk.text.replace("Test Act", "Test Azt")})
    with pytest.raises(QuoteCheckError):
        quotecheck(altered, SAMPLE)
    # a changed digit is the dangerous case for legal text
    altered = Chunk(**{**chunk.__dict__, "text": chunk.text.replace("(1)", "(7)")})
    with pytest.raises(QuoteCheckError):
        quotecheck(altered, SAMPLE)


def test_quotecheck_all_reports_missing_source():
    chunk = _chunks()[0]
    with pytest.raises(QuoteCheckError):
        quotecheck_all([chunk], {})


def test_whitespace_differences_do_not_matter():
    assert normalise("a  b\n c\t d") == "a b c d"


def test_paragraph_mode_packs_blocks_and_stays_exact():
    text = "x\nSTART\n\nfirst block line\nmore\n\nsecond block\n\nthird block here\n\nEND\nafter"
    cfg = {"layer": "escalation", "short_title": "Page", "mode": "paragraphs", "start": "START", "end": r"\nEND"}
    chunks = chunk_paragraphs("page", text, cfg, "https://example.test/p", "2026-11-26", 40, 80)
    assert len(chunks) >= 2
    assert chunks[0].text.startswith("START")
    for c in chunks:
        quotecheck(c, text)


def test_chunk_key_is_stable_and_changes_with_text():
    a = _chunks()[0]
    b = _chunks()[0]
    assert a.key == b.key
    assert Chunk(**{**a.__dict__, "text": a.text + "."}).key != a.key


def test_real_corpus_chunks_all_pass_quotecheck_and_cover_the_statute():
    corpus = build_corpus()
    assert corpus.chunks, "corpus is empty"
    assert quotecheck_all(corpus.chunks, corpus.sources) == len(corpus.chunks)
    layers = {c.layer for c in corpus.chunks}
    assert {"statute", "rules", "regulator", "escalation", "provider_policy"} <= layers
    statute = {c.section for c in corpus.chunks if c.source_id == "cpa2019_egazette"}
    assert statute == {str(n) for n in range(1, 108)}
    rules = {c.section for c in corpus.chunks if c.source_id == "ecom_rules_2020_egazette"}
    assert rules == {str(n) for n in range(1, 9)}
    assert all(c.review_state == "unreviewed" for c in corpus.chunks)
    assert all(c.fetched_at for c in corpus.chunks) and all(c.source_url.startswith("http") for c in corpus.chunks if c.layer != "provider_policy")
    assert max(len(c.text) for c in corpus.chunks) <= 2400
    keys = [c.key for c in corpus.chunks]
    assert len(keys) == len(set(keys))


def test_real_corpus_known_sections_contain_their_text():
    corpus = build_corpus()
    rule4 = " ".join(c.text for c in corpus.chunks if c.source_id == "ecom_rules_2020_egazette" and c.section == "4")
    assert "forty-eight hours" in rule4
    assert any(c.heading.startswith("Duties of e-commerce entities") for c in corpus.chunks if c.section == "4")
    sec35 = [c for c in corpus.chunks if c.source_id == "cpa2019_egazette" and c.section == "35"]
    assert sec35 and "Chapter IV" in sec35[0].heading
