"""OCR bake-off on the 30 evidence documents: Tesseract (English plus Hindi) against RapidOCR (a PaddleOCR-family engine).

Same deterministic field finder after each engine. Writes docs/results/ocr-bakeoff.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workflows" / "src"))
from resolve_workflows.nodes.doc_fields import find_fields  # noqa: E402

TESSERACT = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
TESSDATA = ROOT / "server" / "data" / "tessdata"
DOCS = ROOT / "server" / "data" / "evidence_docs"
SPEC = json.loads((ROOT / "workflows" / "evals" / "datasets" / "evidence.json").read_text(encoding="utf-8"))
OUT = ROOT / "docs" / "results" / "ocr-bakeoff.json"
FIELDS = ("company_name", "order_id", "amount", "order_date")


def tesseract(path: Path) -> str:
    env = {"TESSDATA_PREFIX": str(TESSDATA), "PATH": ""}
    done = subprocess.run([str(TESSERACT), str(path), "-", "-l", "eng+hin"], capture_output=True, env=env, timeout=60)
    return done.stdout.decode("utf-8", errors="replace")


def rapid(engine, path: Path) -> str:
    result, _ = engine(str(path))
    return "\n".join(item[1] for item in (result or []))


def score(engine_name: str, read) -> dict:
    per_field = {f: 0 for f in FIELDS}
    by_lang: dict[str, list[int]] = {}
    misses = []
    started = time.perf_counter()
    for doc in SPEC:
        found = find_fields(read(DOCS / f"{doc['id']}.png"))
        ok = 0
        for field in FIELDS:
            hit = found[field].lower() == doc[field].lower() if field != "company_name" else found[field].lower() == doc[field].lower()
            per_field[field] += hit
            ok += hit
            if not hit:
                misses.append({"doc": doc["id"], "kind": doc["kind"], "field": field, "expected": doc[field], "got": found[field]})
        by_lang.setdefault(doc["language"], []).append(ok)
    total = len(SPEC) * len(FIELDS)
    return {
        "engine": engine_name,
        "accuracy": round(sum(per_field.values()) / total, 3),
        "per_field": per_field,
        "by_language": {k: round(sum(v) / (len(v) * len(FIELDS)), 3) for k, v in by_lang.items()},
        "seconds": round(time.perf_counter() - started, 1),
        "misses": misses,
    }


def main() -> None:
    results = [score("tesseract eng+hin", tesseract)]
    try:
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()
        results.append(score("rapidocr (english and chinese models)", lambda p: rapid(engine, p)))
    except Exception as exc:  # noqa: BLE001
        results.append({"engine": "rapidocr", "error": str(exc)[:200]})
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in results:
        print(r.get("engine"), r.get("accuracy"), r.get("per_field"), r.get("by_language"), r.get("seconds"), r.get("error", ""))
    for miss in results[0]["misses"][:12]:
        print(miss)


if __name__ == "__main__":
    main()
