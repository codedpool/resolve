"""Loaders and validators for the evaluation datasets under evals/datasets."""

from __future__ import annotations

import json
from pathlib import Path

DATASETS = Path(__file__).resolve().parents[2] / "evals" / "datasets"
CRITICAL = ("company_name", "order_id", "amount", "order_date", "promised_date", "desired_remedy")
CERTAINTY = {"stated", "inferred", "approximate", "not_stated"}
TURN_LABELS = {"offer", "claim", "question", "request_for_data", "stall", "hostile", "injection_attempt"}


def load(name: str) -> list[dict]:
    return json.loads((DATASETS / f"{name}.json").read_text(encoding="utf-8"))


def validate_intake(items: list[dict]) -> list[str]:
    errors: list[str] = []
    if len(items) < 20:
        errors.append(f"intake: {len(items)} scenarios, need 20")
    seen = set()
    for item in items:
        if item["id"] in seen:
            errors.append(f"duplicate id {item['id']}")
        seen.add(item["id"])
        for field in CRITICAL:
            fact = item["expect"].get(field)
            if not fact or fact.get("certainty") not in CERTAINTY:
                errors.append(f"{item['id']}: bad {field}")
            elif fact["certainty"] == "not_stated" and fact["value"] != "":
                errors.append(f"{item['id']}: not_stated {field} must have an empty value")
            elif fact["certainty"] != "not_stated" and not fact["value"]:
                errors.append(f"{item['id']}: {field} has a certainty but no value")
    flags = {flag for item in items for flag in item["flags"]}
    for needed in ("not_stated", "approximate", "ambiguity", "correction", "relative_date"):
        if needed not in flags:
            errors.append(f"intake: no scenario marks {needed}")
    return errors


def validate_normalisation(items: list[dict]) -> list[str]:
    errors = [] if len(items) >= 60 else [f"normalisation: {len(items)} cases, need 60"]
    for item in items:
        if item["kind"] not in {"digits", "quantity", "amount", "date"}:
            errors.append(f"{item['id']}: kind {item['kind']}")
        if item["kind"] == "date" and "ref" not in item:
            errors.append(f"{item['id']}: date case needs ref")
    return errors


def validate_redaction(items: list[dict]) -> list[str]:
    errors = [] if len(items) >= 150 else [f"redaction: {len(items)} strings, need 150"]
    for item in items:
        if item["class"] == "keep" and not item["keep"]:
            errors.append(f"{item['id']}: keep item without a kept value")
        if item["class"] != "keep" and not item["redact"]:
            errors.append(f"{item['id']}: sensitive item without a value to redact")
        # Some items list several surface forms (digits and spoken); at least one must be in the text.
        flat = item["text"].replace(" ", "")
        if item["redact"] and not any(v in item["text"] or v.replace(" ", "") in flat for v in item["redact"]):
            errors.append(f"{item['id']}: no redact value appears in the text")
    return errors


def validate_turns(items: list[dict]) -> list[str]:
    errors = [] if len(items) >= 30 else [f"turns: {len(items)} sentences, need 30"]
    for item in items:
        if item["label"] not in TURN_LABELS:
            errors.append(f"turn label {item['label']}")
    labels = {item["label"] for item in items}
    if labels != TURN_LABELS:
        errors.append(f"turns: labels missing {TURN_LABELS - labels}")
    return errors


def validate_all() -> dict[str, list[str]]:
    return {
        "intake": validate_intake(load("intake")),
        "normalisation": validate_normalisation(load("normalisation")),
        "redaction": validate_redaction(load("redaction")),
        "turn_sentences": validate_turns(load("turn_sentences")),
    }
