"""The extraction node: one LLM call, then code checks. The model never decides a format."""

from __future__ import annotations

import re
from datetime import date

from resolve_workflows import prompts
from resolve_workflows.schemas import FIELDS, ExtractionResult, FactCandidate, extraction_json_schema

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_AMOUNT = re.compile(r"^\d+(?:\.\d+)?$")
_NOISE = re.compile(r"(?i)[₹\s,]|rs\.?|inr|rupees?|rupaye")


def _clean_amount(value: str) -> str:
    stripped = _NOISE.sub("", value)
    return stripped if _AMOUNT.match(stripped) else ""


def _valid_date(value: str) -> bool:
    if not _ISO.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def check(result: ExtractionResult) -> ExtractionResult:
    """Deterministic repairs: amount digits only, dates must be real ISO dates, empty value means not_stated."""
    for name in FIELDS:
        fact: FactCandidate = getattr(result, name)
        if name == "amount" and fact.value:
            cleaned = _clean_amount(fact.value)
            if cleaned != fact.value:
                fact.ambiguity_note = (fact.ambiguity_note + " amount reformatted").strip()
            fact.value = cleaned
        if name in {"order_date", "promised_date"} and fact.value and not _valid_date(fact.value):
            fact.ambiguity_note = (fact.ambiguity_note + f" date not understood: {fact.value}").strip()
            fact.value = ""
        if not fact.value:
            fact.certainty = "not_stated"
        elif fact.certainty == "not_stated":
            fact.certainty = "inferred"
    return result


def extract_facts(llm, text: str, narration_date: str, role: str = "extract") -> tuple[ExtractionResult, dict, prompts.Prompt]:
    prompt = prompts.load("extract_facts")
    parsed, usage = llm.structured(role, prompt.text, {"narration_date": narration_date, "text": text}, extraction_json_schema())
    return check(ExtractionResult.model_validate(parsed)), usage, prompt
