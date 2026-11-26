"""Local redaction of text before it reaches a model, a log or long-term storage.

Order of work: normalise spoken numbers, find sensitive spans with class rules, resolve overlaps by
precedence, then replace each span with a placeholder. Order ids become reversible tokens ([NUM_n]);
everything else is irreversible. If any detector raises, the whole segment is withheld.

Precedence (lowest number wins when spans overlap):
 1 card, by cue word      2 order id, by label or known format     3 email, tax id, address, identity
 4 phone                  5 card, by Luhn check                    6 one-time code, by cue
 7 any other 13 to 19 digit run (dropped)
Amounts, dates, years and short counts are never touched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.privacy.numbers import normalize_numbers

_RUN = re.compile(r"(?<![\w])\d+(?:[ -]\d+)*(?![\w])")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_HANDLE = re.compile(r"(?<![\w.])[\w.\-]{2,}@[A-Za-z]{2,}(?![\w.])")
_PASSPORT = re.compile(r"\b[A-Z]\d{7}\b")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_ORDER_LABEL = re.compile(
    r"(?i)\b(?:order|booking|reference|ref|transaction|txn|invoice|bill|awb|tracking|ticket|consignment)"
    r"(?:\s+(?:id|number|no|num|reference|ref))*\s*[:#.\-]*\s*"
)
_ORDER_VALUE = re.compile(r"(?=[A-Za-z0-9\-]*\d)[A-Za-z0-9][A-Za-z0-9\-]{3,}")
_KNOWN_ORDER = re.compile(r"\bOD\d{8,}\b|\b\d{3}-\d{7}-\d{7}\b")
_PHONE = re.compile(r"(?<![\w])(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?![\w])")
_PINCODE = re.compile(r"(?i)(?:pin\s*code|pincode|pin|पिन\s*कोड)\s*[:\-]?\s*([1-9]\d{5})\b")
_ADDRESS_HEAD = re.compile(r"(?i)\b(?:flat|house|plot|door|room|shop|h\.?\s?no\.?)\s*(?:no\.?\s*)?[A-Za-z0-9\-/]+")
_STREET = re.compile(
    r"\b(?:\d+[A-Za-z]?\s+)?(?:[A-Z][\w.]*\s+){1,3}(?:Road|Rd|Marg|Nagar|Colony|Street|Lane|Society|Apartments?|Enclave|Vihar|Layout|Chowk|Bazaar|Park|Gali)\b"
    r"|\bSector\s*\d+\b"
)
_AREA_AFTER = re.compile(r"\s*,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")
_STOP = re.compile(r"(?i)^\s*(?:pin\b|pincode\b|hai\b|rehta\b|rehti\b|pe\b|mein\b|ko\b|se\b|ka\b)")

_CARD_CUES = ("card", "debit", "credit", "expiry", "cvv", "cvc", "visa", "mastercard", "rupay")
_OTP_CUES = ("otp", "code", "verification", "cvv", "cvc", "one time", "one-time", "password", "pin")
_ID_CUES = ("aadhaar", "aadhar", "uid", "आधार")
_ACCOUNT_CUES = ("account", "acct", "a/c", "खाता", "passbook")
_PASSPORT_CUES = ("passport", "licence", "license", "voter")


class RedactionFailure(Exception):
    """Raised internally when a detector fails; the segment is withheld."""


@dataclass(frozen=True)
class Finding:
    kind: str
    start: int
    end: int
    priority: int


@dataclass
class RedactionResult:
    text: str
    tokens: dict[str, str] = field(default_factory=dict)  # "[NUM_1]" -> real value. Never log this.
    kinds: list[str] = field(default_factory=list)
    withheld: bool = False


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
        alt = not alt
    return total % 10 == 0


def _cue_in(text: str, start: int, end: int, cues: tuple[str, ...], before: int = 40, after: int = 14) -> bool:
    window = (text[max(0, start - before) : start] + " | " + text[end : end + after]).lower()
    return any(re.search(rf"(?<![a-z]){re.escape(cue)}(?![a-z])", window) for cue in cues)


def _currency_adjacent(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 6) : start].lower()
    after = text[end : end + 10].lower()
    return before.rstrip().endswith(("₹", "rs", "rs.", "inr")) or bool(re.match(r"\s*(?:rupees?|rupaye|rupiya|rs\b|inr\b|₹)", after))


def _digits_only(run: str) -> str:
    return re.sub(r"\D", "", run)


def _find(text: str) -> list[Finding]:
    found: list[Finding] = []

    for m in _EMAIL.finditer(text):
        found.append(Finding("email", m.start(), m.end(), 3))
    for m in _HANDLE.finditer(text):
        if not any(f.start <= m.start() < f.end for f in found):
            found.append(Finding("email", m.start(), m.end(), 3))
    for m in _PAN.finditer(text):
        found.append(Finding("identity", m.start(), m.end(), 3))
    for m in _PASSPORT.finditer(text):
        if _cue_in(text, m.start(), m.end(), _PASSPORT_CUES, before=30, after=0):
            found.append(Finding("identity", m.start(), m.end(), 3))

    # Addresses: head cue plus following comma segments, street words, and pin codes.
    for m in _ADDRESS_HEAD.finditer(text):
        end = m.end()
        for _ in range(3):
            seg = re.match(r"\s*,\s*[^,]{2,40}", text[end:])
            if not seg or _STOP.match(text[end + seg.group(0).index(",") + 1 :]):
                break
            piece = seg.group(0)
            stop = re.search(r"(?i)\s(?:pin\b|pincode\b|pin code\b|hai\b|rehta\b|rehti\b)", piece)
            if stop:
                piece = piece[: stop.start()]
                end += len(piece)
                break
            end += len(piece)
        found.append(Finding("address", m.start(), end, 3))
    for m in _STREET.finditer(text):
        end = m.end()
        area = _AREA_AFTER.match(text, end)
        if area:
            end = area.end()
        found.append(Finding("address", m.start(), end, 3))
    for m in _PINCODE.finditer(text):
        found.append(Finding("address", m.start(1), m.end(1), 3))

    # A bare pin code right after an address is part of it.
    for f in [f for f in found if f.kind == "address"]:
        tail = re.match(r"[\s,]*([1-9]\d{5})\b", text[f.end : f.end + 20])
        if tail:
            found.append(Finding("address", f.end + tail.start(1), f.end + tail.end(1), 3))

    # Known order formats and labelled ids.
    for m in _KNOWN_ORDER.finditer(text):
        found.append(Finding("order_id", m.start(), m.end(), 2))
    for label in _ORDER_LABEL.finditer(text):
        value = _ORDER_VALUE.match(text, label.end())
        if value and not _currency_adjacent(text, value.start(), value.end()):
            found.append(Finding("order_id", value.start(), value.end(), 2))

    for m in _RUN.finditer(text):
        run = m.group(0)
        digits = _digits_only(run)
        start, end = m.start(), m.end()
        if _currency_adjacent(text, start, end):
            continue
        n = len(digits)
        card_cue = _cue_in(text, start, end, _CARD_CUES, before=30, after=0)
        if n >= 13 and card_cue:
            found.append(Finding("card", start, end, 1))
        elif 13 <= n <= 19 and luhn_ok(digits):
            found.append(Finding("card", start, end, 5))
        elif 13 <= n <= 19:
            found.append(Finding("other_long", start, end, 7))
        if n == 12 and _cue_in(text, start, end, _ID_CUES, before=30, after=10):
            found.append(Finding("identity", start, end, 3))
        elif 9 <= n <= 18 and _cue_in(text, start, end, _ACCOUNT_CUES, before=30, after=10):
            found.append(Finding("identity", start, end, 3))
        if _PHONE.fullmatch(run) and n in (10, 12) and not _cue_in(text, start, end, ("order", "booking", "ticket"), before=20, after=0):
            found.append(Finding("phone", start, end, 4))
        low, high = (3, 8) if _cue_in(text, start, end, ("cvv", "cvc"), before=25, after=10) else (4, 8)
        if low <= n <= high and _cue_in(text, start, end, _OTP_CUES, before=35, after=12):
            found.append(Finding("otp", start, end, 6))
    for m in _PHONE.finditer(text):
        if not any(f.start <= m.start() < f.end for f in found if f.priority <= 3):
            found.append(Finding("phone", m.start(), m.end(), 4))
    return found


def _resolve(findings: list[Finding]) -> list[Finding]:
    chosen: list[Finding] = []
    for f in sorted(findings, key=lambda f: (f.priority, f.start, -(f.end - f.start))):
        if all(f.end <= c.start or f.start >= c.end for c in chosen):
            chosen.append(f)
    return sorted(chosen, key=lambda f: f.start)


_PLACEHOLDER = {
    "otp": "[CODE]", "card": "[CARD]", "identity": "[ID]", "phone": "[PHONE]", "email": "[EMAIL]",
    "address": "[ADDRESS]", "other_long": "[NUMBER]",
}


class Redactor:
    """Stateless apart from the token map passed in."""

    def redact(self, text: str, tokens: dict[str, str] | None = None) -> RedactionResult:
        known = dict(tokens or {})
        try:
            normalised = normalize_numbers(text)
            chosen = _resolve(_find(normalised))
            reverse = {value: token for token, value in known.items()}
            out: list[str] = []
            cursor = 0
            kinds: list[str] = []
            for f in chosen:
                out.append(normalised[cursor : f.start])
                if f.kind == "order_id":
                    value = normalised[f.start : f.end]
                    token = reverse.get(value)
                    if token is None:
                        token = f"[NUM_{len(known) + 1}]"
                        known[token] = value
                        reverse[value] = token
                    out.append(token)
                else:
                    out.append(_PLACEHOLDER[f.kind])
                kinds.append(f.kind)
                cursor = f.end
            out.append(normalised[cursor:])
            return RedactionResult("".join(out), known, kinds)
        except Exception as exc:  # noqa: BLE001 - fail closed on anything
            raise RedactionFailure("detector error") from exc

    def redact_or_withhold(self, text: str, tokens: dict[str, str] | None = None) -> RedactionResult:
        try:
            return self.redact(text, tokens)
        except RedactionFailure:
            return RedactionResult("", dict(tokens or {}), [], withheld=True)

    @staticmethod
    def restore(text: str, tokens: dict[str, str]) -> str:
        for token, value in tokens.items():
            text = text.replace(token, value)
        return text
