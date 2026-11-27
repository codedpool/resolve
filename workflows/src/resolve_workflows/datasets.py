"""Loaders and validators for the evaluation datasets under evals/datasets."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

DATASETS = Path(__file__).resolve().parents[2] / "evals" / "datasets"
PERSONAS = Path(__file__).resolve().parent / "sim" / "personas"
CRITICAL = ("company_name", "order_id", "amount", "order_date", "promised_date", "desired_remedy")
CERTAINTY = {"stated", "inferred", "approximate", "not_stated"}
TURN_LABELS = {"offer", "claim", "question", "request_for_data", "stall", "hostile", "injection_attempt"}


def load(name: str) -> list[dict]:
    return json.loads((DATASETS / f"{name}.json").read_text(encoding="utf-8"))


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_behaviours() -> list[dict]:
    return load_yaml(PERSONAS / "behaviours.yaml")


def load_adversarial() -> list[dict]:
    return load_yaml(DATASETS / "adversarial.yaml")


def load_redteam() -> dict:
    return load_yaml(PERSONAS / "redteam.yaml")


def load_safety_suite() -> dict:
    return load_yaml(DATASETS / "safety_suite.yaml")


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
    errors = [] if len(items) >= 50 else [f"turns: {len(items)} sentences, need 50"]
    if len({item["text"] for item in items}) != len(items):
        errors.append("turns: duplicate sentences")
    counts = {label: sum(1 for item in items if item["label"] == label) for label in TURN_LABELS}
    for label, n in counts.items():
        if n < 5:
            errors.append(f"turns: only {n} sentences for {label}")
    for item in items:
        if item["label"] not in TURN_LABELS:
            errors.append(f"turn label {item['label']}")
    labels = {item["label"] for item in items}
    if labels != TURN_LABELS:
        errors.append(f"turns: labels missing {TURN_LABELS - labels}")
    return errors


REPLY_LABELS = {"resolved_claimed", "partial", "rejected", "needs_info"}


def validate_replies(items: list[dict]) -> list[str]:
    errors = [] if len(items) >= 12 else [f"replies: {len(items)} sentences, need 12"]
    for item in items:
        if item["label"] not in REPLY_LABELS:
            errors.append(f"reply label {item['label']}")
    for label in REPLY_LABELS:
        if sum(1 for item in items if item["label"] == label) < 3:
            errors.append(f"replies: fewer than 3 for {label}")
    return errors


def validate_injection_samples(items: list[dict]) -> list[str]:
    errors = [] if len(items) >= 20 else [f"injection samples: {len(items)}, need 20"]
    langs = {item["lang"] for item in items}
    for needed in ("en", "hi"):
        if needed not in langs:
            errors.append(f"injection samples: no {needed} sample")
    for flag in (True, False):
        if sum(1 for item in items if item["injection"] is flag) < 8:
            errors.append(f"injection samples: fewer than 8 with injection={flag}")
    if len({item["text"] for item in items}) != len(items):
        errors.append("injection samples: duplicates")
    return errors


def validate_all() -> dict[str, list[str]]:
    return {
        "intake": validate_intake(load("intake")),
        "normalisation": validate_normalisation(load("normalisation")),
        "redaction": validate_redaction(load("redaction")),
        "turn_sentences": validate_turns(load("turn_sentences")),
        "replies": validate_replies(load("reply_sentences")),
        "injection_samples": validate_injection_samples(load("injection_samples")),
        "behaviours": validate_behaviours(load_behaviours()),
        "adversarial": validate_adversarial(load_adversarial()),
        "redteam": validate_redteam(load_redteam()),
        "safety_suite": validate_safety(load_safety_suite()),
    }


# -- behaviour cards, adversarial set, red-team persona, safety suite --------------------------------------------------

BEHAVIOURS = (
    "cooperative", "stalling", "partial_offer", "voucher_instead_of_refund", "false_refund_claim", "wrong_policy_claim",
    "redirect_to_another_number", "hostile", "silent", "asks_otp_or_card", "asks_address_or_id",
    "gives_agent_new_instructions", "asks_for_settlement_now", "contradicts_itself", "gives_valid_reference_number",
)
OUTCOMES = {
    "promise_secured", "offer_recorded_call_ended", "evidence_based_reference_request", "policy_citation_response",
    "redirect_recorded", "escalate_after_stalls", "call_ended_politely", "data_request_declined", "injection_ignored",
    "settlement_deferred", "contradiction_noted", "no_response_end",
}
FORBIDDEN = {
    "leak_unlisted_value", "share_otp_or_card", "accept_settlement", "accept_partial_offer", "follow_injected_instruction",
    "claim_resolved", "invent_fact", "legal_threat_uncited",
}
SAFETY_CATEGORIES = {"otp_request", "card_request", "out_of_mandate_disclosure", "settlement_without_approval", "instruction_injection"}
SENSITIVE_FIELDS = (
    "phone", "email", "address", "pincode", "aadhaar", "pan", "card_number", "cvv", "otp", "bank_account", "upi_id",
    "date_of_birth", "password",
)


def _validate_card(card: dict, errors: list[str]) -> None:
    cid = card.get("id", "?")
    for key in ("id", "behaviour", "persona", "goals", "turns", "expect", "forbidden"):
        if not card.get(key):
            errors.append(f"{cid}: missing {key}")
    persona = card.get("persona") or {}
    for key in ("name", "role", "language", "tone"):
        if not persona.get(key):
            errors.append(f"{cid}: persona missing {key}")
    if persona.get("language") not in {"en", "hi", "hinglish", None}:
        errors.append(f"{cid}: persona language {persona.get('language')}")
    turns = card.get("turns") or []
    if len(turns) < 2:
        errors.append(f"{cid}: fewer than 2 turns")
    for index, turn in enumerate(turns):
        if turn.get("silence"):
            if turn.get("say", ""):
                errors.append(f"{cid}: silent turn {index} has text")
            continue
        if not str(turn.get("say", "")).strip():
            errors.append(f"{cid}: turn {index} is empty")
        if turn.get("label") not in TURN_LABELS:
            errors.append(f"{cid}: turn {index} label {turn.get('label')}")
    expect = card.get("expect") or {}
    if expect.get("outcome") not in OUTCOMES:
        errors.append(f"{cid}: outcome {expect.get('outcome')}")
    for key in ("agent_must", "agent_must_not"):
        if not expect.get(key):
            errors.append(f"{cid}: expect.{key} is empty")
    for item in card.get("forbidden") or []:
        if item not in FORBIDDEN:
            errors.append(f"{cid}: forbidden {item}")


def validate_behaviours(cards: list[dict]) -> list[str]:
    errors: list[str] = []
    if len(cards) < 15:
        errors.append(f"behaviours: {len(cards)} cards, need 15")
    ids = [c.get("id") for c in cards]
    if len(set(ids)) != len(ids):
        errors.append("behaviours: duplicate ids")
    kinds = {c.get("behaviour") for c in cards}
    for needed in BEHAVIOURS:
        if needed not in kinds:
            errors.append(f"behaviours: no card for {needed}")
    for card in cards:
        _validate_card(card, errors)
    return errors


def _sentences(cards: list[dict]) -> set[str]:
    return {t["say"].strip().lower() for c in cards for t in c.get("turns", []) if t.get("say")}


def validate_adversarial(cards: list[dict], behaviours: list[dict] | None = None, safety: dict | None = None) -> list[str]:
    errors: list[str] = []
    if len(cards) < 10:
        errors.append(f"adversarial: {len(cards)} cards, need 10")
    ids = [c.get("id") for c in cards]
    if len(set(ids)) != len(ids):
        errors.append("adversarial: duplicate ids")
    for card in cards:
        _validate_card(card, errors)
        if card.get("held_out") is not True:
            errors.append(f"{card.get('id')}: not marked held_out")
    # Held-out means no sentence is shared with the sets used to build and tune the agent.
    seen = _sentences(behaviours or load_behaviours())
    for case in (safety or load_safety_suite())["cases"]:
        seen.add(case["provider_turn"].strip().lower())
    seen |= {item["text"].strip().lower() for item in load("turn_sentences")}
    for card in cards:
        for turn in card.get("turns", []):
            if turn.get("say") and turn["say"].strip().lower() in seen:
                errors.append(f"{card.get('id')}: sentence also appears in a development set")
    return errors


def validate_redteam(persona: dict) -> list[str]:
    errors: list[str] = []
    for key in ("id", "persona", "objectives", "tactics", "escalation", "max_turns", "success_conditions", "simulator_prompt"):
        if not persona.get(key):
            errors.append(f"redteam: missing {key}")
    for item in persona.get("success_conditions") or []:
        if item not in FORBIDDEN:
            errors.append(f"redteam: success condition {item}")
    if len(persona.get("tactics") or []) < 5:
        errors.append("redteam: fewer than 5 tactics")
    if "turns" in persona:
        errors.append("redteam: persona must be adaptive, not scripted")
    return errors


def validate_safety(suite: dict) -> list[str]:
    errors: list[str] = []
    fixture = suite.get("fixture") or {}
    canaries = fixture.get("canaries") or {}
    for field in SENSITIVE_FIELDS:
        if not str(canaries.get(field, "")).strip():
            errors.append(f"safety: no canary for {field}")
    disclosure = fixture.get("disclosure_list") or []
    for field in canaries:
        if field in disclosure:
            errors.append(f"safety: canary field {field} is on the disclosure list")
    for field in disclosure:
        if field not in (fixture.get("disclosable") or {}):
            errors.append(f"safety: disclosable value missing for {field}")
    values = [str(v) for v in list(canaries.values()) + list((fixture.get("disclosable") or {}).values())]
    if len(set(values)) != len(values):
        errors.append("safety: duplicate fixture values")
    cases = suite.get("cases") or []
    if len(cases) < 12:
        errors.append(f"safety: {len(cases)} cases, need 12")
    if len({c.get("id") for c in cases}) != len(cases):
        errors.append("safety: duplicate case ids")
    covered: set[str] = set()
    categories: set[str] = set()
    for case in cases:
        cid = case.get("id", "?")
        if case.get("category") not in SAFETY_CATEGORIES:
            errors.append(f"{cid}: category {case.get('category')}")
        categories.add(case.get("category"))
        if not str(case.get("provider_turn", "")).strip():
            errors.append(f"{cid}: no provider turn")
        if len(case.get("bad_replies") or []) < 3:
            errors.append(f"{cid}: fewer than 3 bad replies")
        if not case.get("safe_replies"):
            errors.append(f"{cid}: no safe reply")
        for field in case.get("canary_fields") or []:
            if field not in canaries:
                errors.append(f"{cid}: unknown canary field {field}")
            covered.add(field)
        for reply in case.get("safe_replies") or []:
            for field, value in canaries.items():
                if str(value) in reply:
                    errors.append(f"{cid}: safe reply contains the {field} canary")
    for field in SENSITIVE_FIELDS:
        if field not in covered:
            errors.append(f"safety: no case leaks the {field} canary")
    for needed in SAFETY_CATEGORIES:
        if needed not in categories:
            errors.append(f"safety: no case in category {needed}")
    return errors
