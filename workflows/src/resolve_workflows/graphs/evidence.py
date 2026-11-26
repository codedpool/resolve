"""Evidence graph: read a document locally first. An image reaches a vision model only after the owner
approves that specific image. Fields come from a deterministic finder, a model fills gaps from redacted text,
and anything that disagrees with a confirmed fact is flagged to the consumer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from resolve_workflows.nodes.doc_fields import find_candidates
from resolve_workflows.nodes.extract import extract_facts
from resolve_workflows.ports import LLM, Redactor

FIELDS = ("company_name", "order_id", "amount", "order_date")


class OCR(Protocol):
    def read(self, image: bytes) -> list[str]:
        """Text from one or more local OCR passes (for example English plus Hindi, English only, Hindi only)."""


class Vision(Protocol):
    def read_text(self, image: bytes) -> str:
        """Send one approved image to a vision model and return the text it reads."""


class EvidenceStore(Protocol):
    def image(self, evidence_id: str) -> bytes: ...

    def request_vision_approval(self, evidence_id: str) -> str: ...

    def approval_status(self, evidence_id: str) -> str | None:
        """pending, approved, rejected or None, read from the stored Approval for this evidence."""

    def confirmed_facts(self, case_id: str) -> dict[str, str]: ...

    def save_result(self, evidence_id: str, doc_type: str, fields: dict, source: str) -> None: ...

    def flag(self, case_id: str, evidence_id: str, field: str, evidence_value: str, fact_value: str) -> None: ...

    def set_state(self, evidence_id: str, state: str) -> None: ...

    def today(self) -> str: ...


class EvidenceState(TypedDict, total=False):
    case_id: str
    evidence_id: str
    event: str  # process | approval_decided
    texts: list[str]
    state: str
    fields: dict
    flags: list[dict]


@dataclass
class EvidencePorts:
    ocr: OCR
    vision: Vision
    llm: LLM
    redactor: Redactor
    store: EvidenceStore


def _merge(texts: list[str]) -> dict[str, list[str] | str]:
    """First non-empty value per field across the OCR passes. Amount keeps every candidate."""
    merged: dict[str, list[str] | str] = {"company_name": "", "order_id": "", "amount": [], "order_date": ""}
    for text in texts:
        found = find_candidates(text)
        for name in ("company_name", "order_id", "order_date"):
            if not merged[name] and found[name]:
                merged[name] = found[name]
        for amount in found["amount"]:
            if amount not in merged["amount"]:
                merged["amount"].append(amount)  # type: ignore[union-attr]
    return merged


def _doc_type(text: str) -> str:
    low = text.lower()
    if re.search(r"payment successful|transaction id|upi", low):
        return "payment_proof"
    if "invoice" in low:
        return "invoice"
    if re.search(r"order|ऑर", low):
        return "order_confirmation"
    return "other"


def _norm(field: str, value: str) -> str:
    if field == "order_id":
        return re.sub(r"[^A-Z0-9]", "", value.upper())
    if field == "amount":
        return re.sub(r"[^0-9]", "", value)
    return re.sub(r"\s+", "", value).lower()


def build_evidence_graph(ports: EvidencePorts):
    store = ports.store

    def route(state: EvidenceState) -> str:
        return "ocr" if state["event"] == "process" else "check_approval"

    def ocr(state: EvidenceState) -> dict:
        texts = ports.ocr.read(store.image(state["evidence_id"]))
        merged = _merge(texts)
        readable = bool(merged["order_id"] or merged["amount"] or merged["order_date"])
        return {"texts": texts if readable else []}

    def after_ocr(state: EvidenceState) -> str:
        return "redact" if state.get("texts") else "request_approval"

    def request_approval(state: EvidenceState) -> dict:
        store.request_vision_approval(state["evidence_id"])
        store.set_state(state["evidence_id"], "waiting_approval")
        return {"state": "waiting_approval"}

    def check_approval(state: EvidenceState) -> dict:
        # The decision is read from the stored Approval, never from the event, so a forged event cannot open the door.
        status = store.approval_status(state["evidence_id"])
        return {"state": status or "none"}

    def after_check(state: EvidenceState) -> str:
        return {"approved": "vision", "rejected": "type_yourself"}.get(state["state"], "end")

    def vision(state: EvidenceState) -> dict:
        text = ports.vision.read_text(store.image(state["evidence_id"]))
        return {"texts": [text] if text.strip() else []}

    def after_vision(state: EvidenceState) -> str:
        return "redact" if state.get("texts") else "type_yourself"

    def type_yourself(state: EvidenceState) -> dict:
        store.set_state(state["evidence_id"], "type_it_yourself")
        return {"state": "type_it_yourself"}

    def redact(state: EvidenceState) -> dict:
        safe = []
        for text in state["texts"]:
            outcome = ports.redactor.redact_or_withhold(text)
            if outcome.withheld:
                continue
            safe.append((text, outcome))
        if not safe:
            return {"texts": []}
        return {"texts": [t for t, _ in safe]}

    def extract(state: EvidenceState) -> dict:
        texts = state["texts"]
        if not texts:
            store.set_state(state["evidence_id"], "type_it_yourself")
            return {"state": "type_it_yourself", "fields": {}}
        merged = _merge(texts)
        fields: dict = {}
        grounded = " ".join(texts)
        # Model fills only what the finder could not place, and only from redacted text.
        missing = [f for f in FIELDS if not merged[f]]
        if missing:
            outcome = ports.redactor.redact_or_withhold(texts[0])
            if not outcome.withheld:
                result, _usage, _prompt = extract_facts(ports.llm, outcome.text, store.today())
                for name in missing:
                    fact = getattr(result, name)
                    value = ports.redactor.restore(fact.value, outcome.tokens)
                    if value and _norm(name, value) in _norm(name, grounded):
                        merged[name] = value if name != "amount" else [value]
        for name in FIELDS:
            value = merged[name]
            fields[name] = {"candidates": list(value)} if name == "amount" else {"value": value}
        doc_type = _doc_type(grounded)
        store.save_result(state["evidence_id"], doc_type, fields, "local_ocr" if state.get("state") != "approved" else "vision")
        return {"fields": fields, "state": "extracted"}

    def checks(state: EvidenceState) -> dict:
        if state.get("state") == "type_it_yourself":
            return {}
        confirmed = store.confirmed_facts(state["case_id"])
        flags = []
        today = date.fromisoformat(store.today())
        for name, entry in state.get("fields", {}).items():
            fact_value = confirmed.get(name, "")
            if not fact_value:
                continue
            if name == "amount":
                candidates = entry.get("candidates", [])
                if candidates and not any(_norm(name, c) == _norm(name, fact_value) for c in candidates):
                    flags.append({"field": name, "evidence": candidates[0], "fact": fact_value})
            else:
                value = entry.get("value", "")
                if value and _norm(name, value) != _norm(name, fact_value):
                    flags.append({"field": name, "evidence": value, "fact": fact_value})
        order_date = state.get("fields", {}).get("order_date", {}).get("value", "")
        if order_date and date.fromisoformat(order_date) > today:
            flags.append({"field": "order_date", "evidence": order_date, "fact": "a date in the future"})
        for flag in flags:
            store.flag(state["case_id"], state["evidence_id"], flag["field"], flag["evidence"], flag["fact"])
        if flags:
            store.set_state(state["evidence_id"], "needs_attention")
        else:
            store.set_state(state["evidence_id"], "read")
        return {"flags": flags, "state": "needs_attention" if flags else "read"}

    b = StateGraph(EvidenceState)
    for name, fn in (("ocr", ocr), ("request_approval", request_approval), ("check_approval", check_approval), ("vision", vision),
                     ("type_yourself", type_yourself), ("redact", redact), ("extract", extract), ("checks", checks)):
        b.add_node(name, fn)
    b.add_conditional_edges(START, route, {"ocr": "ocr", "check_approval": "check_approval"})
    b.add_conditional_edges("ocr", after_ocr, {"redact": "redact", "request_approval": "request_approval"})
    b.add_conditional_edges("check_approval", after_check, {"vision": "vision", "type_yourself": "type_yourself", "end": END})
    b.add_conditional_edges("vision", after_vision, {"redact": "redact", "type_yourself": "type_yourself"})
    b.add_edge("request_approval", END)
    b.add_edge("type_yourself", END)
    b.add_edge("redact", "extract")
    b.add_edge("extract", "checks")
    b.add_edge("checks", END)
    return b.compile()
