"""Agreement of the LLM legal check with the author labels (docs/results/legal-check.json)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "docs" / "results" / "legal-check.json"
LABELS = ROOT / "workflows" / "evals" / "datasets" / "legal_tags_author_labelled.json"


def summarise(results: dict) -> dict:
    labelled = [c for c in results["chunks"].values() if c.get("label_id")]
    exact = [c for c in labelled if set(c["tags"]) == set(c["expected_tags"])]
    tp = sum(len(set(c["tags"]) & set(c["expected_tags"])) for c in labelled)
    proposed = sum(len(c["tags"]) for c in labelled)
    expected = sum(len(c["expected_tags"]) for c in labelled)
    reviewed = [c for c in labelled if c["state"] == "llm_reviewed"]
    attention = [c for c in labelled if c["state"] == "needs_attention"]
    out = {
        "labelled_pairs_run": len(labelled),
        "exact_agreement": f"{len(exact)}/{len(labelled)}",
        "exact_agreement_rate": round(len(exact) / len(labelled), 3) if labelled else None,
        "tag_precision": round(tp / proposed, 3) if proposed else None,
        "tag_recall": round(tp / expected, 3) if expected else None,
        "llm_reviewed": len(reviewed),
        "llm_reviewed_and_agree_with_author": sum(1 for c in reviewed if set(c["tags"]) == set(c["expected_tags"])),
        "needs_attention": len(attention),
        "needs_attention_and_tags_wrong_vs_author": sum(1 for c in attention if set(c["tags"]) != set(c["expected_tags"])),
        "disagreements": [
            {"id": c["label_id"], "locator": c["locator"], "tagger": c["tags"], "author": c["expected_tags"], "state": c["state"]}
            for c in labelled if set(c["tags"]) != set(c["expected_tags"])
        ],
        "all_chunks_reviewed": len(results["chunks"]),
        "all_states": {s: sum(1 for c in results["chunks"].values() if c["state"] == s)
                       for s in ("llm_reviewed", "needs_attention")},
    }
    answers = list(results.get("answers", {}).values())
    if answers:
        right = [a for a in answers if a["top1_is_right_chunk"]]
        wrong = [a for a in answers if not a["top1_is_right_chunk"]]
        out["answer_check"] = {
            "questions": len(answers),
            "top1_right": len(right),
            "reviewer_supports_when_top1_right": sum(1 for a in right if a["verdict"] == "agree"),
            "reviewer_supports_when_top1_wrong": sum(1 for a in wrong if a["verdict"] == "agree"),
            "top1_wrong": len(wrong),
        }
    out["run"] = results.get("run", {})
    return out


if __name__ == "__main__":
    print(json.dumps(summarise(json.loads(RESULTS.read_text(encoding="utf-8"))), ensure_ascii=False, indent=1))
