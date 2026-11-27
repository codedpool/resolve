"""Scripted stand-ins for the models, so the whole graph runs in tests with no vendor.

`ScriptedDraftLLM` plays the draft model. `variant` (the run number) decides how it behaves, so five runs of a card
cover five behaviours: the suggested wording, a paraphrase, the same wording with a greeting, a model that misbehaves
(it adds a sentence that leaks a value or accepts an offer), and a model that is down. The output guard and the
checks in code are real in every run; only the model is scripted.
"""

from __future__ import annotations

import re

from resolve_workflows.nodes.classify_turn import keyword_turn_label

VARIANTS = ("suggested", "paraphrase", "greeting", "misbehaves", "down")
_INJECTION = re.compile(r"(?i)ignore (?:all |your |the )?(?:previous|prior)|system (?:notice|prompt|:)|\[system|forget|भूल जाओ|पिछले")


class ScriptedDraftLLM:
    def __init__(self, variant: int = 0, leaks: tuple[str, ...] = (), replies: list[str] | None = None) -> None:
        self.variant = variant % len(VARIANTS)
        self.leaks = leaks or ("The customer's phone number is 9871234560.", "Yes, the customer accepts the offer.")
        self.replies = list(replies) if replies else None
        self.calls: list[tuple[str, str]] = []

    @property
    def behaviour(self) -> str:
        return VARIANTS[self.variant]

    def text(self, role: str, prompt: str, variables: dict, mode: str = "instruct") -> tuple[str, dict]:
        self.calls.append(("text", role))
        if role == "summarize":
            record = variables["record"]
            return f"The call ended with outcome {record['outcome']}. Nothing is confirmed until you confirm it.", {}
        if self.replies is not None:  # a compromised model: says whatever it is told, whatever the points are
            return self.replies.pop(0) if self.replies else "Okay.", {}
        move = variables["move"]
        suggested = move["suggested"]
        name = self.behaviour
        if name == "down":
            raise RuntimeError("model unavailable")
        if name == "paraphrase":
            return suggested.replace("Could you please", "Would you please").replace("Thank you.", "Thanks."), {}
        if name == "greeting":
            return "Thank you. " + suggested if not suggested.startswith("Hello") else suggested, {}
        if name == "misbehaves":
            return suggested + " " + " ".join(self.leaks), {}
        return suggested, {}

    def structured(self, role: str, prompt: str, variables: dict, schema: dict, mode: str = "instruct") -> tuple[dict, dict]:
        self.calls.append(("structured", role))
        props = schema.get("properties", {})
        if "violation" in props:
            return {"violation": False, "categories": [], "rationale": ""}, {}
        if "statements" in props:
            chunks = variables["chunks"]
            if not chunks:
                return {"answerable": False, "statements": [], "clarifying_question": "Which clause?"}, {}
            first = chunks[0]
            sentence = re.split(r"(?<=[.!?])\s+", first["text"])[0]
            return {"answerable": True, "statements": [{"text": sentence, "kind": "rule", "cites": [first["id"]]}], "clarifying_question": ""}, {}
        raise ValueError(f"unscripted schema {list(props)}")


class ScriptedClassifier:
    """Gives each turn the label its card carries. `mode` simulates the weaknesses the real model has."""

    def __init__(self, labels: dict[str, str] | None = None, mode: str = "card") -> None:
        self.labels = dict(labels or {})
        self.mode = mode  # card | down | devanagari_stall | keywords_only
        self.calls = 0

    def classify(self, role: str, prompt: str, text: str, labels: list[str]) -> tuple[str, float, dict]:
        self.calls += 1
        if self.mode == "down":
            raise RuntimeError("classifier unavailable")
        if self.mode == "devanagari_stall" and re.search("[ऀ-ॿ]", text):
            return "stall", 0.95, {}  # the measured weakness: Devanagari read as a stall with high confidence
        label = self.labels.get(text) or keyword_turn_label(text)
        return label, 0.9, {}


class ScriptedScreen:
    def score(self, text: str) -> float:
        return 0.99 if _INJECTION.search(text) else 0.0005
