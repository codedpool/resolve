"""Eval runner.

    python -m resolve_workflows.evals.run --suite intake_extraction --repeats 3 --max-cost 1.0 --out report.md

Without --live it uses a scripted fake (a self-test of the harness). With --live it calls Groq through
the role map in server/config/models.yaml and stops when the cost cap is reached.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from resolve_workflows import datasets
from resolve_workflows.evals.scoring import score_scenario
from resolve_workflows.nodes.extract import extract_facts
from resolve_workflows.schemas import ExtractionResult

ROOT = Path(__file__).resolve().parents[4]


class CostCapReached(Exception):
    pass


def _redactor():
    server = ROOT / "server"
    if str(server) not in sys.path:
        sys.path.insert(0, str(server))
    try:
        from app.privacy.redact import Redactor
    except ImportError:
        return None
    return Redactor()


def run_intake(llm, repeats: int, cost_of, max_cost: float, redact=None) -> dict:
    scenarios = datasets.load("intake")
    rows = []
    for scenario in scenarios:
        text = scenario["text"]
        tokens: dict[str, str] = {}
        if redact is not None:
            outcome = redact.redact_or_withhold(text)
            text, tokens = outcome.text, outcome.tokens
        for run in range(repeats):
            if cost_of() > max_cost:
                raise CostCapReached(f"cost cap {max_cost} reached")
            result, usage, prompt = extract_facts(llm, text, scenario["narration_date"])
            for name in type(result).model_fields:  # the real value is restored from the case store before anything is compared
                fact = getattr(result, name)
                fact.value = redact.restore(fact.value, tokens) if redact is not None else fact.value
            score = score_scenario(scenario["expect"], result)
            rows.append({"id": scenario["id"], "run": run, "score": score, "flags": scenario["flags"], "prompt": f"{prompt.name}@{prompt.version}:{prompt.sha}",
                         "tokens": usage})
    total = sum(r["score"]["total"] for r in rows)
    correct = sum(r["score"]["correct"] for r in rows)
    fabricated = sum(r["score"]["fabricated"] for r in rows)
    ns_total = sum(r["score"]["not_stated_total"] for r in rows)
    approx_rows = [r for r in rows if "approximate" in r["flags"]]
    return {
        "runs": len(rows),
        "critical_field_accuracy": correct / total,
        "fabricated_rate": fabricated / ns_total if ns_total else 0.0,
        "approximate_accuracy": (sum(r["score"]["correct"] for r in approx_rows) / sum(r["score"]["total"] for r in approx_rows)) if approx_rows else None,
        "rows": rows,
    }


def report_markdown(name: str, summary: dict, meta: dict) -> str:
    fails = [(r["id"], f, v) for r in summary["rows"] for f, v in r["score"]["fields"].items() if not v["ok"]]
    lines = [
        f"# Eval report: {name}", "",
        f"Models: {meta.get('models')}. Prompt: {summary['rows'][0]['prompt'] if summary['rows'] else '-'}. Runs: {summary['runs']}. Cost: ${meta.get('cost', 0):.3f}.", "",
        "| Measure | Result | Threshold |", "|---|---|---|",
        f"| Critical-field accuracy | {summary['critical_field_accuracy']:.1%} | at least 90% |",
        f"| Fabricated values on not_stated fields | {summary['fabricated_rate']:.1%} | at most 2% |",
    ]
    if summary["approximate_accuracy"] is not None:
        lines.append(f"| Accuracy on scenarios with approximate values | {summary['approximate_accuracy']:.1%} | reported |")
    lines += ["", "## Failures", ""]
    if not fails:
        lines.append("None.")
    seen = set()
    for sid, field, v in fails:
        key = (sid, field, v["got"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {sid} {field}: expected `{v['expected']}`, got `{v['got']}` ({v['certainty']})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="intake_extraction")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--max-cost", type=float, default=1.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--role", default="extract")
    args = ap.parse_args(argv)
    if args.suite != "intake_extraction":
        print(f"unknown suite {args.suite}", file=sys.stderr)
        return 2
    redact = _redactor()
    if args.live:
        from resolve_workflows.evals.groq_llm import GroqLLM

        llm = GroqLLM(ROOT / "server" / "config" / "models.yaml", ROOT / ".env")
        cost_of = lambda: llm.cost  # noqa: E731
        meta = {"models": llm.model_for(args.role)}
    else:
        llm = _SelfTestLLM()
        cost_of = lambda: 0.0  # noqa: E731
        meta = {"models": "scripted self-test"}
    started = time.time()
    try:
        summary = run_intake(llm, args.repeats, cost_of, args.max_cost, redact)
    except CostCapReached as exc:
        print(str(exc), file=sys.stderr)
        return 3
    meta["cost"] = cost_of()
    text = report_markdown(args.suite, summary, meta)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        Path(args.out).with_suffix(".json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(text)
    print(f"{time.time() - started:.1f}s", file=sys.stderr)
    return 0


class _SelfTestLLM:
    """Returns the empty extraction so the harness itself can be exercised for free."""

    def structured(self, role, prompt_text, variables, schema, mode="instruct"):
        return ExtractionResult().model_dump(), {"prompt_tokens": 0, "completion_tokens": 0}


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
