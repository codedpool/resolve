"""Small deterministic readers for one provider turn: which details it asks for, what kind of claim it makes, what it
offers, whether it gives a date or a number to call. The outreach graph decides with these, not with a model, wherever
the decision touches the mandate or the case data. English, Hindi (Devanagari) and Hinglish are all covered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from resolve_workflows.nodes.evidence_check import amounts_in, dates_in, references_in, spoken_to_digits, to_ascii_digits

# -- what the provider asks for -------------------------------------------------------------------------------------

SENSITIVE = (
    "otp", "card_number", "cvv", "password", "aadhaar", "pan", "bank_account", "upi_id", "date_of_birth", "phone", "email",
    "address", "pincode",
)
# Never said on a call, even if a mandate lists them: codes, passwords, card data and identity numbers.
NEVER_SHARE = frozenset({"otp", "card_number", "cvv", "password", "aadhaar", "pan"})
DISCLOSABLE_FIELDS = ("order_id", "amount", "order_date", "issue_summary", "consumer_name")

_FIELD_PATTERNS: dict[str, re.Pattern] = {
    "otp": re.compile(r"(?i)\botp\b|one[\s-]?time|ओटीपी|verification code|security code|(?<!pin )(?<!postal )(?<!zip )(?<!area )\bcode\b|(?<!पिन )कोड"),
    "cvv": re.compile(r"(?i)\bcvv\b|\bcvc\b|security code|सीवीवी"),
    "card_number": re.compile(r"(?i)\bcard\b|कार्ड|\bexpiry\b|debit|credit card|aakhri (?:char|chaar|4)|last (?:four|4) digits"),
    "password": re.compile(r"(?i)password|passcode|पासवर्ड|login|\bpin\b(?!\s?code)"),
    "aadhaar": re.compile(r"(?i)aadhaar|aadhar|आधार"),
    "pan": re.compile(r"(?i)\bpan\b|पैन|tax id"),
    "bank_account": re.compile(r"(?i)bank account|account number|a/c|\bifsc\b|खाता|खाते का नंबर"),
    "upi_id": re.compile(r"(?i)\bupi\b|\bvpa\b|यूपीआई"),
    "date_of_birth": re.compile(r"(?i)date of birth|\bdob\b|birth ?date|birthday|जन्म"),
    "phone": re.compile(r"(?i)phone|mobile|contact number|whatsapp|फोन|मोबाइल|registered number|number on the account|cell number"),
    "email": re.compile(r"(?i)e-?mail|ईमेल"),
    "address": re.compile(r"(?i)address|\bpata\b|पता|delivery location|house number|flat number|street"),
    "pincode": re.compile(r"(?i)pin ?code|postal code|zip|पिन कोड|पिनकोड"),
    "order_id": re.compile(r"(?i)order (?:number|id|no\b)|ऑर्डर (?:नंबर|आईडी)|order ka number|order no"),
    "amount": re.compile(r"(?i)how much|\bamount\b|kitne (?:rupaye|paise)|कितने|refund amount|price"),
    "order_date": re.compile(r"(?i)(?:order|purchase|booking) date|date of (?:the )?order|when (?:did you|was|were).{0,25}order|kab.{0,20}order|ऑर्डर.{0,15}तारीख"),
    "issue_summary": re.compile(r"(?i)complaint|\bissue\b|problem|what happened|what is this about|kya hua|shikayat|शिकायत|reason for (?:the |your )?call|kis (?:baare|bare) mein|क्या हुआ"),
    "consumer_name": re.compile(r"(?i)(?:customer|consumer|account holder|caller)'?s? name|your name|who (?:are you|is the customer)|aapka naam|naam kya|नाम"),
}


_ASKS = re.compile(
    r"(?i)\?|give|share|tell|send|provide|need|read|bata|batao|dijiye|bhej|chahiye|confirm|what is|what's|which|kya|kaun|kab|"
    r"बता|दीजिए|दीजिये|चाहिए|भेज|क्या|कौन|कब|बोल|कहो|पूछ|enter|verify|dictate|spell"
)


def asks_for_something(text: str) -> bool:
    """True when the turn is shaped like a request (a question mark or a request verb), so a detail named in a
    plain statement is not taken for a request."""
    return bool(_ASKS.search(text))


def requested_fields(text: str) -> list[str]:
    """The detail names a provider turn asks for, sensitive ones first. `cvv` and `card_number` are both reported for
    card questions so that either listing blocks the sentence."""
    text = text if text else ""
    found = [name for name, pattern in _FIELD_PATTERNS.items() if pattern.search(text)]
    if "card_number" in found and "cvv" in found and not re.search(r"(?i)cvv|cvc|security code", text):
        found.remove("cvv")
    if "pincode" in found and "address" in found and not re.search(r"(?i)pin ?code|postal|zip|पिन", text):
        found.remove("pincode")
    return sorted(found, key=lambda f: (f not in SENSITIVE, SENSITIVE.index(f) if f in SENSITIVE else 99))


# -- claims ----------------------------------------------------------------------------------------------------------

PAID = re.compile(
    r"(?i)\b(?:we|i)\s+(?:have\s+|had\s+|already\s+)?(?:refunded|paid|sent|processed|credited|released|transferred|reversed)\b"
    r"|(?:was|were|has been|have been|had been|is|been|got)\s+(?:already\s+|successfully\s+)?(?:processed|credited|refunded|paid|sent|released|transferred|reversed|initiated|settled)"
    r"|already\s+(?:processed|refunded|paid|credited|sent)|processed\s+(?:on|already|it)|refund\s+(?:is\s+|has been\s+)?(?:done|complete|completed|processed)"
    r"|records show|our records|ho chuka|ho gaya|kar diya|bhej diya|bhej di\b|process ho|jama kar|जमा कर दिया|भेज दिया|हो चुका|हो गया|प्रोसेस"
)
_NO_REQUEST = re.compile(
    r"(?i)no (?:refund )?request (?:was |has been )?(?:received|raised|logged|made)|(?:never|did not|didn't|haven't|have not) received (?:any|a|your) (?:refund )?request"
    r"|request (?:hi )?(?:receive )?nahi|koi request (?:hi )?(?:receive )?nahi|request nahi (?:mili|aaya|aayi)|कोई रिक्वेस्ट"
)
_DELIVERED = re.compile(
    r"(?i)(?:was|been|already|got|has been)\s+delivered|deliver ho gaya|deliver ho chuka|(?:was|is|been) (?:never |not )cancel(?:l)?ed|cancel (?:hi )?nahi hua|cancel nahi hua|not cancelled"
    r"|डिलीवर हो गया|कैंसिल नहीं"
)
POLICY = re.compile(
    r"(?i)polic(?:y|ies)|terms|t&c|clause|\brules?\b|regulation|\bact\b|section|only (?:given|within|if|for)|not (?:applicable|valid|covered)|lagu nahi|"
    r"within (?:\w+ ){0,2}(?:day|hour)s?|(?:one|two|three|seven|\d+)[\s-](?:day|hour)s?\b|नीति|नियम|शर्त|पॉलिसी|लागू नहीं"
)
REFUSAL = re.compile(
    r"(?i)cannot do more|can't do more|no refund|not possible|not eligible|unable to|won't be able|will not (?:refund|give)|not our problem|"
    r"nahi ho sakta|nahi kar sakte|nahi milega|refund nahi|नहीं हो सकता|नहीं मिलेगा|नहीं कर सकते"
)
_OFFER_CUE = re.compile(
    r"(?i)can (?:do|offer|give|pay)|will pay|we pay|offer|most i can|settle|final|we will give|can only|only (?:if|\w+ (?:thousand|hundred|rupees))|de sakte|de denge|dete hain|दे सकते|"
    r"voucher|coupon|credit note|store credit|replace|replacement|discount|badal|वाउचर"
)
_VOUCHER = re.compile(r"(?i)voucher|coupon|credit note|store credit|gift card|वाउचर|कूपन")
_REPLACEMENT = re.compile(r"(?i)replace|replacement|exchange|badal|बदल")
_DISCOUNT = re.compile(r"(?i)discount|cashback|छूट")
_WAIVER = re.compile(
    r"(?i)full and final|final settlement|withdraw|waive|give up|drop the complaint|no further claim|close the complaint|further claims?|"
    r"complaint (?:wapas|back)|शिकायत वापस"
)
_PROMISE_CUE = re.compile(
    r"(?i)\bwill\b|\bshall\b|going to|\bby\b|before|release|reach|credited by|tak\b|तक|ho jayega|ho jaega|milega|bhej denge|de denge|kar denge|credit ho|by the"
)
_PAST_MARKER = re.compile(r"(?i)\b(?:was|were|has been|have been|already|processed on|credited on|paid on|sent on|ho chuka|ho gaya|kar diya)\b|हो चुका|भेज दिया")


def claim_kind(text: str) -> str:
    """processed | no_request | delivered | policy | refusal | reference | other"""
    if _NO_REQUEST.search(text):
        return "no_request"
    if _DELIVERED.search(text):
        return "delivered"
    if PAID.search(text):
        return "processed"
    if POLICY.search(text):
        return "policy"
    if REFUSAL.search(text):
        return "refusal"
    if references_in(text):
        return "reference"
    return "other"


def is_refusal(text: str) -> bool:
    return bool(REFUSAL.search(text))


# -- offers ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Offer:
    kind: str  # refund | voucher | replacement | discount
    amount: int | float | None
    waiver: bool
    text_amounts: tuple[int | float, ...] = ()


def looks_like_offer(text: str) -> bool:
    return bool(_OFFER_CUE.search(text)) and (bool(amounts_in(text)) or bool(_VOUCHER.search(text)) or bool(_REPLACEMENT.search(text)) or bool(_DISCOUNT.search(text)))


def parse_offer(text: str, normalise=None) -> Offer:
    kind = "refund"
    if _VOUCHER.search(text):
        kind = "voucher"
    elif _REPLACEMENT.search(text):
        kind = "replacement"
    elif _DISCOUNT.search(text):
        kind = "discount"
    amounts = tuple(amounts_in(text, normalise))
    return Offer(kind, amounts[0] if amounts else None, bool(_WAIVER.search(text)), amounts)


def compare_to_mandate(offer: Offer, limits: dict, owed: float | None) -> tuple[str, str]:
    """("within" | "outside", reason). The agent never accepts either way; `within` means the offer is what the consumer
    asked for, so the call goes on to get a date and a reference. A partial amount is within only when the mandate
    says `accept_partial` and the amount reaches `min_amount`."""
    if offer.waiver:
        return "outside", "waiver"
    if offer.kind != "refund":
        return "outside", offer.kind
    if offer.amount is None:
        return "within", "no_amount"
    if owed is None:
        return "outside", "owed_unknown"
    if offer.amount >= owed:
        return "within", "full"
    if limits.get("accept_partial") and offer.amount >= float(limits.get("min_amount", owed)):
        return "within", "partial_allowed"
    return "outside", "partial"


def promise_date(text: str, today: date, normalise=None) -> str | None:
    """A date the provider promises something by: a future-tense sentence with a date that is not in the past."""
    if _PAST_MARKER.search(text) and not re.search(r"(?i)\bwill\b|ho jayega|milega|क्रेडिट होगा", text):
        return None
    if not _PROMISE_CUE.search(text):
        return None
    for iso in dates_in(text, today, normalise):
        if iso >= today.isoformat():
            return iso
    return None


# -- redirects -------------------------------------------------------------------------------------------------------

_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?(?:1800|1860)[\s-]?\d{3}[\s-]?\d{4}(?!\d)|(?<!\d)\d{10}(?!\d)|(?<!\d)\d{3,5}[\s-]\d{3,4}[\s-]\d{3,4}(?!\d)")
_CALL_CUE = re.compile(r"(?i)call|contact|dial|reach|phone|ring|transfer|number|par\b|पर|कॉल|संपर्क")


def redirect_number(text: str) -> str:
    """A phone number the provider sends the caller to, digits only, or ''."""
    prepared = to_ascii_digits(text)
    match = _PHONE.search(prepared)
    if match and _CALL_CUE.search(prepared):
        return re.sub(r"\D", "", match.group(0))
    return ""


# -- sentences -------------------------------------------------------------------------------------------------------


def split_sentences(text: str) -> list[str]:
    """Split on sentence ends outside square brackets (a citation label can hold a full stop)."""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    chars = list(text.strip())
    for index, ch in enumerate(chars):
        buf.append(ch)
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch in ".!?।" and depth == 0:
            nxt = chars[index + 1] if index + 1 < len(chars) else " "
            if nxt.isspace() or index + 1 == len(chars):
                if ch == "." and re.search(r"\b(?:Rs|No|Sec|Ltd|Pvt|Dr|Mr|Mrs|Ms)$", "".join(buf[:-1])):
                    continue
                out.append("".join(buf).strip())
                buf = []
    rest = "".join(buf).strip()
    if rest:
        out.append(rest)
    return [s for s in out if s]


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", spoken_to_digits(text))
