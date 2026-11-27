"""Live check of the narration "done" detector on short messages, decided exactly as the intake graph decides.

    python scripts/eval_done_detector.py

A message counts as done only when the model says `done` with confidence at least DONE_CONFIDENCE; anything else is `more`.
Prints accuracy, the messages wrongly treated as done (they would end the narration early) and the done messages missed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eval_turn_understanding import DATA, ROOT, build  # noqa: E402

from resolve_workflows import prompts  # noqa: E402
from resolve_workflows.graphs.intake import DONE_CONFIDENCE  # noqa: E402


def main() -> None:
    prompt = prompts.load("classify_done")
    rows = json.loads((DATA / "done_sentences.json").read_text(encoding="utf-8"))
    paced = build()
    out = []
    for item in rows:
        label, confidence, _ = paced.classify("classify", prompt.text, item["text"], ["done", "more"])  # paced, so the account's per-minute cap is respected
        decided = "done" if label == "done" and confidence >= DONE_CONFIDENCE else "more"
        out.append({"text": item["text"], "expected": item["label"], "model": label, "confidence": confidence, "decided": decided})
    right = sum(r["expected"] == r["decided"] for r in out)
    false_done = [r for r in out if r["expected"] == "more" and r["decided"] == "done"]
    missed = [r for r in out if r["expected"] == "done" and r["decided"] == "more"]
    version = prompt.version
    path = ROOT / "docs" / "results" / f"done-detector-v{version}.json"
    path.write_text(json.dumps({"prompt_version": version, "right": right, "total": len(out), "false_done": len(false_done), "missed_done": len(missed), "rows": out}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"v{version}: {right}/{len(out)}; treated as done wrongly: {len(false_done)}; done missed: {len(missed)}")
    for r in false_done + missed:
        print("  ", r["expected"], "->", r["decided"], r["confidence"], "|", r["text"])


if __name__ == "__main__":
    main()
