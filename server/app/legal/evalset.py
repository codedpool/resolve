"""Reads the retrieval question set (workflows/evals/datasets/retrieval.json) and scores hits."""

from __future__ import annotations

import json
from pathlib import Path

DATASET = Path(__file__).resolve().parents[3] / "workflows" / "evals" / "datasets" / "retrieval.json"


def load_questions(path: Path = DATASET, subset: str | None = None) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data["questions"]
    return [q for q in questions if subset is None or q["set"] == subset]


def is_hit(result, expect: list[dict]) -> bool:
    """`result` needs source_id, section and clause_numbers (a Chunk or a retrieval result)."""
    for want in expect:
        if result.source_id != want["source"]:
            continue
        if want.get("section") is not None and result.section != want["section"]:
            continue
        # a chunk with no clause numbers is a whole section and covers every clause of it
        if want.get("clause") is not None and result.clause_numbers and want["clause"] not in result.clause_numbers:
            continue
        return True
    return False


def top_k_hit(results, expect: list[dict], k: int = 3) -> bool:
    return any(is_hit(r, expect) for r in list(results)[:k])


def summarise(rows: list[tuple[dict, bool]]) -> dict:
    """rows: (question, hit). Returns counts and rates for all, Hindi (hi + hinglish) and English."""

    def rate(items):
        hits = sum(1 for _, ok in items if ok)
        return {"hits": hits, "n": len(items), "rate": round(hits / len(items), 3) if items else None}

    hindi = [r for r in rows if r[0]["lang"] in ("hi", "hinglish")]
    return {
        "all": rate(rows),
        "hindi": rate(hindi),
        "devanagari": rate([r for r in rows if r[0]["lang"] == "hi"]),
        "hinglish": rate([r for r in rows if r[0]["lang"] == "hinglish"]),
        "english": rate([r for r in rows if r[0]["lang"] == "en"]),
    }


def run_eval(search, questions: list[dict], k: int = 3) -> tuple[dict, list[dict]]:
    """`search(question_dict) -> list of results`. Returns (summary, per-question rows)."""
    rows, detail = [], []
    for question in questions:
        results = search(question)
        ok = top_k_hit(results, question["expect"], k)
        rows.append((question, ok))
        detail.append({"id": question["id"], "lang": question["lang"], "hit": ok,
                       "top": [r.locator for r in list(results)[:k]]})
    return summarise(rows), detail
