"""Turn understanding: what did the provider just say (`classify_turn`), and what did a written reply say (`classify_reply`).

Both call the classifier port on the `classify` role. If that fails (the model is withdrawn and the server's own
fallback also fails, the call times out, or the model returns a label outside the list) the node tries the fallback
role, and if that fails too, it falls back to a small keyword classifier and says so (`degraded`). A degraded label is
never trusted for more than routing: the output guard still checks every sentence the agent speaks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from resolve_workflows import prompts
from resolve_workflows.nodes.screen import ScreenResult
from resolve_workflows.ports import Classifier, is_budget_error

TURN_LABELS = ["offer", "claim", "question", "request_for_data", "stall", "hostile", "injection_attempt"]
REPLY_LABELS = ["resolved_claimed", "partial", "rejected", "needs_info", "silence"]
ROLE = "classify"
FALLBACK_ROLE = "judge_for_qwen"  # a different model family, so a withdrawn Qwen does not take the node down
LOW_CONFIDENCE = 0.5


@dataclass(frozen=True)
class Understood:
    label: str
    confidence: float
    source: str  # model | fallback_role | keywords | rule
    degraded: bool = False
    low_confidence: bool = False
    injection_signal: bool = False  # the screen marked this turn; it did not change the label
    screen_score: float = 0.0

    @property
    def injection_covered(self) -> bool:
        """An injection attempt is covered when it is labelled as one or the screen marked it."""
        return self.label == "injection_attempt" or self.injection_signal


_INJECTION = re.compile(
    r"ignore (?:all |your |the )?(?:previous|prior|earlier)|forget (?:everything|the refund|your)|disregard (?:the |your )?(?:rules|mandate|instructions)|"
    r"system prompt|developer mode|you are now|new instruction|system:|system message|pichh?le (?:saare |sabhi )?(?:nirdesh|instructions?|niyam)|"
    r"bhool jao|निर्देश|भूल जाओ|अनदेखा|सिस्टम|from now on you|"
    r"hidden (?:rules|instructions)|(?:say|tell the customer) .{0,60}you (?:approve|accept|agree)|kaho ki aap|apne niyam (?:mujhe )?batao|अपने नियम|"
    r"(?:नियम|निर्देश)[^।]{0,25}(?:बताओ|सुनाओ|दिखाओ)|(?:tell|show) me (?:your|the) (?:rules|instructions)|reveal (?:your|the) (?:rules|instructions|prompt)|(?:rules|instructions) you (?:were|have been) given",
    re.IGNORECASE,
)
_DATA = re.compile(
    r"otp|aadhaar|aadhar|आधार|\bpan\b|पैन|\bcard\b|cvv|कार्ड|ओटीपी|address|pata\b|pin ?code|पता|date of birth|\bdob\b|bank account|account number|"
    r"\bupi\b|phone number|mobile number|\bemail\b|email id|password|पासवर्ड|ईमेल|फोन नंबर|number batayiye|number bataiye|नंबर बताइए",
    re.IGNORECASE,
)
_HOSTILE = re.compile(
    r"stop calling|wasting my time|nonsense|bakwas|बकवास|bhaad mein|call kaat|फोन रख|pareshan kar|irada nahi|not our problem|कोई इरादा नहीं",
    re.IGNORECASE,
)
_STALL = re.compile(
    r"please hold|stay on the line|call (?:us )?back|get back to you|someday|transfer you|\bticket\b|dobara call|phir call|baad mein|jaldi hi|"
    r"system down|system slow|supervisor|कुछ दिन|दोबारा|बाद में|होल्ड|kal phir|line par rahiye",
    re.IGNORECASE,
)
_OFFER = re.compile(
    r"voucher|credit|replace|refund of|we can offer|discount|de sakte|badal denge|वाउचर|दे सकते|will refund|badal|replacement",
    re.IGNORECASE,
)


def _keyword_turn_label(text: str) -> str:
    if _INJECTION.search(text):
        return "injection_attempt"
    if _DATA.search(text):
        return "request_for_data"
    if _HOSTILE.search(text):
        return "hostile"
    if _STALL.search(text):
        return "stall"
    if _OFFER.search(text):
        return "offer"
    if "?" in text or re.search(r"(?i)\b(?:kya|kis|kitne|kab|which|when|what|can you tell|could you)\b|क्या|कौन|कब|कितने", text):
        return "question"
    return "claim"


keyword_turn_label = _keyword_turn_label  # the outreach graph cross-checks the model with it on the dangerous labels

_REPLY_RULES = (
    ("needs_info", re.compile(r"(?i)please (?:share|send|provide)|we need|kripya|bhejiye|भेजिए|screenshot|proof|photo")),
    ("rejected", re.compile(r"(?i)unable to|declined|not eligible|no refund|cannot be|can't be|स्वीकार नहीं|nahi kar sakte|outside the")),
    ("partial", re.compile(r"(?i)\bvoucher\b|instead of|half|aadha|rest after|only part|partial|sirf")),
    ("resolved_claimed", re.compile(r"(?i)resolved|processed|credited|has been (?:sent|refunded)|भेज दिया|बंद|closed")),
)


def _keyword_reply_label(text: str) -> str:
    for label, pattern in _REPLY_RULES:
        if pattern.search(text):
            return label
    return "needs_info"


keyword_reply_label = _keyword_reply_label  # the follow-up graph uses it when the reply may not be sent to a model


def _classify(classifier: Classifier, text: str, prompt_name: str, labels: list[str], roles: tuple[str, ...], stop_on_budget: bool = False):
    prompt = prompts.load(prompt_name)
    for index, role in enumerate(roles):
        try:
            label, confidence, _usage = classifier.classify(role, prompt.text, text, labels)
        except Exception as exc:
            if stop_on_budget and is_budget_error(exc):
                raise  # the spending cap is used up: the call stops cleanly instead of limping on with keywords
            continue
        if label in labels:
            return label, float(confidence), "model" if index == 0 else "fallback_role"
    return None


def classify_turn(classifier: Classifier, text: str, screen: ScreenResult | None = None, roles: tuple[str, ...] = (ROLE, FALLBACK_ROLE)) -> Understood:
    """Label one provider utterance. The screen result only marks the turn."""
    marked = bool(screen and screen.marked)
    score = screen.score if screen else 0.0
    if not text.strip():
        return Understood("stall", 1.0, "rule", injection_signal=marked, screen_score=score)  # nothing was said
    got = _classify(classifier, text, "classify_turn", TURN_LABELS, roles, stop_on_budget=True)
    if got is None:
        return Understood(_keyword_turn_label(text), 0.0, "keywords", degraded=True, low_confidence=True, injection_signal=marked, screen_score=score)
    label, confidence, source = got
    return Understood(label, confidence, source, low_confidence=confidence < LOW_CONFIDENCE, injection_signal=marked, screen_score=score)


def classify_reply(classifier: Classifier, text: str, roles: tuple[str, ...] = (ROLE, FALLBACK_ROLE)) -> Understood:
    """Label a written reply from the provider. An empty reply is silence and needs no model."""
    if not text.strip():
        return Understood("silence", 1.0, "rule")
    got = _classify(classifier, text, "classify_reply", REPLY_LABELS, roles)
    if got is None:
        return Understood(_keyword_reply_label(text), 0.0, "keywords", degraded=True, low_confidence=True)
    label, confidence, source = got
    return Understood(label, confidence, source, low_confidence=confidence < LOW_CONFIDENCE)
