"""A small live check of the outreach graph on Groq: the draft and classify roles on three behaviour cards.

    python scripts/eval_outreach_live.py --runs 2      # about 15 model calls per run of the three cards

Only a sample can run live on this account (8000 tokens per minute, 1000 requests per day), so this is not the behaviour
suite: that runs with scripted models (tests/test_outreach_behaviours.py). Here the draft model (role `draft`) and the turn
classifier (role `classify`) are real; the output guard's deterministic layer is real; the policy classifier layer and the
injection screen are not called (no calls on those roles), and the summary text uses its code fallback. Calls are spaced by
a rolling token window and a 429 waits for the retry-after header. Nothing printed here is a key or a case value; the
fixture is invented.
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

from vendor import load_env  # noqa: E402

from app.adapters.cost import CostMeter  # noqa: E402
from app.adapters.factory import GROQ_BASE  # noqa: E402
from app.adapters.groq_llm import GroqClient  # noqa: E402
from app.config import Settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from resolve_workflows import datasets  # noqa: E402
from resolve_workflows.sim.harness import ScriptedProvider, make_world, outcome_problems, play, universal_problems  # noqa: E402

CARDS = ("b05_false_refund_claim", "b03_partial_offer", "b10_asks_otp_or_card")
OUT = ROOT / "docs" / "results" / "outreach-live.json"
TOKEN_BUDGET_PER_MINUTE = 6500  # the account cap is 8000; leave room


class Paced:
    """The Groq client behind the llm and classifier ports, with a token window, 429 waits and a call tally."""

    def __init__(self, client: GroqClient) -> None:
        self.client = client
        self.calls = {"draft": 0, "classify": 0, "other": 0, "retries": 0, "errors": 0}
        self.tokens = 0
        self.window: deque[tuple[float, int]] = deque()

    def _room(self, expected: int) -> None:
        while True:
            now = time.time()
            while self.window and now - self.window[0][0] > 60:
                self.window.popleft()
            if sum(t for _, t in self.window) + expected <= TOKEN_BUDGET_PER_MINUTE:
                return
            time.sleep(max(1.0, 61 - (now - self.window[0][0])))

    def _go(self, kind: str, expected: int, fn):
        for attempt in range(6):
            self._room(expected)
            self.calls[kind] += 1
            try:
                result, usage = fn()
                used = int((usage or {}).get("total_tokens") or expected)
                self.window.append((time.time(), used))
                self.tokens += used
                return result
            except AppError as exc:
                if (exc.details or {}).get("status") != 429:
                    self.calls["errors"] += 1
                    raise
                self.calls["retries"] += 1
                time.sleep(20 + 10 * attempt)
        raise RuntimeError("rate limited too long")

    def text(self, role, prompt, variables, mode="instruct"):
        if role == "summarize":
            raise RuntimeError("summary uses its code fallback in the live sample")
        return self._go("draft", 1100, lambda: self.client.text(role, prompt, variables, mode)), {}

    def structured(self, role, prompt, variables, schema, mode="instruct"):
        raise RuntimeError("not used in the live sample")

    def classify(self, role, prompt, text, labels):
        def call():
            label, confidence, usage = self.client.classify(role, prompt, text, labels)
            return (label, confidence, usage), usage

        label, confidence, usage = self._go("classify", 800, call)
        return label, confidence, usage


def build() -> Paced:
    load_env()
    import os

    settings = Settings(groq_api_key=os.environ["GROQ_API_KEY"])
    http = httpx.Client(base_url=GROQ_BASE, headers={"Authorization": f"Bearer {settings.groq_api_key}"}, timeout=90)
    meter = CostMeter(2.0)
    paced = Paced(GroqClient(settings.load_models(), meter, http))
    paced.meter = meter
    return paced


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--cards", nargs="*", default=list(CARDS))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    paced = build()
    cards = {c["id"]: c for c in datasets.load_behaviours()}
    rows = []
    for card_id in args.cards:
        card = cards[card_id]
        for run_index in range(args.runs):
            labels = {t["say"]: t["label"] for t in card["turns"] if t.get("say")}
            world = make_world(0, labels, llm=paced, classifier=paced, with_policy_classifier=False)
            started = time.time()
            error = ""
            try:
                run = play(world, ScriptedProvider(card))
                problems = universal_problems(run) + outcome_problems(card, run)
                got = [r.understood.get("model_label") for r in run.results[1:] if r.understood]
                expected = [t["label"] for t in card["turns"][: len(got)]]
                call = run.call
                row = {
                    "card": card_id, "run": run_index, "passed": not problems, "problems": problems, "sentences": run.sentences,
                    "labels_expected": expected, "labels_model": got, "label_hits": sum(1 for a, b in zip(expected, got) if a == b),
                    "draft_fallbacks": call.get("draft_fallbacks"), "drafts": call.get("drafts"), "held": call.get("held"),
                    "end_reason": call.get("end_reason"), "seconds": round(time.time() - started, 1),
                }
            except Exception as exc:  # noqa: BLE001 - a vendor failure is a result too
                error = f"{type(exc).__name__}: {str(exc)[:200]}"
                row = {"card": card_id, "run": run_index, "passed": False, "problems": [error], "sentences": []}
            rows.append(row)
            print(card_id, run_index, "PASS" if row["passed"] else "FAIL", row.get("problems"), flush=True)
    summary = {"rows": rows, "calls": paced.calls, "tokens": paced.tokens, "cost_usd": round(paced.meter.spent_usd, 4)}
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}))


if __name__ == "__main__":
    main()
