"""Scripted stand-ins for every outside vendor, so the whole product can be used and tested with no keys and no network.

Switch: set RESOLVE_FAKE_VENDORS=1. It is honoured only when APP_ENV is `dev` or `test`; in any other environment
the variable is ignored and a warning is logged. `install_fake_vendors(app)` puts the stand-ins on the same hooks the
tests already use (`intake_llm`, `evidence_ocr`, `evidence_vision`, `retriever`, `voice_stt`, `voice_tts_factory`),
so no route or service knows whether it is talking to a vendor.

What is scripted (everything below is deterministic; nothing is random and nothing leaves the machine)

* Language model (`ScriptedModel`, used for intake, evidence, reconciliation, the outreach draft and the guard):
  - fact extraction: regular expressions over the (already redacted) narration. It finds the company (a known list,
    or a capitalised name before "se"/"from"/"at"), the amount (Rs, rupees, rupaye, a rupee sign or "रुपये"), the order
    number (a redaction token such as [NUM_1] near the word "order", or a written id like OD43817265), the order date
    (12 November 2026, 12/11/2026, 2026-11-12, "yesterday"/"kal"), the remedy (refund, replacement), the product, the
    payment mode and a one-line issue summary. It never fills `provider_entity_type`, so the follow-up question about
    where the person bought is always asked.
  - "is the person done?": done only for short phrases such as "that's all", "bas itna hi", "ho gaya".
  - "what kind of company?": keywords (seller, own site, UPI or wallet, app or platform).
  - provider turns: the keyword labels of the workflows package (offer, claim, question, request_for_data, stall,
    hostile, injection_attempt); injection screen: high score on "ignore previous instructions" style text only.
  - reply drafting: the graph's own suggested wording, unchanged (so every sentence still goes through the real output
    guard and the real checks in code); call summary: a fixed sentence with the outcome.
  - output guard policy check: never reports a violation, so only the deterministic layer of the guard acts.
  - grounded answers: the first sentence of the first retrieved chunk, cited.
* Evidence OCR (`ScriptedOCR`): a fixed Zeta Mart receipt (order OD43817265, 12 November 2026, Rs 4999). A text file
  upload is read as its own text instead, so a test can upload any document it likes. Vision (`ScriptedVision`)
  returns the same fixed receipt.
* Retriever: the three fixed chunks of `resolve_workflows.fakes.FakeRetriever` (two consumer-law rules, one Zeta Mart
  policy, all marked as test fixtures).
* Voice: `ScriptedSTT` answers utterances in order (the fixed story, then the usual follow-up answers) and then returns
  nothing; speech synthesis is `FakeTTS`, which yields fixed silent chunks.

The fixed story used by the tests is `STORY`; variants are in `STORY_VARIANTS`.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import date, timedelta

from app.config import SERVER_ROOT

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.fakes import FakeRetriever  # noqa: E402
from resolve_workflows.sim.models import ScriptedClassifier, ScriptedDraftLLM, ScriptedScreen  # noqa: E402

log = logging.getLogger("resolve")

ENV_SWITCH = "RESOLVE_FAKE_VENDORS"
ALLOWED_ENVS = {"dev", "test"}

# The story the end-to-end test tells. It leaves out the order date on purpose, so one follow-up question is needed.
STORY = (
    "Maine Zeta Mart se ek phone 4999 rupaye mein order kiya tha, order id OD43817265. Paise UPI se diye the. "
    "Phone wapas kar diya par refund nahi aaya. Mujhe poora refund chahiye."
)
STORY_VARIANTS = (
    STORY,
    "I ordered a phone from Amazon for Rs 12,999 on 3 November 2026, order number AB12345678. The refund never came and I want a replacement.",
    "Flipkart se shoes mangaye the ₹2,499 ke, 12/11/2026 ko. Wapas kiye lekin paise wapas nahi aaye. Refund chahiye.",
    "Myntra se kal 1500 rupees ka kurta order kiya, UPI se pay kiya. Return kiya par refund nahi mila, paise wapas chahiye.",
)
RECEIPT = "\n".join(["Zeta Mart", "Order Confirmation", "Order ID: OD43817265", "Order date: 12 Nov 2026", "Order total: Rs. 4,999.00"])

KNOWN_COMPANIES = (
    "Zeta Mart", "Flipkart", "Amazon", "Myntra", "Meesho", "Nykaa", "Ajio", "Swiggy", "Zomato", "BigBasket", "Snapdeal", "Croma",
    "Tata Cliq", "Paytm", "PhonePe",
)
_LEADING_WORDS = {"maine", "main", "mene", "mera", "meri", "i", "my", "the", "ek", "from", "at"}
_COMPANY = re.compile(r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*)\s+(?:se|from|at|ne|ka|ki)\b")
_AMOUNT = (
    re.compile(r"(?i)(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]+)?)"),
    re.compile(r"(?i)([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:rupaye|rupees?|rupay|rs\b|₹|रुपये|रुपए)"),
)
_ID_TOKEN = re.compile(r"(?i)order[^.\[\n]{0,25}?(\[NUM_\d+\])")
_ID_WRITTEN = re.compile(r"\b([A-Z]{2}[0-9]{6,})\b")
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_DAY_MONTH = re.compile(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})(?:\s+(\d{4}))?\b")
_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_PRODUCTS = ("phone", "mobile", "laptop", "shoes", "kurta", "headphones", "watch", "tv", "shirt", "bag", "charger")
_DONE = re.compile(r"(?i)^\W*(?:that'?s all|that is all|that'?s it|nothing (?:more|else)|no that'?s it|bas(?: itna)?(?: hi)?|ho gaya|please go ahead|go ahead|aage badhiye)\W*$")


def _empty() -> dict:
    return {"value": "", "certainty": "not_stated", "original_phrase": "", "ambiguity_note": ""}


def _found(value: str, phrase: str = "") -> dict:
    return {"value": value, "certainty": "stated", "original_phrase": phrase or value, "ambiguity_note": ""}


def _date(text: str, today: date) -> tuple[str, str]:
    match = _ISO.search(text)
    if match:
        return match.group(0), match.group(0)
    match = _DMY.search(text)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return date(year, month, day).isoformat(), match.group(0)
        except ValueError:
            return "", ""
    for match in _DAY_MONTH.finditer(text):
        month = _MONTHS.get(match.group(2).lower()[:3])
        if not month:
            continue
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            return date(year, month, int(match.group(1))).isoformat(), match.group(0)
        except ValueError:
            return "", ""
    low = text.lower()
    if re.search(r"\b(?:yesterday|kal)\b", low):
        return (today - timedelta(days=1)).isoformat(), "yesterday"
    return "", ""


def _company(text: str) -> str:
    for name in KNOWN_COMPANIES:
        if re.search(rf"(?i)\b{re.escape(name)}\b", text):
            return name
    match = _COMPANY.search(text)
    if match:
        words = [w for w in match.group(1).split() if w.lower() not in _LEADING_WORDS]
        return " ".join(words)
    return ""


def extract_scripted(text: str, narration_date: str) -> dict:
    """The scripted fact extraction. Returns the strict extraction shape with every field present."""
    try:
        today = date.fromisoformat(narration_date)
    except ValueError:
        today = date(2026, 11, 27)
    out = {
        name: _empty()
        for name in (
            "company_name", "product", "order_id", "order_date", "amount", "currency", "payment_mode", "issue_summary",
            "company_said", "promised_date", "refund_reference", "desired_remedy", "provider_entity_type",
        )
    }
    low = text.lower()
    company = _company(text)
    if company:
        out["company_name"] = _found(company)
    for pattern in _AMOUNT:
        match = pattern.search(text)
        if match:
            out["amount"] = _found(match.group(1).replace(",", ""), match.group(0))
            out["currency"] = _found("INR")
            break
    else:
        # An answer to "how much did you pay?" is often only the number.
        if "question about amount" in low:
            bare = re.search(r"\b([0-9][0-9,]*(?:\.[0-9]+)?)\b", text.split(")", 1)[-1])
            if bare:
                out["amount"] = _found(bare.group(1).replace(",", ""))
                out["currency"] = _found("INR")
    token = _ID_TOKEN.search(text) or re.search(r"(\[NUM_\d+\])", text) if "order" in low else None
    if token:
        out["order_id"] = _found(token.group(1))
    else:
        written = _ID_WRITTEN.search(text)
        if written:
            out["order_id"] = _found(written.group(1))
    # A date only counts when it is not part of the order id or the amount; the patterns above are anchored so they do not overlap.
    iso, phrase = _date(_ID_WRITTEN.sub(" ", text), today)
    if iso:
        out["order_date"] = _found(iso, phrase)
    if re.search(r"(?i)replacement|badal|exchange", text):
        out["desired_remedy"] = _found("replacement")  # a stated wish for a replacement wins over the word "refund" in the complaint
    elif re.search(r"(?i)refund|paise wapas|money back|पैसे वापस", text):
        full = re.search(r"(?i)poora|pura|full|whole|पूरा", text)
        out["desired_remedy"] = _found("full refund" if full else "refund")
    for product in _PRODUCTS:
        if re.search(rf"(?i)\b{product}\b", text):
            out["product"] = _found(product)
            break
    for mode, pattern in (("upi", r"(?i)\bupi\b"), ("card", r"(?i)\bcard\b"), ("cash on delivery", r"(?i)\bcod\b|cash on delivery")):
        if re.search(pattern, text):
            out["payment_mode"] = _found(mode)
            break
    if re.search(r"(?i)refund (?:nahi|never|not)|paise wapas nahi|nahi aaya|nahi mila|not received|never came", text):
        out["issue_summary"] = _found("Refund not received after the order was returned or cancelled")
    return out


def _provider_type(text: str) -> str:
    low = text.lower()
    if re.search(r"seller|vendor|third.?party", low):
        return "seller_on_marketplace"
    if re.search(r"own (?:site|website|shop|app)|their (?:site|website)|direct|company'?s (?:site|website)", low):
        return "direct_seller"
    if re.search(r"upi|paytm|phonepe|gpay|wallet|bank|card", low):
        return "payment_intermediary"
    if re.search(r"app|platform|marketplace|site|website|zeta|amazon|flipkart|myntra|meesho", low):
        return "marketplace"
    return "unknown"


class ScriptedModel:
    """One object for the llm, classifier and screen ports."""

    def __init__(self) -> None:
        self.draft = ScriptedDraftLLM(0)
        self.turns = ScriptedClassifier()
        self.screen = ScriptedScreen()

    def structured(self, role: str, prompt_id: str, variables: dict, schema: dict, mode: str = "instruct") -> tuple[dict, dict]:
        props = schema.get("properties", {})
        if "company_name" in props and "order_id" in props:
            return extract_scripted(str(variables.get("text", "")), str(variables.get("narration_date", ""))), {}
        return self.draft.structured(role, prompt_id, variables, schema, mode)

    def text(self, role: str, prompt_id: str, variables: dict, mode: str = "instruct") -> tuple[str, dict]:
        return self.draft.text(role, prompt_id, variables, mode)

    def classify(self, role: str, prompt_id: str, text: str, labels: list[str]) -> tuple[str, float, dict]:
        if "done" in labels:
            return ("done" if _DONE.match(text) else "more"), 0.95, {}
        if "marketplace" in labels:
            return _provider_type(text), 0.9, {}
        if "resolved_claimed" in labels:
            from resolve_workflows.nodes import classify_turn as module

            return getattr(module, "_keyword_reply_label", lambda _t: "needs_info")(text), 0.9, {}
        return self.turns.classify(role, prompt_id, text, labels)

    def score(self, text: str) -> float:
        return self.screen.score(text)


class ScriptedOCR:
    """Reads a text upload as its own text; any other bytes give the fixed receipt."""

    def read(self, image: bytes) -> list[str]:
        try:
            text = image.decode("utf-8")
        except UnicodeDecodeError:
            return [RECEIPT]
        return [text] if text.strip() and "\x00" not in text else [RECEIPT]


class ScriptedVision:
    def read_text(self, image: bytes) -> str:
        return RECEIPT


class ScriptedSTT:
    """Answers utterances in order: the story, then the answers the follow-up questions usually need."""

    LINES = (STORY, "12 November 2026", "Zeta Mart app se", "poora refund chahiye")

    def __init__(self) -> None:
        self.index = 0

    def transcribe(self, role: str, audio: bytes, filename: str = "clip.wav") -> dict:
        text = self.LINES[self.index] if self.index < len(self.LINES) else ""
        self.index += 1
        return {"text": text, "dropped_segments": 0, "duration_seconds": 1}


def fake_vendors_enabled(settings) -> bool:
    if os.environ.get(ENV_SWITCH, "") != "1":
        return False
    if settings.app_env not in ALLOWED_ENVS:
        log.warning("%s is ignored because APP_ENV is %s", ENV_SWITCH, settings.app_env)
        return False
    return True


def install_fake_vendors(app) -> None:
    from app.voice.tts import FakeTTS

    state = app.state
    state.intake_llm = ScriptedModel()
    state.evidence_ocr = ScriptedOCR()
    state.evidence_vision = ScriptedVision()
    state.retriever = FakeRetriever()
    state.voice_stt = ScriptedSTT()
    state.voice_tts_factory = FakeTTS
    log.warning("fake vendors are on: no model, speech or OCR vendor will be called")
