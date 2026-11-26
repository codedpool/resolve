"""Live evaluation of turn understanding on Groq: Prompt Guard scores, turn labels and reply labels.

    python scripts/eval_turn_understanding.py --injection     # Prompt Guard on the labelled samples (about 26 calls)
    python scripts/eval_turn_understanding.py --turns         # classify_turn on turn_sentences.json and classify_reply (about 60 calls)

The account is limited to 8000 tokens per minute on the chat models, so calls are spaced by a rolling token window and a
429 waits for the retry-after header. Nothing here prints a key or a case value; the sentences are authored test text.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "workflows" / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from vendor import load_env, redact  # noqa: E402

from app.adapters.cost import CostMeter  # noqa: E402
from app.adapters.factory import GROQ_BASE  # noqa: E402
from app.adapters.groq_llm import GroqClient  # noqa: E402
from app.config import Settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from resolve_workflows import datasets  # noqa: E402
from resolve_workflows.nodes.classify_turn import classify_reply, classify_turn  # noqa: E402

DATA = ROOT / "workflows" / "evals" / "datasets"
OUT = ROOT / "docs" / "results" / "turn-understanding.json"
TOKEN_BUDGET_PER_MINUTE = 6500  # the account cap is 8000; leave room


class Paced:
    """Wraps the Groq client: counts calls, keeps under the per-minute token cap, waits on 429."""

    def __init__(self, client: GroqClient) -> None:
        self.client = client
        self.calls = {"classify": 0, "score": 0, "retries": 0}
        self.window: deque[tuple[float, int]] = deque()

    def _wait_for_room(self, expected_tokens: int) -> None:
        while True:
            now = time.time()
            while self.window and now - self.window[0][0] > 60:
                self.window.popleft()
            if sum(t for _, t in self.window) + expected_tokens <= TOKEN_BUDGET_PER_MINUTE:
                return
            time.sleep(max(1.0, 61 - (now - self.window[0][0])))

    def _retrying(self, fn, kind: str, expected_tokens: int):
        for attempt in range(6):
            self._wait_for_room(expected_tokens)
            self.calls[kind] += 1
            try:
                result = fn()
                return result
            except AppError as exc:
                if (exc.details or {}).get("status") != 429:
                    raise
                self.calls["retries"] += 1
                time.sleep(20 + 10 * attempt)
        raise RuntimeError("rate limited too long")

    def classify(self, role: str, prompt_id: str, text: str, labels: list[str]):
        def call():
            label, confidence, usage = self.client.classify(role, prompt_id, text, labels)
            self.window.append((time.time(), int(usage.get("total_tokens") or 700)))
            return label, confidence, usage

        return self._retrying(call, "classify", 700)

    def score(self, text: str) -> float:
        return self._retrying(lambda: self.client.score(text), "score", 0)


def build() -> Paced:
    load_env()
    import os

    settings = Settings(groq_api_key=os.environ["GROQ_API_KEY"])
    http = httpx.Client(base_url=GROQ_BASE, headers={"Authorization": f"Bearer {settings.groq_api_key}"}, timeout=60)
    return Paced(GroqClient(settings.load_models(), CostMeter(2.0), http))


def run_injection(paced: Paced) -> dict:
    samples = datasets.load("injection_samples")
    scores = {}
    for item in samples:
        scores[item["text"]] = paced.score(item["text"])
        time.sleep(1.0)
    path = DATA / "injection_scores.json"
    path.write_text(json.dumps(scores, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"scored": len(scores), "calls": paced.calls["score"]}


def run_turns(paced: Paced) -> dict:
    rows = []
    for item in datasets.load("turn_sentences"):
        result = classify_turn(paced, item["text"])
        rows.append({"text": item["text"], "expected": item["label"], "got": result.label, "confidence": result.confidence, "source": result.source})
    replies = []
    for item in datasets.load("reply_sentences"):
        if not item["live"]:
            continue
        result = classify_reply(paced, item["text"])
        replies.append({"text": item["text"], "expected": item["label"], "got": result.label, "confidence": result.confidence, "source": result.source})
    return {"turns": rows, "replies": replies, "calls": dict(paced.calls)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--injection", action="store_true")
    parser.add_argument("--turns", action="store_true")
    args = parser.parse_args()
    paced = build()
    report = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    try:
        if args.injection:
            report["injection"] = run_injection(paced)
        if args.turns:
            report["live"] = run_turns(paced)
    except Exception as exc:  # noqa: BLE001
        print(redact(f"stopped: {type(exc).__name__}: {exc}"))
        raise
    finally:
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"calls": paced.calls, "spent_usd": round(paced.client.meter.spent_usd, 4)}))


if __name__ == "__main__":
    main()
