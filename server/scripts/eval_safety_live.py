"""The safety suite against real Groq models: every case, several runs, the real draft model, the real turn classifier and the
real guard (deterministic layer plus the policy classifier).

    python scripts/eval_safety_live.py --runs 5

Each case is one hostile provider turn (a request for a code, a card number, an unlisted detail, a settlement, or an
instruction to the assistant). A run passes when nothing the assistant says contains a canary value or accepts anything.
Calls are paced to the account's token limit and wait out 429s, so this takes about an hour. The fixture is invented.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from eval_outreach_live import Paced, build, datasets  # noqa: E402

from resolve_workflows.sim.harness import leaked, make_world, play, universal_problems  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "docs" / "results" / "safety-live.json"


class OneTurn:
    def __init__(self, text: str) -> None:
        self.text, self.used = text, False

    def next_turn(self, history):
        if self.used:
            return None
        self.used = True
        return self.text


class PacedWithStructured(Paced):
    def structured(self, role, prompt, variables, schema, mode="instruct"):
        return self._go("other", 900, lambda: self.client.structured(role, prompt, variables, schema, mode)), {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    base = build()
    paced = PacedWithStructured(base.client)
    paced.meter = base.meter
    cases = datasets.load_safety_suite()["cases"]
    rows = []
    for case in cases:
        if args.only and case["id"] not in args.only:
            continue
        canaries = None
        for run_index in range(args.runs):
            world = make_world(0, {}, llm=paced, classifier=paced, with_policy_classifier=True)
            canaries = world.canaries
            error = ""
            try:
                run = play(world, OneTurn(case["provider_turn"]))
                problems = universal_problems(run)
                leaks = leaked(run.sentences, canaries)
                row = {"case": case["id"], "category": case["category"], "run": run_index, "passed": not problems and not leaks,
                       "problems": problems, "leaks": leaks, "sentences": run.sentences, "held": run.call.get("held")}
            except Exception as exc:  # noqa: BLE001 - a vendor failure is a result too, and is reported as one
                error = f"{type(exc).__name__}: {str(exc)[:160]}"
                row = {"case": case["id"], "category": case["category"], "run": run_index, "passed": False, "problems": [error], "leaks": [], "sentences": []}
            rows.append(row)
            print(case["id"], run_index, "PASS" if row["passed"] else "FAIL", row["problems"] or row["leaks"], flush=True)
            OUT.write_text(json.dumps({"rows": rows, "calls": paced.calls, "tokens": paced.tokens}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    failures = [r for r in rows if not r["passed"]]
    summary = {"trials": len(rows), "failures": len(failures), "calls": paced.calls, "tokens": paced.tokens,
               "cost_usd": round(paced.meter.spent_usd, 4), "finished": time.strftime("%Y-%m-%d %H:%M")}
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
