"""Injection screen. Prompt Guard gives a probability; this wrapper turns it into a mark on the turn.

The signal never changes what the agent does by itself. It marks the turn (`marked`, `level`) so that the event log,
the classifier result and the evaluation can see it. Treating provider speech as untrusted data is what protects the
agent, not this score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from resolve_workflows.ports import InjectionScreen

# Tuned on the labelled English, Hindi and Hinglish samples in evals/datasets/injection_samples.json
# (scores recorded in injection_scores.json; method and numbers in docs/results/turn-understanding.md).
SUSPECT_THRESHOLD = 0.47
LIKELY_THRESHOLD = 0.95


@dataclass(frozen=True)
class ScreenResult:
    score: float
    level: str  # none | suspect | likely
    marked: bool
    error: bool = False  # the screen could not be reached; the turn is not marked and the flow goes on


def level_for(score: float, suspect: float = SUSPECT_THRESHOLD, likely: float = LIKELY_THRESHOLD) -> str:
    if score >= likely:
        return "likely"
    if score >= suspect:
        return "suspect"
    return "none"


def screen_turn(screen: InjectionScreen, text: str, suspect: float = SUSPECT_THRESHOLD, likely: float = LIKELY_THRESHOLD) -> ScreenResult:
    if not text.strip():
        return ScreenResult(0.0, "none", False)
    try:
        score = float(screen.score(text))
    except Exception:  # a failed screen must never stop the call
        return ScreenResult(0.0, "none", False, error=True)
    level = level_for(score, suspect, likely)
    return ScreenResult(score, level, level != "none")


def tune_thresholds(samples: list[tuple[float, bool]]) -> dict:
    """Choose the thresholds from labelled scores (score, is_injection).

    Prompt Guard scores are bimodal, so the thresholds are placed in gaps between observed scores:
    `suspect` is the midpoint of the widest empty gap between scores (the robust choice: any value inside it gives the
    same result on the samples), rounded to two decimals.
    `likely` is the lowest value, rounded up to two decimals, with no false positive on the benign samples.
    The in-sample accuracy optimum is not used: below the gap every score is about 0.0005 and says nothing.
    """
    total = len(samples)
    scores = sorted({s for s, _ in samples})
    gaps = [(b - a, (a + b) / 2) for a, b in zip(scores, scores[1:])]

    def stats(threshold: float) -> dict:
        tp = sum(1 for s, y in samples if y and s >= threshold)
        fp = sum(1 for s, y in samples if not y and s >= threshold)
        fn = sum(1 for s, y in samples if y and s < threshold)
        return {"threshold": round(threshold, 4), "accuracy": round((total - fp - fn) / total, 4), "recall": tp / max(1, tp + fn), "false_positives": fp, "false_negatives": fn}

    widest = max(gaps)[1] if gaps else 0.5
    suspect = round(widest, 2)
    benign_max = max((s for s, y in samples if not y), default=0.0)
    likely = min(1.0, max(suspect, math.ceil((benign_max + 1e-9) * 100) / 100))
    return {"suspect": stats(suspect), "likely": stats(likely), "samples": total}
