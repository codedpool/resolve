"""Measures the output guard on the safety suite and on ordinary sentences. Used by the tests and for the write-up.

    python -m resolve_workflows.evals.guard_eval
"""

from __future__ import annotations

import json
import sys

from resolve_workflows import datasets
from resolve_workflows.guards.output_guard import GuardContext, OutputGuard, heard_from


def suite_context(fixture: dict, provider_turn: str = "") -> GuardContext:
    """The guard context for the suite's fixture case, with every canary registered as a withheld value."""
    return GuardContext(
        mandate_version=1,
        disclosable={k: str(v) for k, v in fixture["disclosable"].items()},
        undisclosable=tuple(str(v) for v in fixture["canaries"].values()),
        goal=fixture["goal"],
        consumer_name=fixture["consumer_name"],
    )


def run_suite(guard: OutputGuard) -> dict:
    suite = datasets.load_safety_suite()
    ctx = suite_context(suite["fixture"])
    bad = blocked = safe = false_blocks = 0
    missed, wrongly_blocked, by_category = [], [], {}
    for case in suite["cases"]:
        for reply in case["bad_replies"]:
            bad += 1
            ok = guard.check(reply, ctx, case["provider_turn"]).blocked
            blocked += ok
            row = by_category.setdefault(case["category"], [0, 0])
            row[0] += 1
            row[1] += ok
            if not ok:
                missed.append({"case": case["id"], "reply": reply})
        for reply in case["safe_replies"]:
            safe += 1
            if guard.check(reply, ctx, case["provider_turn"]).blocked:
                false_blocks += 1
                wrongly_blocked.append({"case": case["id"], "reply": reply})
    return {"bad": bad, "blocked": blocked, "safe": safe, "false_blocks": false_blocks, "missed": missed,
            "wrongly_blocked": wrongly_blocked, "by_category": by_category}


def run_ordinary(guard: OutputGuard) -> dict:
    ctx = suite_context(datasets.load_safety_suite()["fixture"])
    rows = datasets.load("ordinary_sentences")
    wrongly = []
    for row in rows:
        verdict = guard.check(row["text"], ctx, row.get("provider_turn", ""))
        if verdict.blocked:
            wrongly.append({"id": row["id"], "text": row["text"], "categories": verdict.categories, "rationale": verdict.rationale})
    return {"total": len(rows), "false_blocks": len(wrongly), "rate": len(wrongly) / len(rows), "wrongly_blocked": wrongly}


if __name__ == "__main__":
    guard = OutputGuard()  # deterministic layer alone
    print(json.dumps({"suite": run_suite(guard), "ordinary": run_ordinary(guard)}, ensure_ascii=False, indent=1))
    sys.exit(0)
