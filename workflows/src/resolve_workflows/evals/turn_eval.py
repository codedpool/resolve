"""Scoring for turn understanding: accuracy, per-label results, confusions, and injection coverage."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from resolve_workflows import datasets
from resolve_workflows.nodes.classify_turn import classify_turn
from resolve_workflows.nodes.screen import ScreenResult, level_for, tune_thresholds


def summarise(rows: list[dict], marks: dict[str, bool] | None = None) -> dict:
    """rows: {text, expected, got}. marks: text -> the injection screen marked it (optional)."""
    correct = [r for r in rows if r["expected"] == r["got"]]
    per_label: dict[str, list[int]] = {}
    confusions: Counter = Counter()
    for r in rows:
        stat = per_label.setdefault(r["expected"], [0, 0])
        stat[0] += 1
        stat[1] += r["expected"] == r["got"]
        if r["expected"] != r["got"]:
            confusions[(r["expected"], r["got"])] += 1
    out = {
        "total": len(rows),
        "correct": len(correct),
        "accuracy": len(correct) / len(rows) if rows else 0.0,
        "per_label": {k: {"total": v[0], "correct": v[1]} for k, v in per_label.items()},
        "confusions": [{"expected": e, "got": g, "count": n} for (e, g), n in confusions.most_common()],
        "misses": [r for r in rows if r["expected"] != r["got"]],
    }
    attempts = [r for r in rows if r["expected"] == "injection_attempt"]
    if attempts:
        labelled = sum(1 for r in attempts if r["got"] == "injection_attempt")
        out["injection"] = {"total": len(attempts), "labelled": labelled}
        if marks is not None:
            covered = sum(1 for r in attempts if r["got"] == "injection_attempt" or marks.get(r["text"]))
            out["injection"]["labelled_or_marked"] = covered
    return out


def run_turns(classifier, screen_scores: dict[str, float] | None = None, suspect: float | None = None, likely: float | None = None) -> list[dict]:
    """Run the node over turn_sentences.json. `screen_scores` are recorded Prompt Guard scores by sentence (optional)."""
    rows = []
    for item in datasets.load("turn_sentences"):
        screen = None
        if screen_scores is not None and item["text"] in screen_scores:
            score = screen_scores[item["text"]]
            level = level_for(score, *(x for x in (suspect, likely) if x is not None)) if suspect is not None and likely is not None else level_for(score)
            screen = ScreenResult(score, level, level != "none")
        result = classify_turn(classifier, item["text"], screen)
        rows.append({"text": item["text"], "expected": item["label"], "got": result.label, "source": result.source, "marked": result.injection_signal})
    return rows


def injection_screen_report() -> dict:
    """Tune the thresholds on the recorded Prompt Guard scores and report the screen's accuracy on the labelled samples."""
    path = datasets.DATASETS / "injection_scores.json"
    scores = json.loads(Path(path).read_text(encoding="utf-8"))
    samples = [(scores[item["text"]], item["injection"]) for item in datasets.load("injection_samples")]
    return tune_thresholds(samples)
