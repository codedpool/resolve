"""Live check of turn labels on Devanagari sentences, one set at a time, with the prompt currently on disk.

    python scripts/eval_devanagari_turns.py dev       # the development set, used while tuning the prompt
    python scripts/eval_devanagari_turns.py heldout   # written before tuning and scored only once per prompt version
    python scripts/eval_devanagari_turns.py english   # the original 52 sentences, to catch a regression

Reports the model's own label (before the keyword cross-check the graph adds), with the prompt version in the output name.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eval_turn_understanding import DATA, ROOT, build  # noqa: E402

from resolve_workflows.nodes.classify_turn import classify_turn  # noqa: E402

SETS = {"dev": "turn_sentences_devanagari_dev", "heldout": "turn_sentences_devanagari_heldout", "english": "turn_sentences"}


def main() -> None:
    which = sys.argv[1]
    version = (ROOT / "workflows" / "src" / "resolve_workflows" / "prompts" / "classify_turn.md").read_text(encoding="utf-8").splitlines()[0].strip()
    number = version.split(":")[-1].strip()  # the first line is "version: N"; a colon must never reach a file name on Windows
    rows = json.loads((DATA / f"{SETS[which]}.json").read_text(encoding="utf-8"))
    paced = build()
    out = []
    for item in rows:
        result = classify_turn(paced, item["text"])
        out.append({"text": item["text"], "expected": item["label"], "got": result.label, "confidence": result.confidence, "source": result.source})
    right = sum(r["expected"] == r["got"] for r in out)
    path = ROOT / "docs" / "results" / f"devanagari-turns-{which}-v{number}.json"
    path.write_text(json.dumps({"set": which, "prompt": version, "right": right, "total": len(out), "rows": out}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(which, f"v{number}", f"{right}/{len(out)}", json.dumps(paced.calls))
    for r in out:
        if r["expected"] != r["got"]:
            print("  miss:", r["expected"], "->", r["got"])


if __name__ == "__main__":
    main()
