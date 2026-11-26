"""Phrase rules for the deterministic layer of the output guard: English, Hindi (Devanagari) and Hinglish (Roman).

Every rule is a regular expression over normalised text (lower case, ASCII digits). Rules marked `negatable` are
skipped when a negation word sits just before or just after the match ("we do not accept", "main code share nahi
karti"). Rules that are commitments in themselves ("will not take legal action") are not negatable.
Devanagari words are matched as substrings because Python's `\\b` does not see Devanagari vowel signs as word
characters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    category: str
    name: str
    pattern: re.Pattern
    negatable: bool = True
    needs_offer: bool = False  # weak rule: only counts when the provider just made an offer
    before_only: bool = False  # English verbs of promising: a negation after the match belongs to the promise itself


def _r(category: str, name: str, pattern: str, negatable: bool = True, needs_offer: bool = False, before_only: bool = False) -> Rule:
    return Rule(category, name, re.compile(pattern, re.IGNORECASE), negatable, needs_offer, before_only)


_CRED = (
    r"(?:otp|one[\s-]?time|(?<!reference )(?<!ticket )(?<!tracking )(?<!confirmation )(?<!promo )(?<!order )(?<!coupon )code|"
    r"password|passcode|pin|cvv|cvc|card\s+(?:number|details|no)|ओटीपी|पासवर्ड|कोड|सीवीवी)"
)
_VERB = r"(?:read|share|give|send|tell|provide|pass|forward|relay|dictate|bata\w*|bhej\w*|de\s+(?:deti|deta|dungi|dunga|dete|dijiye)|dena|बता|दे|भेज)"
_ASK = r"(?:ask|tell|get|have|request|maang\w*|mangw\w*|puch\w*|पूछ|मांग)"
_PERSON = r"(?:customer|consumer|her|him|woh|asha|ग्राहक)"

RULES: tuple[Rule, ...] = (
    # --- accepting a settlement (strong: always blocked) ---
    _r("settlement_acceptance", "we_accept", r"\b(?:we|i)\s+(?:\w+\s+){0,2}?accept(?:ed)?\b"),
    _r("settlement_acceptance", "agree_to", r"\b(?:we|i)\s+(?:\w+\s+){0,1}?(?:agree|consent)(?:d)?\s+(?:to|with)\s+(?:the|that|your|this|these|those|it|any|all)\b"),
    _r("settlement_acceptance", "settled", r"\b(?:consider|treat)\s+(?:it|this|that)\s+(?:as\s+)?(?:settled|done|accepted|agreed)\b"),
    _r("settlement_acceptance", "deal", r"\b(?:it'?s\s+a\s+deal|we\s+have\s+a\s+deal|you\s+have\s+a\s+deal|deal\s+(?:done|pakki|final)|deal\s+hai)\b"),
    _r("settlement_acceptance", "take_it", r"\b(?:we|i)\s*(?:'ll|\s+will|\s+shall)\s+take\s+(?:it|that|this|the\s+(?:offer|voucher|deal|coupon|refund|amount))\b"),
    _r("settlement_acceptance", "full_and_final", r"\b(?:full\s+and\s+final|final\s+settlement)\b"),
    _r("settlement_acceptance", "hinglish_accept", r"\b(?:hum|ham|main|mai|mein)\s+(?:\w+\s+){0,3}?(?:accept|manzoor|manjoor|manjur|sweekar|swikar|sahmat|raazi|razi|agree)\b"),
    _r("settlement_acceptance", "manzoor_hai", r"\b(?:manzoor|manjoor|manjur)\s+hai\b"),
    _r("settlement_acceptance", "maan_lena", r"\bmaan\s+(?:lete|leti|leta|lenge|lungi|lunga|liya)\b"),
    _r("settlement_acceptance", "settlement_kar", r"\bsettlement\s+(?:kar\s+\w+|ho\s+gaya)\b"),
    _r("settlement_acceptance", "har_shart", r"\bhar\s+shart\s+(?:mante|manti|manta|maan)\b"),
    _r("settlement_acceptance", "sahmat", r"\bsahmat\b|\bsweekar\b|\bswikar\b"),
    _r("settlement_acceptance", "hi_accept", r"स्वीकार|मंज़ूर|मंजूर|सहमत|राज़ी|राजी|हर\s+शर्त\s+मान|मान\s+(?:लेते|लेती|लिया|लूँगा|लूंगा|लूँगी)|समझौता"),
    _r("settlement_acceptance", "happy_to_take", r"\b(?:we|i)(?:'re|\s+are|\s+am|'m)\s+(?:happy|glad|willing|ready)\s+to\s+(?:take|accept|settle|go\s+ahead|proceed)\b"),
    _r("settlement_acceptance", "go_ahead_with", r"\bgo\s+ahead\s+with\s+(?:the|that|this|your)\s+(?:voucher|offer|deal|refund|settlement|coupon|amount|credit)\b"),
    _r("settlement_acceptance", "close_matter", r"\b(?:you\s+(?:may|can|could)|please|go\s+ahead\s+and)\s+close\s+(?:the|this|that)\s+(?:matter|case|ticket|complaint)\b"),
    # --- accepting a settlement (weak: only after an offer) ---
    _r("settlement_acceptance", "bare_yes", r"^\W*(?:yes|yeah|yep|okay|ok|sure|fine|agreed|accepted|haan|han|ha|ji\s+haan|theek\s+hai|thik\s+hai|chalega|हाँ|हां|ठीक\s+है|जी\s+हाँ|जी\s+हां)\W*$", needs_offer=True),
    _r("settlement_acceptance", "that_works", r"\b(?:that|this|it)\s+(?:works|is\s+(?:fine|acceptable|okay|ok|agreed)|sounds\s+(?:good|fine|fair))\b", needs_offer=True),
    _r("settlement_acceptance", "i_agree", r"\b(?:we|i)\s+agree\b", needs_offer=True),
    _r("settlement_acceptance", "happy_with", r"\bi(?:'m|\s+am)\s+(?:happy|fine|okay|ok)\s+with\b", needs_offer=True),
    _r("settlement_acceptance", "fine_by_us", r"\b(?:fine|okay|ok|good|acceptable)\s+(?:by|for|with)\s+(?:us|me)\b", needs_offer=True),
    _r("settlement_acceptance", "chalega", r"\bchale(?:ga|gi)\b|\bkhush\s+(?:hain|hai|hoon)\b|(?:ticket|case|matter|complaint)\s+(?:band|close)\s+kar\b|चलेगी|चलेगा|ठीक\s+है|खुश", needs_offer=True),
    _r("settlement_acceptance", "bare_deal", r"\bdeal\b", needs_offer=True),
    _r("settlement_acceptance", "close_it", r"\bclose\s+(?:the|this|that)\s+(?:matter|case|ticket|complaint)\b", needs_offer=True),
    # --- proposing or countering an amount ---
    _r("settlement_counter", "fine_with_amount", r"\b(?:fine|happy|okay|ok|satisfied)\s+with\s+(?:rs\.?\s*|₹\s*)?\d"),
    _r("settlement_counter", "can_we_say", r"\bcan\s+we\s+(?:say|make\s+it|do|settle)\s+(?:rs\.?\s*|₹\s*)?\d"),
    _r("settlement_counter", "settle_for", r"\bsettl(?:e|ing)\s+(?:for|at|with|on)\b"),
    _r("settlement_counter", "how_about", r"\bhow\s+about\s+(?:rs\.?\s*|₹\s*|inr\s*)?\d"),
    _r("settlement_counter", "would_you_accept", r"\bwould\s+you\s+(?:accept|take|agree|consider)\b"),
    _r("settlement_counter", "what_if", r"\bwhat\s+if\s+(?:we|you|i)\s+(?:\w+\s+){0,3}\d"),
    _r("settlement_counter", "halfway", r"\bmeet\s+(?:us\s+)?(?:in\s+the\s+middle|halfway)\b"),
    _r("settlement_counter", "can_take", r"\b(?:we|i)\s*(?:'ll|\s+can|\s+could|\s+would|\s+will)\s+(?:also\s+)?(?:take|do|go\s+(?:down\s+)?(?:to|for)|accept)\s+(?:rs\.?\s*|₹\s*|inr\s*)?\d"),
    _r("settlement_counter", "settle_kar", r"\bsettle\s+kar\b|\b\d+\s+(?:mein|me)\s+settle\b"),
    # --- promises on the consumer's behalf ---
    _r("commitment", "promise", r"\b(?:i|we)\s+(?:hereby\s+)?(?:promise|guarantee|undertake|commit|assure|swear)\b", before_only=True),
    _r("commitment", "guarantee_hinglish", r"\bguarantee\s+(?:deti|deta|dete|karti|karta|karte)\b|\bvaada\s+(?:karti|karta|karte)\b"),
    _r("commitment", "withdraw", r"\bwithdraw(?:ing|n)?\s+(?:the\s+|our\s+|this\s+|her\s+|his\s+|my\s+)?(?:complaint|case|claim|dispute)\b"),
    _r("commitment", "waive", r"\bwaiv(?:e|ing|ed)\b"),
    _r("commitment", "give_up", r"\bgive\s+up\s+(?:any|the|all|our|her)\b|\bdrop\s+(?:the\s+)?(?:complaint|case|claim)\b"),
    _r("commitment", "no_action", r"\b(?:will|shall)\s+not\s+(?:take|file|pursue|go|escalate|approach)\b.{0,30}\b(?:action|court|case|complaint|police|consumer)\b", negatable=False),
    _r("commitment", "no_further", r"\bno\s+(?:further|more)\s+(?:claim|action|complaint)s?\b", negatable=False),
    _r("commitment", "shikayat_wapas", r"\b(?:shikayat|complaint|case)\s+(?:wapas|vapas)\s+le\b"),
    _r("commitment", "authorise", r"\b(?:i|we)\s+(?:authori[sz]e|confirm\s+on\s+behalf)\b|\bon\s+behalf\s+of\s+(?:the\s+)?(?:customer|consumer|her|him)\b.{0,50}\b(?:confirm|agree|accept|authori[sz]e|promise)\b"),
    _r("commitment", "will_not_escalate", r"\bwill\s+not\s+escalate\b|\b(?:give|gave)\s+you\s+(?:my|our)\s+word\b|\blikh\s+kar\s+de\b|\baage\s+koi\s+(?:shikayat|claim|action)\s+nahi\b", negatable=False),
    _r("commitment", "hi_commit", r"शिकायत\s+वापस|गारंटी|वादा\s+कर"),
    # --- claiming to be someone else ---
    _r("identity_claim", "i_am_customer", r"\b(?:i\s+am|i'm|this\s+is|my\s+name\s+is)\s+(?:the\s+|her\s+|his\s+)?(?:customer|consumer|account\s+holder)\b", negatable=False),
    _r("identity_claim", "i_am_lawyer", r"\bi\s+am\s+(?:her\s+|his\s+|the\s+|a\s+|an\s+)?(?:lawyer|advocate|attorney|solicitor|police|officer|inspector|ombudsman|judge)\b", negatable=False),
    _r("identity_claim", "behalf_of_authority", r"\bon\s+behalf\s+of\s+the\s+(?:court|police|government|ombudsman|commission)\b", negatable=False),
    _r("identity_claim", "main_customer", r"\bmain\s+(?:customer|consumer|grahak|vakil|advocate|lawyer)\s+hoon\b|\bmain\s+(?:customer|consumer|grahak|vakil|advocate|lawyer)\b(?:\s+\w+)?\s+hoon", negatable=False),
    _r("identity_claim", "represent_firm", r"\bi\s+(?:represent|work\s+for)\b[^.!?]{0,30}\b(?:law\s+firm|lawyers?|advocates?|court|police|bank|government)\b", negatable=False),
    _r("identity_claim", "hi_identity", r"मैं\s+(?:ग्राहक|वकील)", negatable=False),
    # --- legal threats ---
    _r("legal_threat", "sue", r"\b(?:sue|sued|suing)\b|\btake\s+(?:you|this|the\s+matter|it)\s+to\s+court\b|\blegal\s+(?:action|notice|proceedings)\b|\bfile\s+a\s+(?:lawsuit|suit)\b"),
    # --- credentials and codes ---
    _r("otp_or_card", "cred_after_verb", rf"\b{_VERB}\b[^.!?]{{0,40}}?\b{_CRED}\b"),
    _r("otp_or_card", "cred_before_verb", rf"\b{_CRED}\b[^.!?]{{0,40}}?\b{_VERB}\b"),
    _r("otp_or_card", "ask_person_for_cred", rf"\b{_ASK}\b[^.!?]{{0,40}}?{_PERSON}[^.!?]{{0,40}}?\b{_CRED}\b"),
    _r("otp_or_card", "cred_then_person_ask", rf"\b{_CRED}\b[^.!?]{{0,40}}?{_PERSON}[^.!?]{{0,30}}?\b{_ASK}"),
    _r("otp_or_card", "person_se_cred", rf"{_PERSON}\s+se\s+{_CRED}\b"),
    _r("otp_or_card", "hi_cred", r"(?:ओटीपी|पासवर्ड|कोड|सीवीवी)[^.!?।]{0,30}(?:बता|दे|भेज)"),
)

NEGATORS = {
    "not", "no", "never", "cannot", "can't", "cant", "won't", "wont", "don't", "dont", "unable", "refuse", "refused",
    "without", "nahi", "nahin", "nhi", "mat", "na", "नहीं", "न", "ना", "कभी", "isn't", "aren't", "shouldn't", "mustn't",
}
_TOKEN = re.compile(r"[^\s.,;:!?()\[\]\"।]+")


def negated(text: str, start: int, end: int, before: int = 6, after: int = 4) -> bool:
    """True if a negation word is within `before` tokens ahead of the match, inside it, or `after` tokens behind it."""
    pre = [t.casefold().replace("’", "'") for t in _TOKEN.findall(text[:start])][-before:]
    inside = [t.casefold().replace("’", "'") for t in _TOKEN.findall(text[start:end])]
    post = [t.casefold().replace("’", "'") for t in _TOKEN.findall(text[end:])][:after] if after else []
    return any(t in NEGATORS for t in pre + inside + post)


OFFER_MARKERS = re.compile(
    r"voucher|coupon|settle|final|offer|deal|partial|half|discount|instead|credit\s+note|accept|agree|manzoor|"
    r"वाउचर|सहमत|स्वीकार|पेशकश|समझौता|कूपन|ऑफर",
    re.IGNORECASE,
)

CRED_CUES_STRONG = ("otp", "one time", "one-time", "cvv", "cvc", "password", "passcode", "ओटीपी", "पासवर्ड", "सीवीवी")
CRED_CUES_WEAK = ("code", "pin", "verification", "कोड", "पिन")
REFERENCE_CUES = ("ref", "ticket", "tracking", "confirmation", "order", "awb", "docket", "complaint")
AMOUNT = re.compile(
    r"(?:₹|rs\.?|inr|rupees?|रुपये|रुपए|रु\.?)\s*(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(?:rupees?|rupaye|rupay|rupiye|rs\b|रुपये|रुपए|₹)",
    re.IGNORECASE,
)
ORDER_ID = re.compile(r"\border\s*(?:id|number|no\.?|#)?\s*(?:is|was)?\s*[:#]?\s*([a-z0-9][a-z0-9\-]{5,})", re.IGNORECASE)
CITATION_CUES = re.compile(r"\b(?:section|sec\.|act|rule|rules|clause|regulation|policy|article)\b", re.IGNORECASE)
