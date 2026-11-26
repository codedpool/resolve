"""Scores the redaction engine on the 150-string set and prints a markdown summary."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.privacy.redact import Redactor  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "workflows" / "evals" / "datasets" / "redaction.json"
items = json.loads(DATA.read_text(encoding="utf-8"))
r = Redactor()
rows = {}
for it in items:
    out = r.redact_or_withhold(it["text"]).text
    row = rows.setdefault(it["class"], {"n": 0, "leaks": 0, "lost": 0, "values": 0})
    row["n"] += 1
    row["values"] += len(it["redact"]) + len(it["keep"])
    row["leaks"] += sum(s in out for s in it["redact"])
    row["lost"] += sum(s not in out for s in it["keep"])
print("| Class | Strings | Values that survived (should be 0) | Values wrongly removed |")
print("|---|---|---|---|")
for cls, row in sorted(rows.items()):
    print(f"| {cls} | {row['n']} | {row['leaks']} | {row['lost']} |")
