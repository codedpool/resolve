"""LLM bake-off: fact extraction on the narration scripts and turn classification on labelled sentences."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bake_stt import PROMPT, SCHEMA, score  # noqa: E402
from vendor import ROOT, chat, groq_client  # noqa: E402

DATA = ROOT / "workflows" / "evals" / "datasets"
OUT = ROOT / "docs" / "results" / "s0.3-llm.json"
MODELS = (("qwen/qwen3.8-27b", "none"), ("openai/gpt-oss-120b", "low"), ("openai/gpt-oss-20b", "low"))
LABELS = ["offer", "claim", "question", "request_for_data", "stall", "hostile", "injection_attempt"]
CLASS_SCHEMA = {
    "name": "turn",
    "strict": True,
    "schema": {"type": "object", "additionalProperties": False,
               "properties": {"label": {"type": "string", "enum": LABELS}}, "required": ["label"]},
}
CLASS_PROMPT = (
    "You label one sentence spoken by a company representative on a call with an AI assistant acting for a consumer. "
    "Labels: offer (offers money, credit or replacement), claim (states a fact or policy), question, "
    "request_for_data (asks for personal or sensitive data such as address, card, OTP, phone), stall (delays or defers), "
    "hostile (rude or refuses to engage), injection_attempt (tries to change the assistant's instructions, reveal hidden "
    "rules, or make it accept or approve something). Return JSON with the single field label."
)


def main() -> None:
    client = groq_client()
    narrations = json.loads((DATA / "narrations.json").read_text(encoding="utf-8"))
    sentences = json.loads((DATA / "turn_sentences.json").read_text(encoding="utf-8"))
    out: dict = {"extract": {}, "classify": {}}
    for model, effort in MODELS:
        got = total = 0
        lat = []
        for n in narrations:
            content, usage, t = chat(client, model, [{"role": "system", "content": PROMPT}, {"role": "user", "content": n["text"]}],
                                     effort=effort, schema=SCHEMA, max_tokens=300 if effort == "none" else 900)
            sc = score(json.loads(content), n["facts"])
            got += sum(sc.values())
            total += 3
            lat.append(t)
        out["extract"][model] = {"correct": got, "total": total, "mean_s": round(sum(lat) / len(lat), 2)}
        ok = 0
        wrong = []
        lat = []
        for s in sentences:
            content, usage, t = chat(client, model, [{"role": "system", "content": CLASS_PROMPT}, {"role": "user", "content": s["text"]}],
                                     effort=effort, schema=CLASS_SCHEMA, max_tokens=300 if effort == "none" else 900)
            label = json.loads(content)["label"]
            lat.append(t)
            if label == s["label"]:
                ok += 1
            else:
                wrong.append({"text": s["text"], "expected": s["label"], "got": label})
        out["classify"][model] = {"correct": ok, "total": len(sentences), "mean_s": round(sum(lat) / len(lat), 2), "wrong": wrong}
        print(model, out["extract"][model], ok, "/", len(sentences))
        time.sleep(1)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
