"""Text intake graph: narrate, then extract, then ask for one missing field at a time, then hand over to confirmation.

One invocation handles one event (a message, the Done button, or a long silence). The agent says nothing
while the consumer is narrating. Nothing here confirms a fact: confirmation is a UI action only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from resolve_workflows import prompts
from resolve_workflows.nodes.extract import extract_facts
from resolve_workflows.ports import LLM, Classifier, InjectionScreen, IntakeStore, Redactor

QUESTION_CAP = 5
PRIORITY = ("company_name", "amount", "order_id", "order_date", "desired_remedy")
PROVIDER_TYPES = ["marketplace", "seller_on_marketplace", "direct_seller", "payment_intermediary", "unknown"]
INJECTION_THRESHOLD = 0.5
DONE_CONFIDENCE = 0.8
DONE_MAX_WORDS = 10

QUESTIONS = {
    "en": {
        "company_name": "Which company is this complaint about?",
        "amount": "How much did you pay, in rupees?",
        "order_id": "What is the order number? You can also type it into the form.",
        "order_date": "On which date did you place the order?",
        "desired_remedy": "What would you like: a refund, a replacement, or something else?",
        "provider_entity_type": "Did you buy from a large shopping platform, from a seller on one, from the company's own site or shop, or did a payment app move the money?",
    },
    "hi": {
        "company_name": "यह शिकायत किस कंपनी के बारे में है?",
        "amount": "आपने कितने रुपये दिए थे?",
        "order_id": "आपका ऑर्डर नंबर क्या है? आप उसे फ़ॉर्म में टाइप भी कर सकते हैं।",
        "order_date": "आपने ऑर्डर किस तारीख को किया था?",
        "desired_remedy": "आप क्या चाहते हैं: पैसे वापस, बदला हुआ सामान, या कुछ और?",
        "provider_entity_type": "आपने किसी बड़े शॉपिंग प्लेटफ़ॉर्म से, उस पर किसी विक्रेता से, कंपनी की अपनी साइट या दुकान से खरीदा, या किसी पेमेंट ऐप से पैसा गया?",
    },
}
FINISHED = {
    "en": "I have noted what you told me. Please check each detail below and confirm it.",
    "hi": "आपने जो बताया वह मैंने लिख लिया है। कृपया नीचे हर जानकारी देखकर पुष्टि करें।",
}
HANDOFF = {
    "en": "I could not get these from our chat, so please type them into the form: {fields}.",
    "hi": "ये जानकारियाँ बातचीत से नहीं मिलीं, कृपया इन्हें फ़ॉर्म में टाइप करें: {fields}।",
}
SILENCE = {
    "en": "Shall I go ahead and note the details? Press Done when you have finished.",
    "hi": "क्या मैं जानकारी लिख लूँ? जब आप बता चुके हों तो Done दबाएँ।",
}
WITHHELD = {
    "en": "I could not safely read part of that message, so I did not keep it. Please type the number into the form instead.",
    "hi": "आपके संदेश का एक हिस्सा मैं सुरक्षित रूप से पढ़ नहीं पाया, इसलिए उसे नहीं रखा। कृपया वह नंबर फ़ॉर्म में टाइप करें।",
}


class IntakeState(TypedDict, total=False):
    case_id: str
    event: str  # message | done | silence
    text: str
    redacted: str
    reply: str | None
    status: str
    handoff_fields: list[str]


@dataclass
class IntakePorts:
    llm: LLM
    classifier: Classifier
    screen: InjectionScreen
    redactor: Redactor
    store: IntakeStore
    reconcile: Callable[[str], None] | None = None  # hook for the live reconciliation step


def _lang(ports: IntakePorts, case_id: str) -> str:
    return "hi" if ports.store.language(case_id) == "hi" else "en"


def build_intake_graph(ports: IntakePorts):
    store = ports.store

    def route(state: IntakeState) -> str:
        return {"message": "screen", "done": "extract", "silence": "silence"}[state["event"]]

    def screen(state: IntakeState) -> dict:
        score = ports.screen.score(state["text"])
        if score >= INJECTION_THRESHOLD:
            store.flag_injection(state["case_id"], score)  # a signal only; the flow never changes because of it
        return {}

    def capture(state: IntakeState) -> dict:
        case_id = state["case_id"]
        result = ports.redactor.redact_or_withhold(state["text"], store.tokens(case_id))
        store.set_tokens(case_id, result.tokens)
        store.append_message(case_id, state["text"], result.text, result.withheld)
        if result.withheld:
            return {"redacted": "", "reply": WITHHELD[_lang(ports, case_id)]}
        return {"redacted": result.text}

    def after_capture(state: IntakeState) -> str:
        if state.get("reply"):
            return "end"
        phase = store.phase(state["case_id"])
        if phase.get("phase") == "asking":
            return "answer"
        if phase.get("phase") == "confirming":
            return "end"
        return "check_done"

    def check_done(state: IntakeState) -> dict:
        words = state["redacted"].split()
        if len(words) > DONE_MAX_WORDS:
            return {"event": "message"}
        prompt = prompts.load("classify_done")
        label, confidence, _ = ports.classifier.classify("classify", prompt.text, state["redacted"], ["done", "more"])
        return {"event": "done" if label == "done" and confidence >= DONE_CONFIDENCE else "message"}

    def after_check(state: IntakeState) -> str:
        return "extract" if state["event"] == "done" else "end"

    def _apply(case_id: str, result, only: set[str] | None = None) -> None:
        tokens = store.tokens(case_id)
        existing = store.fact_values(case_id)
        for name in type(result).model_fields:
            fact = getattr(result, name)
            if not fact.value or (only is not None and name not in only):
                continue
            if only is None and existing.get(name):
                continue
            value = ports.redactor.restore(fact.value, tokens)
            phrase = ports.redactor.restore(fact.original_phrase, tokens)
            store.propose(case_id, name, value, fact.certainty, phrase, fact.ambiguity_note)

    def extract(state: IntakeState) -> dict:
        case_id = state["case_id"]
        narration = store.narration_redacted(case_id)
        result, _usage, _prompt = extract_facts(ports.llm, narration, store.today())
        _apply(case_id, result)
        return {}

    def answer(state: IntakeState) -> dict:
        case_id = state["case_id"]
        field = store.phase(case_id).get("asked_field", "")
        if field == "provider_entity_type":
            prompt = prompts.load("classify_provider_type")
            label, confidence, _ = ports.classifier.classify("classify", prompt.text, state["redacted"], PROVIDER_TYPES)
            value = label if confidence >= 0.5 else "unknown"
            store.propose(case_id, field, value, "stated" if value != "unknown" else "not_stated", state["text"], "")
            return {}
        result, _usage, _prompt = extract_facts(
            ports.llm, f"(answer to the question about {field.replace('_', ' ')}) {state['redacted']}", store.today()
        )
        _apply(case_id, result, only={field} | {n for n in type(result).model_fields if n not in store.fact_values(case_id)})
        return {}

    def next_step(state: IntakeState) -> dict:
        case_id = state["case_id"]
        lang = _lang(ports, case_id)
        have = store.fact_values(case_id)
        asked = store.asked_fields(case_id)
        missing = [f for f in PRIORITY if not have.get(f)]
        questions = [f for f in asked if f in PRIORITY]
        candidates = [f for f in missing if f not in asked]
        if candidates and len(questions) < QUESTION_CAP:
            field = candidates[0]
            store.mark_asked(case_id, field)
            store.set_phase(case_id, "asking", field)
            return {"reply": QUESTIONS[lang][field], "status": "intake"}
        if not missing and "provider_entity_type" not in have and "provider_entity_type" not in asked:
            store.mark_asked(case_id, "provider_entity_type")
            store.set_phase(case_id, "asking", "provider_entity_type")
            return {"reply": QUESTIONS[lang]["provider_entity_type"], "status": "intake"}
        handoff = [f for f in missing]
        reply = FINISHED[lang]
        if handoff:
            reply += " " + HANDOFF[lang].format(fields=", ".join(f.replace("_", " ") for f in handoff))
        store.set_phase(case_id, "confirming")
        store.set_status(case_id, "confirming")
        if ports.reconcile is not None:
            ports.reconcile(case_id)
        return {"reply": reply, "status": "confirming", "handoff_fields": handoff}

    def silence(state: IntakeState) -> dict:
        case_id = state["case_id"]
        phase = store.phase(case_id)
        if phase.get("phase", "narrating") == "narrating" and store.narration_redacted(case_id) and not store.silence_prompted(case_id):
            store.mark_silence_prompted(case_id)
            return {"reply": SILENCE[_lang(ports, case_id)]}
        return {"reply": None}

    builder = StateGraph(IntakeState)
    for name, fn in (("screen", screen), ("capture", capture), ("check_done", check_done), ("extract", extract),
                     ("answer", answer), ("next_step", next_step), ("silence", silence)):
        builder.add_node(name, fn)
    builder.add_conditional_edges(START, route, {"screen": "screen", "extract": "extract", "silence": "silence"})
    builder.add_edge("screen", "capture")
    builder.add_conditional_edges("capture", after_capture, {"end": END, "answer": "answer", "check_done": "check_done"})
    builder.add_conditional_edges("check_done", after_check, {"extract": "extract", "end": END})
    builder.add_edge("extract", "next_step")
    builder.add_edge("answer", "next_step")
    builder.add_edge("next_step", END)
    builder.add_edge("silence", END)
    return builder.compile()
