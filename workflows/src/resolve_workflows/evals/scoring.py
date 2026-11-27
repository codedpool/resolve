"""Scoring for the intake extraction suite. Comparison is in code; no model judges a value."""

from __future__ import annotations

import re

from resolve_workflows.schemas import CRITICAL_FIELDS, ExtractionResult

_REMEDY_TERMS = ("refund", "money", "paisa", "replacement", "replace", "repair", "reversal", "reverse", "exchange",
                 "compensation", "install", "return")


def _alnum(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def _terms(value: str) -> set[str]:
    low = value.lower()
    found = {t for t in _REMEDY_TERMS if t in low}
    if "money" in found or "paisa" in found:
        found.add("refund")
    if "replace" in found:
        found.add("replacement")
    if "reverse" in found:
        found.add("reversal")
    return found - {"money", "paisa", "replace", "reverse"}


def values_match(field: str, expected: str, got: str) -> bool:
    if field == "order_id":
        return _alnum(expected) == _alnum(got)
    if field == "amount":
        return re.sub(r"\D", "", expected) == re.sub(r"\D", "", got)
    if field == "desired_remedy":
        return bool(_terms(expected) & _terms(got))
    if field == "company_name":
        return re.sub(r"\s+", "", expected).lower() == re.sub(r"\s+", "", got).lower()
    return expected.strip() == got.strip()


def score_scenario(expect: dict, result: ExtractionResult) -> dict:
    """Per critical field: correct (value and, for approximate, certainty) or fabricated (a value where none is stated)."""
    out = {"fields": {}, "correct": 0, "total": 0, "fabricated": 0, "not_stated_total": 0}
    for name in CRITICAL_FIELDS:
        want = expect[name]
        got = getattr(result, name)
        out["total"] += 1
        if want["certainty"] == "not_stated":
            out["not_stated_total"] += 1
            fabricated = bool(got.value)
            out["fabricated"] += fabricated
            ok = not fabricated
        else:
            ok = bool(got.value) and values_match(name, want["value"], got.value)
            if ok and want["certainty"] == "approximate":
                ok = got.certainty == "approximate"
        out["correct"] += ok
        out["fields"][name] = {"ok": ok, "expected": want["value"], "got": got.value, "certainty": got.certainty}
    return out
