"""Reconciliation: compare what the consumer said in the whole narration with the facts they confirmed.

Values are normalised first, so "twelve hundred" against "Rs. 1,200" is not a disagreement. A fact the consumer
corrected by hand (version above 1) is a deliberate change and never counts against them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from resolve_workflows.nodes.extract import extract_facts
from resolve_workflows.schemas import ExtractionResult

CHECKED = ("company_name", "amount", "order_id", "order_date", "promised_date", "desired_remedy")
_REMEDY = ("refund", "replacement", "repair", "reversal", "exchange", "compensation")


@dataclass(frozen=True)
class FactView:
    value: str
    certainty: str
    version: int = 1


@dataclass(frozen=True)
class Disagreement:
    field: str
    kind: str  # different_value | missing_fact | approximate_as_exact
    fact_value: str
    narration_value: str

    def as_dict(self) -> dict:
        return {"field": self.field, "kind": self.kind, "fact": self.fact_value, "narration": self.narration_value}


def _norm(field: str, value: str) -> str:
    if field == "order_id":
        return re.sub(r"[^A-Z0-9]", "", value.upper())
    if field == "amount":
        match = re.search(r"[0-9]+(?:\.[0-9]+)?", value.replace(",", ""))
        number = match.group(0) if match else ""
        return number[:-3] if number.endswith(".00") else number
    if field == "desired_remedy":
        low = value.lower()
        return ",".join(sorted(t for t in _REMEDY if t in low)) or low.strip()
    return re.sub(r"\s+", "", value).lower()


def _same(field: str, a: str, b: str) -> bool:
    if field == "desired_remedy":
        ta, tb = set(_norm(field, a).split(",")), set(_norm(field, b).split(","))
        return bool(ta & tb)
    return _norm(field, a) == _norm(field, b)


def compare(extracted: ExtractionResult, facts: dict[str, FactView]) -> list[Disagreement]:
    out: list[Disagreement] = []
    for field in CHECKED:
        said = getattr(extracted, field)
        fact = facts.get(field)
        if not said.value:
            continue
        if fact is None or not fact.value:
            out.append(Disagreement(field, "missing_fact", "", said.value))
            continue
        if fact.version > 1:
            continue  # the consumer corrected this on purpose
        if not _same(field, fact.value, said.value):
            out.append(Disagreement(field, "different_value", fact.value, said.value))
        elif said.certainty == "approximate" and fact.certainty == "stated":
            out.append(Disagreement(field, "approximate_as_exact", fact.value, said.value))
    return out


def question_for(item: Disagreement) -> str:
    name = item.field.replace("_", " ")
    if item.kind == "missing_fact":
        return f"You mentioned a {name} of {item.narration_value}, but it is not in your details. Should it be added?"
    if item.kind == "approximate_as_exact":
        return f"You described the {name} as about {item.narration_value}, but your details show {item.fact_value} as exact. Which is right?"
    return f"You said the {name} was {item.narration_value}, but your details show {item.fact_value}. Which is right?"


def reconcile(llm, narration: str, today: str, facts: dict[str, FactView]) -> tuple[ExtractionResult, list[Disagreement]]:
    result, _usage, _prompt = extract_facts(llm, narration, today)
    return result, compare(result, facts)
