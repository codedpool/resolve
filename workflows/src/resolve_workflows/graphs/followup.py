"""Follow-up graph: what to do after the company writes back, or after a promised date passes without a word.

One invocation handles one event: `reply` (the company's written reply), `deadline` (a reminder or a promised date came
due) or `choice` (the consumer picked an escalation route from the candidates shown). Everything that must survive between
events is the case's follow-up state, kept through the FollowUpStore port, so a worker that dies resumes from what was stored.

    reply    -> classify_reply -> verify_against_case_evidence -> propose_next_step
    deadline ------------------------------------------------------^
    propose_next_step -> [escalate: select_escalation_target] -> [needs a consumer decision: request_approval] -> schedule
    choice   -> request_approval -> schedule

Decisions are made in code. The model only labels the reply (and the keyword reader takes over when it is down or the
reply may not be sent to a model); it never compares numbers: amounts, dates and reference numbers in a claim are checked
against the case's own evidence on normalised values. The graph can leave a case in `awaiting_consumer`, `awaiting_provider`
or `provider_claimed_resolved` and in nothing else: `resolved_consumer_confirmed` is set only by the consumer's own action
in the app, which this graph cannot reach (and `set_status` below refuses it).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from resolve_workflows.nodes.classify_turn import Understood, classify_reply, keyword_reply_label
from resolve_workflows.nodes.escalation import Selection, choose, select_escalation_target
from resolve_workflows.nodes.evidence_check import check_case_evidence
from resolve_workflows.ports import ApprovalPort, Classifier, FollowUpStore, Once

# The statuses this graph may set. A provider's claim, a refusal or silence can never lead to a resolved case.
GRAPH_STATUSES = frozenset({"awaiting_consumer", "awaiting_provider", "provider_claimed_resolved"})
TERMINAL = frozenset({"resolved_consumer_confirmed", "closed", "deleted"})
APPROVAL_KIND = "summary"
KIND_PREFIX = "followup_"
CHECK_REFUND_DAYS = 3
PROVIDER_REPLY_DAYS = 7
CONSUMER_ACTION_DAYS = 3
MAX_REMINDERS = 5
CONSUMER_KINDS = frozenset({KIND_PREFIX + "check_refund", KIND_PREFIX + "choose_route", KIND_PREFIX + "send_info"})  # waiting on the consumer


@dataclass
class FollowUpPorts:
    classifier: Classifier
    store: FollowUpStore
    approvals: ApprovalPort
    once: Once
    now: Callable[[], datetime]
    redactor: object | None = None  # the Redactor port; without it the reply goes to the model as written (tests only)


class FollowUpState(TypedDict, total=False):
    case_id: str
    event: str  # reply | deadline | choice
    text: str
    deadline_id: str
    deadline_kind: str
    choice: str
    fs: dict  # the stored working state
    key: str  # this event's key
    label: str
    understood: dict
    verdict: dict | None
    action: str
    target_status: str
    selection: dict | None
    out: dict


# -- helpers --------------------------------------------------------------------------------------------------------


def event_key(event: str, text: str = "", deadline_id: str = "", choice: str = "", origin: str = "") -> str:
    if event == "reply":
        return "reply:" + hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:16]
    if event == "deadline":
        return "deadline:" + deadline_id
    return "choice:" + hashlib.sha256(f"{origin}:{choice}".encode()).hexdigest()[:16]


def new_state() -> dict:
    return {"processed": {}, "effects": [], "approvals": {}, "reminders": {}, "pending": None, "last": {}, "reminder_count": 0}


def _eff(case_id: str, key: str, what: str) -> str:
    return f"followup:{hashlib.sha256(f'{case_id}:{key}'.encode()).hexdigest()[:24]}:{what}"


def set_status(ports: FollowUpPorts, case_id: str, status: str) -> bool:
    """The only place the graph changes the case status. Refuses anything a provider claim must not lead to, and never
    moves a case that the consumer has already resolved or closed."""
    if status not in GRAPH_STATUSES:
        raise ValueError(f"the follow-up graph may not set the status {status!r}")
    if ports.store.case_status(case_id) in TERMINAL:
        return False
    ports.store.set_status(case_id, status)
    return True


def _describe(label: str, verdict: dict | None, action: str = "") -> str:
    if action == "confirm_or_dispute":
        return "The company said your refund was sent. Please confirm in the app once the money has reached you, or say that it has not."
    if action == "remind_consumer":
        return "This case is waiting for you."
    if label == "resolved_claimed":
        if verdict and verdict["overall"] == "match":
            return "The company says the problem is resolved, and what it says matches your own records."
        if verdict and verdict["overall"] == "mismatch":
            return "The company says the problem is resolved, but what it says does not match your records."
        return "The company says the problem is resolved. Your records cannot confirm it, so it is only a claim."
    return {
        "partial": "The company offered less than you asked for. I have not accepted or answered it.",
        "rejected": "The company refused your request.",
        "needs_info": "The company asked you for more information before it will act.",
        "silence": "The company did not answer by the date it was due.",
    }[label]


# -- the graph ------------------------------------------------------------------------------------------------------


def build_followup_graph(ports: FollowUpPorts):
    store = ports.store

    def load(state: FollowUpState) -> dict:
        fs = store.load(state["case_id"]) or new_state()
        if state["event"] == "choice":
            pending = fs.get("pending")
            key = event_key("choice", choice=state.get("choice", ""), origin=pending["origin"] if pending else "")
        else:
            key = event_key(state["event"], state.get("text", ""), state.get("deadline_id", ""))
        return {"fs": fs, "key": key}

    def route_event(state: FollowUpState) -> str:
        fs, key = state["fs"], state["key"]
        if key in fs["processed"]:
            return "duplicate"  # the same reply, deadline or choice again: the stored answer stands
        if state["event"] == "choice":
            return "choice" if fs.get("pending") else "nothing_pending"
        return state["event"]

    def duplicate(state: FollowUpState) -> dict:
        previous = state["fs"]["processed"].get(state["key"]) or {}
        return {"out": dict(previous, duplicate=True)}

    def nothing_pending(state: FollowUpState) -> dict:
        return {"out": {"event": "choice", "ignored": True, "reason": "no_choice_pending", "needs_choice": False}}

    def classify(state: FollowUpState) -> dict:
        text = state.get("text", "")
        sendable, withheld = text, False
        if ports.redactor is not None and text.strip():
            outcome = ports.redactor.redact_or_withhold(text, {})
            sendable, withheld = outcome.text, bool(outcome.withheld)
        if withheld:  # fail closed: the reply may not go to a model, the keyword reader labels it
            u = Understood(keyword_reply_label(text), 0.0, "keywords", degraded=True, low_confidence=True)
        else:
            u = classify_reply(ports.classifier, sendable)
        return {"label": u.label, "understood": {
            "label": u.label, "confidence": u.confidence, "source": u.source, "degraded": u.degraded,
            "low_confidence": u.low_confidence, "redacted_text": sendable if not withheld else "",
        }}

    def verify(state: FollowUpState) -> dict:
        label = state["label"]
        if label not in {"resolved_claimed", "partial"}:
            return {"verdict": None}
        evidence = store.case_evidence(state["case_id"])
        verdict = check_case_evidence(state.get("text", ""), evidence, ports.now().date())
        return {"verdict": verdict.as_dict()}

    def deadline_label(state: FollowUpState) -> dict:
        label = "reminder" if state.get("deadline_kind") in CONSUMER_KINDS else "silence"  # a reminder to the consumer is not the company's silence
        return {"label": label, "understood": {"label": label, "confidence": 1.0, "source": "rule", "degraded": False, "low_confidence": False, "redacted_text": ""}, "verdict": None}

    def propose(state: FollowUpState) -> dict:
        label, verdict = state["label"], state.get("verdict")
        if state["event"] == "deadline" and state.get("deadline_kind") == KIND_PREFIX + "check_refund":
            return {"action": "confirm_or_dispute", "target_status": "provider_claimed_resolved"}
        if state["event"] == "deadline" and state.get("deadline_kind") in CONSUMER_KINDS:
            return {"action": "remind_consumer", "target_status": "awaiting_consumer"}
        if label == "resolved_claimed":
            if verdict and verdict["overall"] == "match":
                return {"action": "confirm_receipt", "target_status": "provider_claimed_resolved"}
            return {"action": "ask_proof", "target_status": "awaiting_consumer"}
        if label == "partial":
            return {"action": "review_offer", "target_status": "awaiting_consumer"}
        if label == "needs_info":
            return {"action": "provide_info", "target_status": "awaiting_consumer"}
        return {"action": "escalate", "target_status": "awaiting_consumer"}  # rejected, silence

    def after_propose(state: FollowUpState) -> str:
        return {"escalate": "select", "ask_proof": "approve", "review_offer": "approve"}.get(state["action"], "schedule")

    def select(state: FollowUpState) -> dict:
        provider = store.provider(state["case_id"])
        picked = select_escalation_target(provider.get("entity_type", "unknown"), float(provider.get("confidence", 0.0)), store.routes_by_type())
        return {"selection": picked.as_dict()}

    def after_select(state: FollowUpState) -> str:
        return "wait_for_choice" if state["selection"]["needs_choice"] else "approve"

    def _summary(state: FollowUpState) -> str:
        return _describe(state["label"], state.get("verdict"), state["action"])

    def wait_for_choice(state: FollowUpState) -> dict:
        """The provider's type is unknown or held with low confidence: no route is picked. Every candidate goes to the
        consumer, and the case waits for their choice."""
        fs, case_id, key = state["fs"], state["case_id"], state["key"]
        fs["pending"] = {"origin": key, "label": state["label"], "verdict": state.get("verdict"), "selection": state["selection"], "action": state["action"]}
        out = _outcome(state, approval_id="", needs_choice=True)
        return {"out": out, "fs": fs}

    def apply_choice(state: FollowUpState) -> dict:
        fs = state["fs"]
        pending = fs["pending"]
        selection = Selection(pending["selection"]["entity_type"], True, None, tuple(pending["selection"]["candidates"]), pending["selection"]["reason"])
        route = choose(selection, state["choice"])
        if route is None:
            raise ValueError("that route is not one of the candidates")
        sel = dict(pending["selection"], selected=route, needs_choice=False, chosen_by_consumer=True)
        return {"selection": sel, "label": pending["label"], "verdict": pending.get("verdict"), "action": pending["action"],
                "target_status": "awaiting_consumer", "understood": {"label": pending["label"], "source": "stored"}}

    def _outcome(state: FollowUpState, approval_id: str, needs_choice: bool) -> dict:
        return {
            "event": state["event"], "label": state["label"], "understood": {k: v for k, v in state["understood"].items() if k != "redacted_text"},
            "verdict": state.get("verdict"), "action": state["action"], "status": state["target_status"], "summary": _summary(state),
            "escalation": state.get("selection"), "needs_choice": needs_choice, "approval_id": approval_id, "reminder": None,
            "ignored": False, "duplicate": False,
        }

    def request_approval(state: FollowUpState) -> dict:
        fs, case_id, key = state["fs"], state["case_id"], state["key"]
        selection = state.get("selection")
        payload = {
            "type": "follow_up", "action": state["action"], "label": state["label"], "summary": _summary(state),
            "verdict": state.get("verdict"), "target": selection["selected"] if selection else None, "simulated": True,
            "not_sent": "Nothing is sent to anyone until you approve, and in this simulation nothing is sent at all.",
        }
        name = f"approval:{key}"
        if name not in fs["approvals"]:
            fs["approvals"][name] = ports.approvals.create(case_id, APPROVAL_KIND, payload, _eff(case_id, key, "approval"))
        out = _outcome(state, approval_id=fs["approvals"][name], needs_choice=False)
        if state["event"] == "choice":
            fs["pending"] = None
        return {"out": out, "fs": fs}

    def schedule(state: FollowUpState) -> dict:
        fs, case_id, key = state["fs"], state["case_id"], state["key"]
        out = state.get("out") or _outcome(state, approval_id="", needs_choice=bool(fs.get("pending")) and state["action"] == "remind_consumer")
        reminder = _reminder(state["action"], out["needs_choice"], state.get("deadline_kind", ""))
        if reminder is not None and fs["reminder_count"] < MAX_REMINDERS:
            kind, days = reminder
            due = ports.now() + timedelta(days=days)
            name = f"reminder:{key}"
            if name not in fs["reminders"]:
                fs["reminders"][name] = store.schedule_reminder(case_id, due, kind, _eff(case_id, key, "reminder"))
                fs["reminder_count"] += 1
            out["reminder"] = {"id": fs["reminders"][name], "kind": kind, "due_at": due.isoformat()}
        return {"out": out, "fs": fs}

    def finish(state: FollowUpState) -> dict:
        fs, case_id, key, out = state["fs"], state["case_id"], state["key"], dict(state["out"])
        status = out["status"]
        applied = {"done": False}

        def record() -> None:
            store.record_event(case_id, "follow_up", {
                "event": state["event"], "label": out["label"], "action": out["action"], "verdict": (out["verdict"] or {}).get("overall", ""),
                "approval_id": out["approval_id"], "needs_choice": out["needs_choice"], "text": (state.get("understood") or {}).get("redacted_text", ""),
            })

        ports.once(_eff(case_id, key, "event"), record)  # the ledger is the port's `once`: a worker killed and run again does not repeat it
        applied["done"] = set_status(ports, case_id, status)
        out["status"] = status if applied["done"] else store.case_status(case_id)
        fs["processed"][key] = out
        fs["last"] = out
        store.save(case_id, fs)
        return {"out": out, "fs": fs}

    b = StateGraph(FollowUpState)
    for name, fn in [
        ("load", load), ("duplicate", duplicate), ("nothing_pending", nothing_pending), ("classify_reply", classify),
        ("verify_against_case_evidence", verify), ("deadline_label", deadline_label), ("propose_next_step", propose),
        ("select_escalation_target", select), ("wait_for_choice", wait_for_choice), ("apply_choice", apply_choice),
        ("request_approval", request_approval), ("schedule", schedule), ("finish", finish),
    ]:
        b.add_node(name, fn)
    b.add_edge(START, "load")
    b.add_conditional_edges("load", route_event, {
        "duplicate": "duplicate", "nothing_pending": "nothing_pending", "reply": "classify_reply", "deadline": "deadline_label", "choice": "apply_choice",
    })
    b.add_edge("duplicate", END)
    b.add_edge("nothing_pending", END)
    b.add_edge("classify_reply", "verify_against_case_evidence")
    b.add_edge("verify_against_case_evidence", "propose_next_step")
    b.add_edge("deadline_label", "propose_next_step")
    b.add_conditional_edges("propose_next_step", after_propose, {"select": "select_escalation_target", "approve": "request_approval", "schedule": "schedule"})
    b.add_conditional_edges("select_escalation_target", after_select, {"wait_for_choice": "wait_for_choice", "approve": "request_approval"})
    b.add_edge("wait_for_choice", "schedule")
    b.add_edge("apply_choice", "request_approval")
    b.add_edge("request_approval", "schedule")
    b.add_edge("schedule", "finish")
    b.add_edge("finish", END)
    return b.compile()


def _reminder(action: str, needs_choice: bool, deadline_kind: str = "") -> tuple[str, int] | None:
    """When to look at the case again: (deadline kind, days)."""
    if needs_choice:
        return KIND_PREFIX + "choose_route", CONSUMER_ACTION_DAYS
    if action == "remind_consumer":
        return deadline_kind, CONSUMER_ACTION_DAYS
    return {
        "confirm_receipt": (KIND_PREFIX + "check_refund", CHECK_REFUND_DAYS),
        "confirm_or_dispute": (KIND_PREFIX + "check_refund", CHECK_REFUND_DAYS),
        "ask_proof": (KIND_PREFIX + "provider_reply", PROVIDER_REPLY_DAYS),
        "review_offer": (KIND_PREFIX + "provider_reply", PROVIDER_REPLY_DAYS),
        "escalate": (KIND_PREFIX + "escalation_check", PROVIDER_REPLY_DAYS),
        "provide_info": (KIND_PREFIX + "send_info", CONSUMER_ACTION_DAYS),
    }.get(action)


@dataclass
class FollowUpResult:
    event: str
    label: str = ""
    action: str = ""
    status: str = ""
    summary: str = ""
    verdict: dict | None = None
    escalation: dict | None = None
    needs_choice: bool = False
    approval_id: str = ""
    reminder: dict | None = None
    understood: dict = field(default_factory=dict)
    duplicate: bool = False
    ignored: bool = False

    @classmethod
    def of(cls, out: dict) -> "FollowUpResult":
        names = cls.__dataclass_fields__
        return cls(**{k: v for k, v in out.items() if k in names})


class FollowUpRunner:
    """Thin wrapper over the graph: one call per event, a FollowUpResult back."""

    def __init__(self, ports: FollowUpPorts) -> None:
        self.ports = ports
        self.graph = build_followup_graph(ports)

    def _run(self, case_id: str, event: str, **kw) -> FollowUpResult:
        return FollowUpResult.of(self.graph.invoke({"case_id": case_id, "event": event, **kw})["out"])

    def reply(self, case_id: str, text: str) -> FollowUpResult:
        return self._run(case_id, "reply", text=text)

    def deadline(self, case_id: str, deadline_id: str, kind: str = "") -> FollowUpResult:
        return self._run(case_id, "deadline", deadline_id=deadline_id, deadline_kind=kind)

    def choose(self, case_id: str, route_kind: str) -> FollowUpResult:
        return self._run(case_id, "choice", choice=route_kind)
