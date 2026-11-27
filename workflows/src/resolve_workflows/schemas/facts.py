"""Pydantic models and the strict JSON schema for fact extraction (plan section 5.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FIELDS = (
    "company_name", "product", "order_id", "order_date", "amount", "currency", "payment_mode", "issue_summary",
    "company_said", "promised_date", "refund_reference", "desired_remedy", "provider_entity_type",
)
CRITICAL_FIELDS = ("company_name", "order_id", "amount", "order_date", "promised_date", "desired_remedy")
Certainty = Literal["stated", "inferred", "approximate", "not_stated"]


class FactCandidate(BaseModel):
    value: str = ""
    certainty: Certainty = "not_stated"
    original_phrase: str = ""
    ambiguity_note: str = ""


class ExtractionResult(BaseModel):
    company_name: FactCandidate = Field(default_factory=FactCandidate)
    product: FactCandidate = Field(default_factory=FactCandidate)
    order_id: FactCandidate = Field(default_factory=FactCandidate)
    order_date: FactCandidate = Field(default_factory=FactCandidate)
    amount: FactCandidate = Field(default_factory=FactCandidate)
    currency: FactCandidate = Field(default_factory=FactCandidate)
    payment_mode: FactCandidate = Field(default_factory=FactCandidate)
    issue_summary: FactCandidate = Field(default_factory=FactCandidate)
    company_said: FactCandidate = Field(default_factory=FactCandidate)
    promised_date: FactCandidate = Field(default_factory=FactCandidate)
    refund_reference: FactCandidate = Field(default_factory=FactCandidate)
    desired_remedy: FactCandidate = Field(default_factory=FactCandidate)
    provider_entity_type: FactCandidate = Field(default_factory=FactCandidate)


def _candidate_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "value": {"type": "string"},
            "certainty": {"type": "string", "enum": ["stated", "inferred", "approximate", "not_stated"]},
            "original_phrase": {"type": "string"},
            "ambiguity_note": {"type": "string"},
        },
        "required": ["value", "certainty", "original_phrase", "ambiguity_note"],
    }


def extraction_json_schema() -> dict:
    """Strict-compatible: every field is required, so absence is `not_stated` with an empty value."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {name: _candidate_schema() for name in FIELDS},
        "required": list(FIELDS),
    }
