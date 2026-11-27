"""Speech bake-off on the synthetic set: Whisper models x language settings x quiet/noisy.

Writes docs/results/s0.3-stt.json. Extraction uses the same prompt for every transcript.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vendor import ROOT, chat, groq_client, transcribe  # noqa: E402

AUDIO = ROOT / "server" / "data" / "audio"
DATA = ROOT / "workflows" / "evals" / "datasets"
OUT = ROOT / "docs" / "results" / "s0.3-stt.json"
MODELS = ("whisper-large-v3", "whisper-large-v3-turbo")
LANGS = ("hi", "en", None)

SCHEMA = {
    "name": "facts",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "merchant": {"type": "string"},
            "amount_rupees": {"type": "string"},
            "order_id": {"type": "string"},
        },
        "required": ["merchant", "amount_rupees", "order_id"],
    },
}
PROMPT = (
    "Extract from this consumer complaint transcript: merchant name, amount in rupees as digits only, "
    "and the order, booking, bill or transaction id exactly as spoken (letters and digits, no spaces). "
    "Use an empty string for anything not stated. The transcript may mix Hindi and English."
)


def norm_id(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


ALIASES = {
    "Flipkart": ["फ्लिपकार्ट", "फ्लिप कार्ट", "फ्लिपकार्ड"], "Swiggy": ["स्विगी", "स्वीगी"],
    "Amazon": ["अमेज़न", "अमेजन", "अमेज़ॉन", "अमेजॉन"], "Myntra": ["मिंत्रा", "मिन्त्रा", "मींत्रा"],
    "Zomato": ["ज़ोमैटो", "जोमैटो", "ज़ोमाटो"], "Paytm": ["पेटीएम", "पे टीएम"], "Croma": ["क्रोमा", "क्रोमाह"],
    "MakeMyTrip": ["मेक माय ट्रिप", "मेकमायट्रिप", "make my trip"], "Nykaa": ["नायका", "नाइका", "नाईका"],
    "BigBasket": ["बिग बास्केट", "बिगबास्केट", "big basket"],
}


def merchant_ok(got: str, truth: str) -> bool:
    flat = lambda t: re.sub(r"s+", "", t.lower())  # noqa: E731
    g = flat(got)
    if not g:
        return False
    return flat(truth) in g or g in flat(truth) or any(flat(a) in g or g in flat(a) for a in ALIASES.get(truth, []))


def score(facts: dict, truth: dict) -> dict:
    amount = re.sub(r"[^0-9]", "", facts.get("amount_rupees", ""))
    return {
        "merchant": merchant_ok(facts.get("merchant", ""), truth["merchant"]),
        "amount": amount == truth["amount"],
        "order_id": norm_id(facts.get("order_id", "")) == norm_id(truth["order_id"]),
    }


def wer(ref: str, hyp: str) -> float | None:
    clean = lambda s: re.findall(r"[a-z0-9]+", s.lower())  # noqa: E731
    r, h = clean(ref), clean(hyp)
    if not r or len(h) < 3:
        return None
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev = cur
    return d[len(h)] / len(r)


def rescore() -> None:
    narrations = {n["id"]: n for n in json.loads((DATA / "narrations.json").read_text(encoding="utf-8"))}
    results = json.loads(OUT.read_text(encoding="utf-8"))
    for row in results["narration"]:
        row["score"] = score(row["facts"], narrations[row["id"]]["facts"])
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    if "--rescore" in sys.argv:
        rescore()
        return
    client = groq_client()
    narrations = json.loads((DATA / "narrations.json").read_text(encoding="utf-8"))
    manifest = json.loads((AUDIO / "manifest.json").read_text(encoding="utf-8"))
    results = {"narration": [], "noise": [], "segments": {"speech": [], "noise": []}}
    for item in narrations:
        for cond in ("quiet", "noisy"):
            wav = (AUDIO / f"{item['id']}-{cond}.wav").read_bytes()
            for model in MODELS:
                for lang in LANGS:
                    r = transcribe(client, model, wav, lang)
                    text = (r.get("text") or "").strip()
                    content, _, _ = chat(client, "qwen/qwen3.8-27b", [
                        {"role": "system", "content": PROMPT}, {"role": "user", "content": text or "(empty)"}],
                        effort="none", schema=SCHEMA, max_tokens=200)
                    facts = json.loads(content)
                    sc = score(facts, item["facts"])
                    results["narration"].append({
                        "id": item["id"], "cond": cond, "model": model, "lang": lang or "auto",
                        "text": text, "facts": facts, "score": sc, "wer": wer(item["text"], text),
                        "latin": bool(re.search(r"[A-Za-z]", text)) and not re.search(r"[ऀ-ॿ]", text),
                    })
                    for seg in r.get("segments") or []:
                        results["segments"]["speech"].append({k: seg.get(k) for k in ("no_speech_prob", "avg_logprob", "compression_ratio")} | {"model": model})
                    print(item["id"], cond, model, lang, sc)
    for clip in manifest["noise"]:
        wav = (AUDIO / f"{clip['id']}.wav").read_bytes()
        for model in MODELS:
            for lang in ("hi", None):
                r = transcribe(client, model, wav, lang)
                segs = [{k: s.get(k) for k in ("text", "no_speech_prob", "avg_logprob", "compression_ratio")} for s in r.get("segments") or []]
                results["noise"].append({"id": clip["id"], "kind": clip["kind"], "model": model, "lang": lang or "auto",
                                         "text": (r.get("text") or "").strip(), "segments": segs})
                if clip["kind"] != "background_speech":
                    results["segments"]["noise"].extend(s | {"model": model} for s in segs)
        print(clip["id"])
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
