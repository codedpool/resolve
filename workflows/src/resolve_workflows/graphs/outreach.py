"""The outreach graph: a simulated call to a company representative, on the consumer's behalf, inside a mandate.

One invocation handles one event: `start`, one provider turn (`turn`), or `end`. Everything that must survive between
invocations is the call's working state, kept through the OutreachStore port (never in process memory), so a worker that
dies between turns resumes from what was stored.

    start -> check_mandate -> [blocked: request_mandate] -> retrieve_rules_and_policy -> build_call_plan -> open_call
    turn  -> check_mandate -> limits -> hear_provider -> injection_screen -> classify_turn -> route -> handle_* ->
             draft_reply -> speak (output guard, sentence by sentence) -> check_end
    end   -> post_call_summary -> reconcile_facts -> update_case -> request_approval(summary)

Decisions that touch the mandate or the case are made in code: the evidence check, the offer-against-mandate
comparison, which details may be said. The model only words a reply from a `move` (and writes the summary text); code
checks the draft and every sentence passes the output guard before it is returned. Provider text is untrusted data.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from resolve_workflows import prompts
from resolve_workflows.graphs.mandate_gate import build_mandate_gate
from resolve_workflows.guards.output_guard import HOLDING, OutputGuard, build_guard_context, heard_from
from resolve_workflows.mandate import ALWAYS_ALLOWED, MandateBlocked, build_call_context
from resolve_workflows.nodes import call_lines as lines
from resolve_workflows.nodes.answer import _DEADLINE, _THREAT, answer_with_citations
from resolve_workflows.nodes.classify_turn import Understood, classify_turn, keyword_turn_label
from resolve_workflows.nodes.evidence_check import (
    CaseEvidence, check_case_evidence, normalise_amount, normalise_reference, reference_pairs, spoken_to_digits,
)
from resolve_workflows.nodes.screen import screen_turn
from resolve_workflows.nodes.turn_facts import (
    NEVER_SHARE, SENSITIVE, asks_for_something, claim_kind, compare_to_mandate, is_refusal, looks_like_offer, parse_offer,
    promise_date, redirect_number, requested_fields, split_sentences,
)
from resolve_workflows.ports import LLM, ApprovalPort, CaseStore, Classifier, InjectionScreen, OutreachStore, Retriever, is_budget_error

TURN_LIMIT = 30
STALL_LIMIT = 3
REFUSAL_LIMIT = 3
SILENCE_LIMIT = 3
DATA_LIMIT = 3
ASK_BY_DAYS = 3
DRAFT_ROLE = "draft"
SUMMARY_ROLE = "summarize"
CONTRADICTORY = ("processed", "no_request", "delivered")
_DEVANAGARI = re.compile("[ऀ-ॿ]")
_INJECTION_WORDS = re.compile(r"(?i)ignore (?:all |your |the )?(?:previous|prior|earlier)|system (?:prompt|notice|message|:)|\[system|disregard|developer mode|you are now|from now on you")


@dataclass
class OutreachPorts:
    llm: LLM
    classifier: Classifier
    screen: InjectionScreen
    case_store: CaseStore
    store: OutreachStore
    approvals: ApprovalPort
    retriever: Retriever
    guard: OutputGuard
    now: Callable[[], datetime]
    normalise: Callable[[str], str] | None = None  # spoken-number normaliser (the server's), optional
    canaries: tuple[str, ...] = ()  # decoy values the guard must never see spoken (tests and the red team)
    on_sentence: Callable[[str], None] | None = None  # called with each sentence as soon as it has passed the guard
    draft_role: str = DRAFT_ROLE
    # `backoff_watch(callback)` is a context manager that calls `callback(seconds)` when the model client is about to wait
    # out a rate limit (the server's Groq client has one). The call uses it to say a holding line instead of going silent.
    backoff_watch: Callable | None = None


class OutreachState(TypedDict, total=False):
    case_id: str
    call_id: str
    event: str  # start | turn | end
    text: str
    reason: str
    call: dict
    status: str  # ready | blocked
    block_reason: str
    understood: dict
    route: str
    moves: list[dict]
    sentences: list[str]
    phase: str
    approval_id: str


@dataclass
class TurnResult:
    sentences: list[str]
    phase: str
    ended: bool
    approval_id: str = ""
    end_reason: str = ""
    blocked: str = ""
    understood: dict = field(default_factory=dict)


# -- call state -----------------------------------------------------------------------------------------------------


def new_call(case_id: str, call_id: str, language: str, provider: dict, mandate_version: int, started_at: datetime) -> dict:
    return {
        "case_id": case_id, "call_id": call_id, "language": language, "provider": provider.get("name", ""),
        "entity_type": provider.get("entity_type", "unknown"), "mandate_version": mandate_version,
        "started_at": started_at.isoformat(), "turns": 0, "stalls": 0, "refusals": 0, "silences": 0, "data_declines": 0,
        "injections": 0, "held": [], "ended": False, "end_reason": "", "finished": False, "heard": [], "plan": {},
        "chunk_ids": [], "claims": [], "claim_kinds": [], "contradictions": [], "offers": [], "promises": [],
        "promise": {"date": "", "reference": ""}, "reference": "", "redirects": [], "data_requests": [], "approvals": {},
        "effects": [], "transcript": [], "summary": {}, "reconciled": [], "status": "", "approval_id": "", "provider_ids": [],
        "draft_fallbacks": 0, "drafts": 0,
    }


def _who(language: str, facts: dict) -> tuple[str, str]:
    name = facts["consumer_name"].value if "consumer_name" in facts else ""
    order = facts["order_id"].value if "order_id" in facts else ""
    lang = lines.lang_of(language)
    if lang == "hi":
        return (f" {name} की ओर से" if name else " एक ग्राहक की ओर से"), (f"ऑर्डर {order} के रिफंड" if order else "एक रिफंड")
    if lang == "hinglish":
        return (f" {name} ki taraf se" if name else " ek customer ki taraf se"), (f"order {order} ke refund" if order else "ek refund")
    return (f" on behalf of {name}" if name else " on behalf of a customer"), (f"the refund for order {order}" if order else "a refund")


# -- moves ----------------------------------------------------------------------------------------------------------


def _move(intent: str, suggested: str, must: tuple[str, ...] = (), facts: dict | None = None, fixed: bool = False, cited: bool = False) -> dict:
    return {"intent": intent, "suggested": suggested, "points": split_sentences(suggested), "must": list(must), "facts": facts or {},
            "fixed": fixed, "cited": cited}


REF = r"(?i)refer|ticket|संदर्भ|टिकट"
DATE = r"(?i)date|by when|तारीख|कब तक|kab tak|which day"
CAN_NOT = r"(?i)not able|cannot|can't|never|unable|nahi|नहीं|sorry|maaf|क्षमा"


class _View:
    """What a node needs about the mandate and the disclosable facts, read fresh each turn."""

    def __init__(self, ports: OutreachPorts, call: dict) -> None:
        self.mandate = ports.case_store.get_mandate(call["case_id"], call["mandate_version"])
        self.facts = {f.field: f for f in ports.case_store.get_disclosable_facts(call["case_id"], call["mandate_version"])}
        self.allowed = (set(self.mandate.disclosure) | set(ALWAYS_ALLOWED)) if self.mandate else set()
        self.language = call["language"]
        self.for_whom, self.subject = _who(self.language, self.facts)

    def line(self, key: str, **kw) -> str:
        return lines.line(key, self.language, for_whom=self.for_whom, subject=self.subject, **kw)


def _ask_by(ports: OutreachPorts, language: str) -> str:
    day = ports.now().date() + timedelta(days=ASK_BY_DAYS)
    return f"{day.day} {day.strftime('%B')}"


def _owed(ports: OutreachPorts, call: dict, view: _View) -> float | None:
    evidence = ports.store.case_evidence(call["case_id"])
    value = normalise_amount(evidence.paid_amount) or (normalise_amount(view.facts["amount"].value) if "amount" in view.facts else "")
    return float(value) if value else None


def _record_once(call: dict, key: str) -> bool:
    """True the first time a key is seen: the caller makes the record only then."""
    if key in call["effects"]:
        return False
    call["effects"].append(key)
    return True


def _approval(ports: OutreachPorts, call: dict, kind: str, payload: dict, key: str) -> str:
    full = f"{kind}:{call['call_id']}:{key}"
    if full not in call["approvals"]:
        call["approvals"][full] = ports.approvals.create(call["case_id"], kind, payload, full)
    return call["approvals"][full]


def _end(call: dict, reason: str) -> None:
    if not call["ended"]:
        call["ended"] = True
        call["end_reason"] = reason


# -- understanding the turn -----------------------------------------------------------------------------------------


def understand(ports: OutreachPorts, text: str) -> tuple[Understood, dict]:
    """Screen (signal only), classify, then cross-check the model with the keyword reader on the two dangerous labels
    and on the known weakness: the classifier reads Devanagari turns as `stall`."""
    # The injection screen and the classifier do not depend on each other (the screen result only marks the turn), so they run together.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending_screen = pool.submit(screen_turn, ports.screen, text)
        u = classify_turn(ports.classifier, text, None)
        screen = pending_screen.result()
    u = replace(u, injection_signal=bool(screen.marked), screen_score=screen.score)
    label, overridden = u.label, ""
    if text.strip():
        keyword = keyword_turn_label(text)
        if keyword == "injection_attempt" and label != "injection_attempt":
            label, overridden = "injection_attempt", "keywords"
        elif keyword == "request_for_data" and label not in ("request_for_data", "injection_attempt") and asks_for_something(text):
            label, overridden = "request_for_data", "keywords"
        elif label == "stall" and _DEVANAGARI.search(text) and keyword not in ("claim", "stall"):
            label, overridden = keyword, "keywords_devanagari"
    info = {"label": label, "model_label": u.label, "confidence": round(u.confidence, 3), "source": u.source, "degraded": u.degraded,
            "overridden": overridden, "screen_level": screen.level, "screen_score": round(screen.score, 4)}
    return u, info


def decide_route(text: str, label: str, call: dict, ports: OutreachPorts, view: _View) -> str:
    if not text.strip():
        return "silence"
    if label == "injection_attempt" or _INJECTION_WORDS.search(text):
        return "injection"
    fields = requested_fields(text)
    sensitive = [f for f in fields if f in SENSITIVE]
    if label == "request_for_data" or (sensitive and asks_for_something(text)):
        return "data"
    if redirect_number(text) and label in ("stall", "claim", "offer", "question"):
        return "redirect"
    kind = claim_kind(text)
    pdate = promise_date(text, ports.now().date(), ports.normalise)
    if kind == "processed" and not pdate and label in ("offer", "claim", "stall", "question"):
        return "claim"  # a statement that money was already paid is a claim to check, whatever the label says
    if label == "offer" or (label in ("claim", "stall", "question") and (looks_like_offer(text) or (pdate and kind != "processed"))):
        return "offer"
    if label == "claim":
        return "claim"
    if label == "question":
        return "question"
    if label == "stall":
        return "claim" if kind in ("processed", "no_request", "delivered", "policy") else "stall"
    if label == "hostile":
        return "hostile"
    return "claim"


# -- handlers: each returns a list of moves and updates the call ---------------------------------------------------


def h_injection(ports, call, text, view) -> list[dict]:
    call["injections"] += 1
    ports.case_store.record_event(call["case_id"], "injection_ignored", {"turn": call["turns"]})
    return [_move("injection_restate", view.line("injection_restate"), (r"(?i)refund|रिफंड",))]


def h_data(ports, call, text, view) -> list[dict]:
    fields = requested_fields(text)
    lang = view.language
    never = [f for f in fields if f in NEVER_SHARE]
    answerable = [f for f in fields if f in view.allowed and f in view.facts and f not in NEVER_SHARE]
    unlisted = [f for f in fields if (f in SENSITIVE or f in lines.FIELD_NOUN) and f not in NEVER_SHARE and f not in answerable]
    moves: list[dict] = []
    if answerable:
        values = {}
        parts = []
        for f in answerable:
            fact = view.facts[f]
            value = fact.value if fact.certainty != "approximate" else f"approximately {fact.value}"
            values[f] = value
            if f in lines.FIELD_LABEL:
                parts.append(lines.line("answer_field", lang, label=lines.FIELD_LABEL[f][lines.lang_of(lang)], value=value))
            else:  # a sensitive field the consumer chose to list on the mandate
                parts.append(f"{f.replace('_', ' ').capitalize()}: {value}.")
        moves.append(_move("answer_fields", " ".join(parts), facts=values))
    if never:
        moves.append(_move("decline_never", view.line("decline_never"), (CAN_NOT,)))
        ports.case_store.record_event(call["case_id"], "data_request_refused", {"fields": never, "turn": call["turns"]})
    if unlisted:
        key = ",".join(sorted(unlisted))
        asked = key not in call["data_requests"]
        _approval(ports, call, "disclosure", {"call_id": call["call_id"], "fields": sorted(unlisted), "turn": call["turns"], "asked_by": "provider"}, key)
        if asked:
            call["data_requests"].append(key)
        moves.append(_move("decline_unlisted", view.line("decline_unlisted"), (CAN_NOT,)))
        moves.append(_move("asked_customer", view.line("asked_customer"), (r"(?i)customer|ग्राहक",)))
    if never or unlisted:
        call["data_declines"] += 1
        allowed_names = [f for f in lines.FIELD_NOUN if f in view.facts and f in view.allowed]
        moves.append(_move("offer_alternatives", view.line("offer_alternatives", names=lines.noun_list(allowed_names, lang))))
        if call["data_declines"] >= DATA_LIMIT:
            _end(call, "repeated_data_requests")
            moves.append(_move("end_turns", view.line("end_turns")))
    if not moves:
        moves.append(_move("general_ask", view.line("general_ask")))
    return moves


def h_question(ports, call, text, view) -> list[dict]:
    fields = [f for f in requested_fields(text) if f in lines.FIELD_NOUN or f in SENSITIVE]
    if fields:
        return h_data(ports, call, text, view)
    return [_move("purpose", view.line("purpose"), (r"(?i)refund|रिफंड",))]


def _note_claim(call: dict, kind: str, text: str) -> dict | None:
    """Track what the provider asserts about the refund; two different assertions are a contradiction to report."""
    if kind not in CONTRADICTORY:
        return None
    earlier = [k for k in call["claim_kinds"] if k != kind]
    call["claim_kinds"].append(kind)
    if earlier:
        pair = {"first": earlier[0], "second": kind, "turn": call["turns"]}
        call["contradictions"].append(pair)
        return pair
    return None


def _remember_references(ports, call, text, view) -> list[str]:
    order = normalise_reference(ports.store.case_evidence(call["case_id"]).order_id)
    raw = []
    for written, norm in reference_pairs(text):
        if norm == order:
            continue
        raw.append(written)
        if norm not in {normalise_reference(r) for r in call["provider_ids"]}:
            call["provider_ids"].append(written)
        call["reference"] = written
    return raw


def h_claim(ports, call, text, view) -> list[dict]:
    kind = claim_kind(text)
    today = ports.now().date()
    refs = _remember_references(ports, call, text, view)
    if is_refusal(text):
        call["refusals"] += 1
    contradiction = _note_claim(call, kind, text)
    if contradiction:
        ports.case_store.record_event(call["case_id"], "provider_contradiction", contradiction)
        lang = lines.lang_of(view.language)
        first, second = (lines.CLAIM_PHRASE[contradiction[k]][lang] for k in ("first", "second"))
        if kind == "processed":  # the new claim is still checked and recorded; the reply is about the contradiction
            _evidence_moves(ports, call, text, view, today)
        return [_move("contradiction", view.line("contradiction", first=first, second=second), (REF,))]
    if kind == "processed":
        return _evidence_moves(ports, call, text, view, today)
    if kind == "policy":
        return _policy_moves(ports, call, text, view)
    if refs and call["promise"]["date"]:  # a date was promised earlier and the reference has now come
        call["promise"]["reference"] = call["reference"]
        return _secure(ports, call, view)
    if refs:
        ref_line = view.line("reference_noted", reference=refs[0])
        tail = view.line("ask_date") if not call["promise"]["date"] else ""
        return [_move("reference_noted", " ".join(x for x in (ref_line, tail) if x), (REF,))]
    if call["refusals"] >= REFUSAL_LIMIT:
        _end(call, "repeated_refusal")
        return [_move("hostile_end", view.line("hostile_end"))]
    return [_move("claim_generic", view.line("claim_generic"), (DATE,))]


def _evidence_moves(ports, call, text, view, today) -> list[dict]:
    evidence: CaseEvidence = ports.store.case_evidence(call["case_id"])
    verdict = check_case_evidence(text, evidence, today, ports.normalise)
    call["claims"].append({"turn": call["turns"], "kind": "processed", "verdict": verdict.as_dict()})
    ports.case_store.record_event(call["case_id"], "provider_claim_checked", {"turn": call["turns"], "overall": verdict.overall,
                                                                           "fields": [f.field + ":" + f.verdict for f in verdict.fields]})
    lang = lines.lang_of(view.language)
    if verdict.overall == "match":
        return [_move("evidence_match", view.line("evidence_match"), (REF,))]
    if verdict.overall == "mismatch":
        clause = ""
        owed = verdict.get("amount_owed")
        if owed and owed.verdict == "mismatch" and "amount" in view.facts and "amount" in view.allowed:
            clause = {"en": " (the customer paid {a} rupees)", "hi": " (ग्राहक ने {a} रुपये दिए थे)",
                      "hinglish": " (customer ne {a} rupaye diye the)"}[lang].format(a=view.facts["amount"].value)
        return [_move("evidence_mismatch", view.line("evidence_mismatch", owed_clause=clause), (REF,))]
    return [_move("evidence_missing", view.line("evidence_missing"), (REF, r"(?i)no record|not (?:received|seen)|nahi|नहीं|not found"))]


def _policy_moves(ports, call, text, view) -> list[dict]:
    """retrieve_and_compare: a rule or deadline may be said only with a retrieved chunk id (answer_with_citations)."""
    try:
        result = answer_with_citations(ports.llm, ports.retriever, f"Is it true that: {text}", entity_type=call["entity_type"], language=lines.lang_of(view.language),
                                       role=ports.draft_role)
    except Exception as exc:  # noqa: BLE001 - retrieval or the model failing must not stop the call
        ports.case_store.record_event(call["case_id"], "policy_check_failed", {"error": type(exc).__name__})
        result = None
    if result is not None and result.kind == "grounded":
        call["claims"].append({"turn": call["turns"], "kind": "policy", "cited": [c.chunk_id for c in result.citations], "disclaimer": result.disclaimer})
        ports.case_store.record_event(call["case_id"], "provider_claim_checked", {"turn": call["turns"], "policy": True,
                                                                               "cited": [c.chunk_id for c in result.citations]})
        moves = [_move("policy_answer", sentence, fixed=True, cited=True) for sentence in split_sentences(result.text)]
        moves.append(_move("ask_clause", view.line("ask_clause"), (r"(?i)clause|खंड|section",)))
        return moves
    call["claims"].append({"turn": call["turns"], "kind": "policy", "cited": []})
    return [_move("policy_unknown", view.line("policy_unknown"), (r"(?i)clause|खंड|check|जाँच",))]


def _offer_desc(offer, lang: str) -> str:
    amount = f"{offer.amount:g}" if offer.amount is not None else ""
    kinds = {"voucher": {"en": "your voucher offer", "hi": "आपका वाउचर ऑफ़र", "hinglish": "aapka voucher offer"},
             "replacement": {"en": "your replacement offer", "hi": "आपका बदलने का ऑफ़र", "hinglish": "aapka replacement offer"},
             "discount": {"en": "your discount offer", "hi": "आपका छूट का ऑफ़र", "hinglish": "aapka discount offer"}}
    if offer.kind in kinds:
        return kinds[offer.kind][lang]
    if amount:
        return {"en": f"your offer of {amount} rupees", "hi": f"आपका {amount} रुपये का ऑफ़र", "hinglish": f"aapka {amount} rupaye ka offer"}[lang]
    return {"en": "your offer", "hi": "आपका ऑफ़र", "hinglish": "aapka offer"}[lang]


def h_offer(ports, call, text, view) -> list[dict]:
    today = ports.now().date()
    lang = lines.lang_of(view.language)
    offer = parse_offer(text, ports.normalise)
    owed = _owed(ports, call, view)
    limits = view.mandate.limits if view.mandate else {}
    verdict, reason = compare_to_mandate(offer, limits, owed)
    refs = _remember_references(ports, call, text, view)
    pdate = promise_date(text, today, ports.normalise)
    record = {"turn": call["turns"], "kind": offer.kind, "amount": offer.amount, "waiver": offer.waiver, "verdict": verdict, "reason": reason,
              "date": pdate or ""}
    call["offers"].append(record)
    if _record_once(call, f"offer:{call['call_id']}:{call['turns']}"):
        ports.store.record_offer(call["case_id"], call["call_id"], dict(record), f"offer:{call['call_id']}:{call['turns']}")
    if verdict == "outside":  # record the offer, pause, end the call, never accept
        _end(call, "offer_outside_mandate")
        return [_move("offer_outside", view.line("offer_outside", offer_desc=_offer_desc(offer, lang)), (CAN_NOT, r"(?i)customer|ग्राहक"))]
    if pdate:
        call["promise"]["date"] = pdate
    if refs or call["reference"]:
        call["promise"]["reference"] = call["reference"]
    if call["promise"]["date"] and call["promise"]["reference"]:
        return _secure(ports, call, view)
    if call["promise"]["date"]:
        return [_move("ask_reference", view.line("ask_reference"), (REF,))]
    if call["promise"]["reference"]:
        return [_move("ask_date", view.line("ask_date"), (DATE,))]
    return [_move("ask_reference_and_date", view.line("ask_reference_and_date"), (REF,))]


def _secure(ports, call, view) -> list[dict]:
    promise = {"by_when": call["promise"]["date"], "reference": call["promise"]["reference"], "what": "refund to the consumer"}
    if promise not in call["promises"]:
        call["promises"].append(promise)
    _end(call, "promise_secured")
    day = datetime.fromisoformat(promise["by_when"])
    spoken = f"{day.day} {day.strftime('%B')}"
    return [_move("promise_secured", view.line("promise_secured", date=spoken, reference=promise["reference"]), (REF,), facts={"date": spoken, "reference": promise["reference"]})]


def h_stall(ports, call, text, view) -> list[dict]:
    call["stalls"] += 1
    if call["stalls"] >= STALL_LIMIT:
        ports.case_store.record_event(call["case_id"], "provider_stalled", {"count": call["stalls"]})
        _end(call, "escalate_after_stalls")
        return [_move("stall_escalate", view.line("stall_escalate"))]
    return [_move("stall_restate", view.line("stall_restate", ask_by=_ask_by(ports, view.language)), (DATE,))]


def h_hostile(ports, call, text, view) -> list[dict]:
    call["refusals"] += 1
    if call["refusals"] >= REFUSAL_LIMIT:
        _end(call, "repeated_refusal")
        return [_move("hostile_end", view.line("hostile_end"))]
    key = "hostile_first" if call["refusals"] == 1 else "hostile_second"
    return [_move(key, view.line(key, ask_by=_ask_by(ports, view.language)))]


def h_silence(ports, call, text, view) -> list[dict]:
    call["silences"] += 1
    if call["silences"] >= SILENCE_LIMIT:
        _end(call, "no_response")
        return [_move("silence_end", view.line("silence_end"))]
    if call["silences"] == 1:
        return [_move("silence_check", view.line("silence_check"), (r"(?i)anyone|कोई|koi",))]
    return []  # wait quietly, do not fill the silence


def h_redirect(ports, call, text, view) -> list[dict]:
    number = redirect_number(text)
    call["redirects"].append({"number": number, "turn": call["turns"]})
    _approval(ports, call, "contact", {"call_id": call["call_id"], "number": number, "source": "provider_redirect"}, number)
    return [_move("redirect", view.line("redirect", number=number), (r"(?i)ticket|टिकट|log",))]


HANDLERS = {"injection": h_injection, "data": h_data, "question": h_question, "claim": h_claim, "offer": h_offer, "stall": h_stall,
            "hostile": h_hostile, "silence": h_silence, "redirect": h_redirect}


# -- drafting and speaking ------------------------------------------------------------------------------------------


def _acceptable(text: str, group: list[dict]) -> bool:
    text = text.strip()
    if not text or len(text) > 700 or len(split_sentences(text)) > 5:
        return False
    for move in group:
        for pattern in move["must"]:
            if not re.search(pattern, text, re.S):
                return False
    cited = any(m["cited"] for m in group)
    if not cited and (_DEADLINE.search(text) or _THREAT.search(text)):
        return False  # a deadline or a legal remark needs a retrieved source
    return True


def draft_group(ports: OutreachPorts, call: dict, group: list[dict], provider_text: str) -> list[str]:
    """One model call for a run of moves; the draft is checked in code and replaced by the suggested wording if it misses a point."""
    suggested = " ".join(m["suggested"] for m in group)
    call["drafts"] += 1
    try:
        context = build_call_context(ports.case_store, call["case_id"], call["mandate_version"], ports.now(), call["provider"], call["language"])
        system = context.system_prompt + "\n\n" + prompts.load("outreach_draft").text
        variables = dict(context.variables)
        variables["move"] = {
            "points": [p for m in group for p in m["points"]], "suggested": suggested,
            "facts": {k: v for m in group for k, v in m["facts"].items()},
        }
        variables["provider_said"] = provider_text
        text, _usage = ports.llm.text(ports.draft_role, system, variables)
    except MandateBlocked:
        raise
    except Exception as exc:  # noqa: BLE001 - the draft model being down must not stop the call
        if is_budget_error(exc):
            raise  # but a used-up spending cap does stop it, cleanly (OutreachRunner closes the call)
        text = ""
    if text and _acceptable(text, group):
        return split_sentences(text)
    call["draft_fallbacks"] += 1
    return split_sentences(suggested)


def compose(ports: OutreachPorts, call: dict, moves: list[dict], provider_text: str) -> list[str]:
    out: list[str] = []
    group: list[dict] = []
    for move in moves:
        if move["fixed"]:
            if group:
                out += draft_group(ports, call, group, provider_text)
                group = []
            out += move["points"]
        else:
            group.append(move)
    if group:
        out += draft_group(ports, call, group, provider_text)
    return out


def speak(ports: OutreachPorts, call: dict, drafted: list[str], provider_text: str) -> list[str]:
    """Every sentence goes through OutputGuard.speak. A blocked one becomes the holding phrase (once) and is logged."""
    ctx = build_guard_context(ports.case_store, call["case_id"], call["mandate_version"], heard=tuple(call["heard"]), canaries=ports.canaries)
    spoken: list[str] = []
    held = 0
    language = call["language"]
    for sentence in drafted:
        guarded = ports.guard.speak(sentence, ctx, provider_text, language)
        if guarded.verdict.blocked:
            held += 1
            call["held"].append({"turn": call["turns"], "categories": guarded.verdict.categories})
            if spoken and spoken[-1] == guarded.text:
                continue
        spoken.append(guarded.text)
        if ports.on_sentence:
            ports.on_sentence(guarded.text)
    if held:
        ports.case_store.record_event(call["case_id"], "agent_reply_held", {"turn": call["turns"], "count": held})
    for text in spoken:
        call["transcript"].append({"who": "agent", "text": text})
    return spoken


# -- summary, reconciliation, case update ---------------------------------------------------------------------------


def _record_for_summary(call: dict) -> dict:
    return {
        "outcome": call["end_reason"], "turns": call["turns"], "promises": call["promises"],
        "offers": [{"kind": o["kind"], "amount": o["amount"], "within_mandate": o["verdict"] == "within"} for o in call["offers"]],
        "claims_checked": [{"kind": c["kind"], "evidence": (c.get("verdict") or {}).get("overall", ""), "cited": bool(c.get("cited"))} for c in call["claims"]],
        "contradictions": call["contradictions"], "details_requested_and_declined": call["data_requests"],
        "redirects": [r["number"] for r in call["redirects"]], "stalls": call["stalls"], "replies_held_back": len(call["held"]),
        "references_given": call["provider_ids"], "disagreements": call["reconciled"],
    }


_OUTCOME_TEXT = {
    "promise_secured": "The company gave a dated promise with a reference number.",
    "offer_outside_mandate": "The company made an offer that is outside what you allowed. I did not accept or counter it and ended the call so you can decide.",
    "escalate_after_stalls": "The company kept stalling and gave no date, so I ended the call. You may want to escalate.",
    "repeated_refusal": "The company refused repeatedly, so I ended the call politely.",
    "repeated_data_requests": "The company kept asking for details I may not share, so I ended the call.",
    "no_response": "Nobody answered on the line, so I ended the call.",
    "time_limit": "The call reached its time limit and I ended it.",
    "turn_limit": "The call reached its turn limit and I ended it.",
    "ended_by_consumer": "The call was ended.",
    "mandate_blocked": "The call stopped because your permission is no longer valid.",
    "budget_exhausted": "The call was stopped because the usage limit of this service was reached. Nothing was agreed; you can continue later.",
}


def summary_text(ports: OutreachPorts, call: dict, record: dict) -> str:
    base = [_OUTCOME_TEXT.get(call["end_reason"], "The call has ended.")]
    for promise in call["promises"]:
        base.append(f"Promise: refund by {promise['by_when']}, reference {promise['reference']}.")
    for offer in call["offers"]:
        what = f"{offer['kind']} of {offer['amount']:g}" if offer["amount"] is not None else offer["kind"]
        base.append(f"Offer noted, not accepted: {what}. You decide through the app.")
    for claim in call["claims"]:
        if claim["kind"] == "processed":
            base.append(f"The company said the refund was already processed; checked against your evidence: {claim['verdict']['overall']}. Nothing is confirmed until you confirm it.")
    if call["contradictions"]:
        base.append("The company gave contradictory answers.")
    if call["data_requests"]:
        base.append("The company asked for details you did not list; I declined and asked you whether to allow them.")
    if call["held"]:
        base.append("I held back some replies that did not pass the safety check.")
    fallback = " ".join(base)
    try:
        text, _usage = ports.llm.text(SUMMARY_ROLE, prompts.load("call_summary").text, {"record": record, "language": call["language"]})
    except Exception:  # noqa: BLE001
        return fallback
    text = (text or "").strip()
    if not text or len(text) > 1500:
        return fallback
    ctx = build_guard_context(ports.case_store, call["case_id"], call["mandate_version"], heard=tuple(call["heard"]), canaries=ports.canaries)
    # The consumer reads this, but it must not carry a stored secret or a canary either: check the deterministic layer.
    if {"unlisted_disclosure", "otp_or_card"} & set(ports.guard.scan(text, ctx, "")[0]):
        return fallback
    return text


def reconcile_provider_facts(ports: OutreachPorts, call: dict) -> list[dict]:
    """Compare what the provider said with what the case holds, on normalised values."""
    evidence = ports.store.case_evidence(call["case_id"])
    owed = normalise_amount(evidence.paid_amount)
    out: list[dict] = []
    for offer in call["offers"]:
        if offer["amount"] is not None and owed:
            same = f"{offer['amount']:g}" == owed
            out.append({"field": "amount", "provider": f"{offer['amount']:g}", "verdict": "match" if same else "different"})
    order = normalise_reference(evidence.order_id)
    for written in call["provider_ids"]:
        if re.fullmatch(r"[A-Z]{2}\d{6,}", written) and order and normalise_reference(written) != order:
            out.append({"field": "order_id", "provider": written, "verdict": "different"})
    return out


# -- the graph ------------------------------------------------------------------------------------------------------


def build_outreach_graph(ports: OutreachPorts):
    gate = build_mandate_gate(ports.case_store, ports.now)

    def load_call(state: OutreachState) -> dict:
        call = ports.store.load_call(state["call_id"])
        return {"call": call if call is not None else {}, "sentences": [], "phase": "provider_call"}

    def check_mandate(state: OutreachState) -> dict:
        if state["event"] == "end":
            return {"status": "ready"}
        call = state["call"]
        version = call.get("mandate_version") if call else None
        result = gate.invoke({"case_id": state["case_id"], "mandate_version": version})
        if result["status"] == "ready":
            if call is not None and not call:
                call["mandate_version"] = result["mandate_version"]
            return {"status": "ready", "call": call}
        return {"status": "blocked", "block_reason": result["block_reason"]}

    def request_mandate(state: OutreachState) -> dict:
        call = state["call"]
        if call and not call["ended"]:
            _end(call, "mandate_blocked")
            ports.store.save_call(state["call_id"], call)
        return {"phase": "blocked", "sentences": []}

    def retrieve_rules_and_policy(state: OutreachState) -> dict:
        call = state["call"]
        provider = ports.store.provider(state["case_id"])
        call.update(new_call(state["case_id"], state["call_id"], ports.store.language(state["case_id"]), provider, call["mandate_version"], ports.now()))
        try:
            chunks = ports.retriever.search("refund for a cancelled online order not received, return and refund timelines", provider.get("entity_type"), 6)
            call["chunk_ids"] = [c.id for c in chunks]
        except Exception as exc:  # noqa: BLE001
            ports.case_store.record_event(state["case_id"], "retrieval_failed", {"error": type(exc).__name__})
        return {"call": call}

    def build_call_plan(state: OutreachState) -> dict:
        call = state["call"]
        mandate = ports.case_store.get_mandate(state["case_id"], call["mandate_version"])
        call["plan"] = {
            "goal": mandate.goal, "ask_by": (ports.now().date() + timedelta(days=ASK_BY_DAYS)).isoformat(),
            "steps": ["introduce", "state_request", "get_reference_and_date", "record_offers_for_consumer"],
            "chunk_ids": list(call["chunk_ids"]), "entity_type": call["entity_type"],
        }
        return {"call": call}

    def open_call(state: OutreachState) -> dict:
        call = state["call"]
        ports.store.set_status(state["case_id"], "outreach")
        ports.case_store.record_event(state["case_id"], "call_started", {"call_id": state["call_id"], "mandate_version": call["mandate_version"]})
        view = _View(ports, call)
        moves = [_move("open", view.line("open"), (r"(?i)AI|एआई",))]
        sentences = speak(ports, call, compose(ports, call, moves, ""), "")
        ports.store.save_call(state["call_id"], call)
        return {"call": call, "sentences": sentences, "phase": "provider_call"}

    def limits(state: OutreachState) -> dict:
        call = state["call"]
        if call.get("ended"):
            return {}
        started = datetime.fromisoformat(call["started_at"])
        mandate = ports.case_store.get_mandate(state["case_id"], call["mandate_version"])
        if (ports.now() - started).total_seconds() >= mandate.call_limit_seconds:
            _end(call, "time_limit")
            view = _View(ports, call)
            sentences = speak(ports, call, [view.line("end_time")], "")
            return {"call": call, "sentences": sentences}
        return {}

    def hear_provider(state: OutreachState) -> dict:
        call = state["call"]
        text = state["text"].strip()
        call["turns"] += 1
        call["transcript"].append({"who": "provider", "text": text})
        for value in heard_from(text, ports.normalise or spoken_to_digits):
            if value not in call["heard"]:
                call["heard"].append(value)
        ports.store.save_call(state["call_id"], call)
        return {"call": call}

    def injection_screen_and_classify(state: OutreachState) -> dict:
        call = state["call"]
        u, info = understand(ports, state["text"])
        if info["screen_level"] != "none":
            ports.case_store.record_event(state["case_id"], "injection_signal", {"score": info["screen_score"], "level": info["screen_level"], "turn": call["turns"]})
        if info["degraded"]:
            ports.case_store.record_event(state["case_id"], "classifier_degraded", {"turn": call["turns"]})
        view = _View(ports, call)
        route = decide_route(state["text"], info["label"], call, ports, view)
        return {"understood": info, "route": route}

    def handle(state: OutreachState) -> dict:
        call = state["call"]
        view = _View(ports, call)
        moves = HANDLERS[state["route"]](ports, call, state["text"], view)
        if not call["ended"] and call["turns"] >= TURN_LIMIT:
            _end(call, "turn_limit")
            moves.append(_move("end_turns", view.line("end_turns")))
        return {"moves": moves, "call": call}

    def draft_and_speak(state: OutreachState) -> dict:
        call = state["call"]
        drafted = compose(ports, call, state["moves"], state["text"])
        sentences = speak(ports, call, drafted, state["text"])
        if call["ended"] and sentences and sentences[-1] in {h for h in HOLDING.values()}:
            # the last thing said on a call must not be a held sentence: close politely
            sentences += speak(ports, call, [lines.line("end_consumer", call["language"])], state["text"])
        return {"sentences": sentences, "call": call}

    def after_turn(state: OutreachState) -> str:
        return "finish" if state["call"]["ended"] else "save"

    def save(state: OutreachState) -> dict:
        ports.store.save_call(state["call_id"], state["call"])
        return {}

    def end_event(state: OutreachState) -> dict:
        call = state["call"]
        if call and not call["ended"]:
            _end(call, state.get("reason") or "ended_by_consumer")
            view = _View(ports, call)
            closing = "end_budget" if call["end_reason"] == "budget_exhausted" else "end_consumer"
            sentences = speak(ports, call, [view.line(closing)], "")
            return {"sentences": sentences, "call": call}
        return {}

    def post_call_summary(state: OutreachState) -> dict:
        call = state["call"]
        ports.store.save_call(state["call_id"], call)  # the call is closing: a restart resumes from here
        if call["finished"]:
            return {}
        record = _record_for_summary(call)
        call["summary"] = {"text": summary_text(ports, call, record), "record": record}
        return {"call": call}

    def reconcile_facts(state: OutreachState) -> dict:
        call = state["call"]
        if call["finished"]:
            return {}
        call["reconciled"] = reconcile_provider_facts(ports, call)
        call["summary"]["record"]["disagreements"] = call["reconciled"]
        return {"call": call}

    def update_case(state: OutreachState) -> dict:
        call = state["call"]
        if call["finished"]:
            return {}
        for index, promise in enumerate(call["promises"]):
            key = f"promise:{call['call_id']}:{index}"
            if _record_once(call, key):
                ports.store.save_promise(state["case_id"], call["call_id"], "provider", promise["what"], promise["by_when"], promise["reference"], key)
        verified = any(c["kind"] == "processed" and c["verdict"]["overall"] == "match" for c in call["claims"])
        status = "provider_claimed_resolved" if verified else "awaiting_consumer"  # a claim alone is never resolved
        call["status"] = status
        ports.store.set_status(state["case_id"], status)
        ports.store.save_summary(state["case_id"], call["call_id"], call["summary"])
        ports.case_store.record_event(state["case_id"], "call_ended", {"call_id": call["call_id"], "reason": call["end_reason"], "turns": call["turns"]})
        return {"call": call}

    def request_approval(state: OutreachState) -> dict:
        call = state["call"]
        if not call["finished"]:
            payload = {"call_id": call["call_id"], "outcome": call["end_reason"], "summary": call["summary"]["text"], "simulated": True,
                       "promises": call["promises"], "offers": [o for o in call["offers"]], "suggest_escalation": call["end_reason"] == "escalate_after_stalls"}
            call["approval_id"] = _approval(ports, call, "summary", payload, "summary")
            call["finished"] = True
        ports.store.save_call(state["call_id"], call)
        return {"call": call, "approval_id": call["approval_id"], "phase": "summary"}

    def first_route(state: OutreachState) -> str:
        return {"start": "start", "turn": "turn", "end": "end"}[state["event"]]

    def after_load(state: OutreachState) -> str:
        if state["event"] == "start":
            return "check" if not state["call"] else "already_open"
        if not state["call"]:
            return "no_call"
        return "check"

    def after_gate(state: OutreachState) -> str:
        if state["status"] != "ready":
            return "blocked"
        return {"start": "start", "turn": "turn", "end": "end"}[state["event"]]

    def after_limits(state: OutreachState) -> str:
        call = state["call"]
        if call["finished"]:
            return "done"
        if call["ended"]:
            return "finish"
        return "hear"

    builder = StateGraph(OutreachState)
    for name, fn in [
        ("load_call", load_call), ("check_mandate", check_mandate), ("request_mandate", request_mandate),
        ("retrieve_rules_and_policy", retrieve_rules_and_policy), ("build_call_plan", build_call_plan), ("open_call", open_call),
        ("limits", limits), ("hear_provider", hear_provider), ("classify_turn", injection_screen_and_classify), ("handle", handle),
        ("draft_and_speak", draft_and_speak), ("save", save), ("end_event", end_event),
        ("post_call_summary", post_call_summary), ("reconcile_facts", reconcile_facts), ("update_case", update_case),
        ("request_approval", request_approval),
    ]:
        builder.add_node(name, fn)
    builder.add_edge(START, "load_call")
    builder.add_conditional_edges("load_call", after_load, {"check": "check_mandate", "already_open": END, "no_call": END})
    builder.add_conditional_edges(
        "check_mandate", after_gate,
        {"blocked": "request_mandate", "start": "retrieve_rules_and_policy", "turn": "limits", "end": "end_event"},
    )
    builder.add_edge("request_mandate", END)
    builder.add_edge("retrieve_rules_and_policy", "build_call_plan")
    builder.add_edge("build_call_plan", "open_call")
    builder.add_edge("open_call", END)
    builder.add_conditional_edges("limits", after_limits, {"done": END, "finish": "post_call_summary", "hear": "hear_provider"})
    builder.add_edge("hear_provider", "classify_turn")
    builder.add_edge("classify_turn", "handle")
    builder.add_edge("handle", "draft_and_speak")
    builder.add_conditional_edges("draft_and_speak", after_turn, {"finish": "post_call_summary", "save": "save"})
    builder.add_edge("save", END)
    builder.add_edge("end_event", "post_call_summary")
    builder.add_edge("post_call_summary", "reconcile_facts")
    builder.add_edge("reconcile_facts", "update_case")
    builder.add_edge("update_case", "request_approval")
    builder.add_edge("request_approval", END)
    return builder.compile()


class OutreachRunner:
    """Thin wrapper over the graph: one call per event, a TurnResult back."""

    def __init__(self, ports: OutreachPorts) -> None:
        self.ports = ports
        self.graph = build_outreach_graph(ports)

    def _invoke(self, case_id: str, call_id: str, event: str, text: str, reason: str) -> dict:
        return self.graph.invoke({"case_id": case_id, "call_id": call_id, "event": event, "text": text, "reason": reason})

    def _result(self, out: dict, early: list[str]) -> TurnResult:
        call = out.get("call") or {}
        return TurnResult(
            sentences=early + list(out.get("sentences") or []), phase=out.get("phase", "provider_call"), ended=bool(call.get("ended")),
            approval_id=out.get("approval_id", call.get("approval_id", "")), end_reason=call.get("end_reason", ""),
            blocked=out.get("block_reason", "") if out.get("status") == "blocked" else "", understood=out.get("understood", {}),
        )

    def _run(self, case_id: str, call_id: str, event: str, text: str = "", reason: str = "") -> TurnResult:
        ports = self.ports
        early: list[str] = []  # lines said while a rate limit was being waited out, ahead of the real reply

        def hold(seconds: float) -> None:
            if early:
                return  # one holding line per event is enough
            language = (ports.store.load_call(call_id) or {}).get("language") or ports.store.language(case_id)
            said = lines.line("hold_wait", language)
            early.append(said)
            if ports.on_sentence:
                ports.on_sentence(said)
            ports.case_store.record_event(case_id, "rate_limited_hold", {"seconds": round(float(seconds), 1)})

        watch = ports.backoff_watch(hold) if ports.backoff_watch and event in ("start", "turn") else nullcontext()
        try:
            with watch:
                out = self._invoke(case_id, call_id, event, text, reason)
        except Exception as exc:  # noqa: BLE001
            if not is_budget_error(exc) or not ports.store.load_call(call_id):
                raise  # nothing was started yet, or not a budget problem: the caller reports it
            # The spending cap is used up. Close the call politely, record why, and hand the summary to the consumer.
            return self._result(self._invoke(case_id, call_id, "end", "", "budget_exhausted"), early)
        return self._result(out, early)

    def start(self, case_id: str, call_id: str) -> TurnResult:
        return self._run(case_id, call_id, "start")

    def turn(self, case_id: str, call_id: str, text: str) -> TurnResult:
        return self._run(case_id, call_id, "turn", text)

    def end(self, case_id: str, call_id: str, reason: str = "ended_by_consumer") -> TurnResult:
        return self._run(case_id, call_id, "end", reason=reason)


_ = HOLDING
