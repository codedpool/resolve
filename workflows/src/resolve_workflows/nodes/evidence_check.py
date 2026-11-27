"""check_case_evidence: compare what the provider claims with what the case holds, in code.

Amounts, dates and reference numbers are first turned into normalised values ("twelve hundred" and "Rs. 1,200" both
become 1200; "twentieth of November" becomes 2026-11-20; "zm-ref 558201" and "ZM-REF-558201" are the same reference)
and only then compared. A model never compares raw numbers. The verdict for each field is `match`, `mismatch` or
`missing`; `missing` means the case holds nothing to compare the claim with, which is not the same as the claim being wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chah": 6, "saat": 7,
    "aath": 8, "nau": 9, "shunya": 0,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "सात": 7, "आठ": 8, "नौ": 9,
}
_TENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
    "das": 10, "dus": 10, "gyarah": 11, "barah": 12, "terah": 13, "chaudah": 14, "pandrah": 15, "solah": 16, "satrah": 17,
    "atharah": 18, "unnis": 19, "bees": 20, "ikkis": 21, "baais": 22, "teis": 23, "chaubis": 24, "pachchis": 25,
    "pachis": 25, "pachees": 25, "chhabbis": 26, "sattais": 27, "atthais": 28, "untis": 29, "tees": 30, "chalis": 40,
    "pachas": 50, "pachaas": 50, "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90,
    "दस": 10, "बीस": 20, "तीस": 30, "चालीस": 40, "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90,
}
_HUNDRED = {"hundred": 100, "sau": 100, "सौ": 100}
_BIG = {"thousand": 1000, "hazaar": 1000, "hazar": 1000, "हज़ार": 1000, "हजार": 1000, "lakh": 100_000, "lac": 100_000, "लाख": 100_000,
        "crore": 10_000_000, "करोड़": 10_000_000}
_WORD = re.compile(r"[A-Za-zऀ-ॿ]+")
_CURRENCY = {"rs", "inr", "rupees", "rupee", "rupaye", "rupiya", "rupay", "रुपये", "रुपए", "रुपया"}
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
    "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12,
    "जनवरी": 1, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8, "सितंबर": 9, "अक्टूबर": 10,
    "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12,
}
_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
    "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
    "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}
_TIME_UNITS = {"hours", "hour", "days", "day", "weeks", "week", "months", "month", "minutes", "ghante", "din", "hafte", "mahine"}


def to_ascii_digits(text: str) -> str:
    return text.translate(_DEVANAGARI_DIGITS)


def spoken_to_digits(text: str) -> str:
    """Replace runs of spoken number words (English, Hinglish, Hindi) by digits. "twelve hundred" -> "1200".
    A run of only unit words is left alone unless a currency word follows or precedes it ("do" also means "give")."""
    text = to_ascii_digits(text)
    out: list[str] = []
    last = 0
    tokens = list(_WORD.finditer(text))
    i = 0
    while i < len(tokens):
        word = tokens[i].group(0).lower()
        if not _is_number_word(word) or (word in _AMBIGUOUS and not _ambiguous_ok(text, tokens, i)):
            i += 1
            continue
        j = i
        run = [tokens[i]]
        while j + 1 < len(tokens):
            gap = text[tokens[j].end(): tokens[j + 1].start()]
            nxt = tokens[j + 1].group(0).lower()
            if re.fullmatch(r"[\s\-]*", gap) and _is_number_word(nxt):
                run.append(tokens[j + 1])
                j += 1
            elif re.fullmatch(r"\s+", gap) and nxt == "and" and j + 2 < len(tokens) and _is_number_word(tokens[j + 2].group(0).lower()):
                run.append(tokens[j + 1])
                run.append(tokens[j + 2])
                j += 2
            else:
                break
        words = [t.group(0).lower() for t in run]
        if _qualifies(words, text, run[0].start(), run[-1].end()):
            value = _run_value([w for w in words if w != "and"])
            if value is not None:
                out.append(text[last:run[0].start()])
                out.append(str(value))
                last = run[-1].end()
        i = j + 1
    out.append(text[last:])
    return "".join(out)


_AMBIGUOUS = {"do", "ek", "teen", "char", "sat", "one"}  # also ordinary words ("do" is "give" or English "do")


def _ambiguous_ok(text: str, tokens: list, index: int) -> bool:
    """An ambiguous word is a number only when a multiplier or a currency word follows it directly."""
    nxt = tokens[index + 1].group(0).lower() if index + 1 < len(tokens) else ""
    gap = text[tokens[index].end(): tokens[index + 1].start()] if index + 1 < len(tokens) else ""
    return bool(re.fullmatch(r"\s+", gap)) and (nxt in _BIG or nxt in _HUNDRED or nxt in _CURRENCY)


def _is_number_word(word: str) -> bool:
    return word in _UNITS or word in _TENS or word in _HUNDRED or word in _BIG


def _qualifies(words: list[str], text: str, start: int, end: int) -> bool:
    if any(w in _HUNDRED or w in _BIG or w in _TENS for w in words):
        # a lone Hindi "do"/"ek" style word is excluded above; tens words such as "das" are unambiguous enough
        return True
    after = re.match(r"\s*([A-Za-zऀ-ॿ]+)", text[end:])
    before = re.search(r"([A-Za-zऀ-ॿ₹]+)\W*$", text[:start])
    near = {(after.group(1).lower() if after else ""), (before.group(1).lower() if before else "")}
    return bool(near & _CURRENCY)


def _run_value(words: list[str]) -> int | None:
    total = 0
    current = 0
    for w in words:
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w in _HUNDRED:
            current = (current or 1) * 100
        elif w in _BIG:
            total += (current or 1) * _BIG[w]
            current = 0
        else:
            return None
    return total + current


# -- amounts ---------------------------------------------------------------------------------------------------------

_MONEY_CONTEXT = re.compile(
    r"(?i)refund|pay|paid|amount|offer|credit|voucher|settle|rupee|rupaye|rs\b|₹|inr|reimburs|deduct|charge|price|cost|diye|दिए|रुपये|रुपए|cash|wapas|वापस",
)
_NUM = re.compile(r"(?<![A-Za-z0-9\-])(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![A-Za-z0-9])")
_PLAIN_CURRENCY_AFTER = re.compile(r"(?i)\s*(?:/-|rs\.?|inr|rupees?|rupaye|rupiya|रुपये|रुपए)")


def amounts_in(text: str, normalise: Callable[[str], str] | None = None) -> list[int | float]:
    """Money amounts in the text, as numbers. A number counts when a currency word touches it, or when it stands in a
    sentence about money and is not a date, a duration or part of a code."""
    prepared = text
    if normalise:
        prepared = normalise(prepared)
    prepared = spoken_to_digits(prepared)
    found: list[int | float] = []
    context = bool(_MONEY_CONTEXT.search(prepared))
    for match in _NUM.finditer(prepared):
        raw = match.group(1)
        value = float(raw.replace(",", ""))
        value = int(value) if value == int(value) else value
        before = prepared[max(0, match.start() - 6): match.start()].lower()
        after_text = prepared[match.end(): match.end() + 14]
        word_after = re.match(r"\s*(?:of\s+|ko\s+|ke\s+)?([A-Za-z]+)", after_text)
        next_word = word_after.group(1).lower() if word_after else ""
        currency_touch = bool(
            re.search(r"(?:₹|rs\.?|inr)\s*$", before) or _PLAIN_CURRENCY_AFTER.match(after_text)
            or next_word in _CURRENCY or "/-" in after_text[:3]
        )
        run = re.search(r"\d[\d \-]{7,}\d", prepared[max(0, match.start() - 14): match.end() + 14])
        if run and len(re.sub(r"\D", "", run.group(0))) >= 9 and not currency_touch:
            continue  # a phone or card number written in groups
        if next_word in _MONTHS or next_word in _TIME_UNITS or re.match(r"\s*(?:st|nd|rd|th)\b", after_text):
            continue
        if re.search(r"(?:\d{1,2}[/\-.])$", prepared[max(0, match.start() - 3): match.start()]) or re.match(r"[/\-.]\d{1,4}", after_text):
            continue  # part of a numeric date
        if currency_touch or (context and value >= 100 and len(raw.replace(",", "").split(".")[0]) >= 3):
            if not (1900 <= value <= 2100 and not currency_touch):
                found.append(value)
    return found


def normalise_amount(value: str, normalise: Callable[[str], str] | None = None) -> str:
    """The case's stored amount as a plain number string, "" if there is none."""
    nums = amounts_in(f"Rs {value}", normalise) if value else []
    if not nums:
        match = re.search(r"\d+(?:\.\d+)?", to_ascii_digits(str(value)).replace(",", ""))
        return _fmt(float(match.group(0))) if match else ""
    return _fmt(nums[0])


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:.2f}".rstrip("0")


# -- dates -----------------------------------------------------------------------------------------------------------

_ORD_PATTERN = "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True))
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DAY_FIRST = re.compile(
    rf"(?i)(?<![\d.])(?:the\s+)?(?P<day>\d{{1,2}}|(?:twenty|thirty)[\s\-]+(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth)|{_ORD_PATTERN})"
    rf"(?:st|nd|rd|th)?\s*(?:of\s+|ko\s+)?(?P<month>{_MONTH_PATTERN})\b(?:\s*,?\s*(?P<year>\d{{4}}))?"
)
_MONTH_FIRST = re.compile(rf"(?i)\b(?P<month>{_MONTH_PATTERN})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b(?:\s*,?\s*(?P<year>\d{{4}}))?")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_NUMERIC = re.compile(r"(?<![\d/])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?![\d/])")


def _day_value(token: str) -> int | None:
    token = re.sub(r"[\s\-]+", " ", token.lower().strip())
    if token.isdigit():
        return int(token)
    if token in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[token]
    parts = token.split(" ")
    if len(parts) == 2 and parts[0] in ("twenty", "thirty") and parts[1] in _ORDINAL_WORDS:
        return _TENS[parts[0]] + _ORDINAL_WORDS[parts[1]]
    return None


_COMPOUND_ORD = r"(?:twenty|thirty)[\s\-]+(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth)"
_ORD_BEFORE_MONTH = re.compile(rf"(?i)\b({_COMPOUND_ORD}|{_ORD_PATTERN})(?=\s*(?:of\s+)?(?:{_MONTH_PATTERN})\b)")
_ORD_AFTER_MONTH = re.compile(rf"(?i)\b((?:{_MONTH_PATTERN})\s+)({_COMPOUND_ORD}|{_ORD_PATTERN})\b")


def _ordinals_to_digits(text: str) -> str:
    text = _ORD_BEFORE_MONTH.sub(lambda m: str(_day_value(m.group(1)) or m.group(1)), text)
    return _ORD_AFTER_MONTH.sub(lambda m: m.group(1) + str(_day_value(m.group(2)) or m.group(2)), text)


def dates_in(text: str, today: date, normalise: Callable[[str], str] | None = None) -> list[str]:
    """ISO dates in the text. A date without a year takes the year of `today`."""
    prepared = to_ascii_digits(text)
    if normalise:
        prepared = normalise(prepared)
    prepared = spoken_to_digits(_ordinals_to_digits(prepared))
    found: list[str] = []

    def add(year: int, month: int, day: int) -> None:
        try:
            iso = date(year, month, day).isoformat()
        except ValueError:
            return
        if iso not in found:
            found.append(iso)

    for m in _ISO.finditer(prepared):
        add(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    for m in _NUMERIC.finditer(prepared):
        year = int(m.group(3))
        add(year + 2000 if year < 100 else year, int(m.group(2)), int(m.group(1)))
    for pattern in (_DAY_FIRST, _MONTH_FIRST):
        for m in pattern.finditer(prepared):
            day = _day_value(m.group("day"))
            month = _MONTHS.get(m.group("month").lower())
            if day is None or month is None:
                continue
            add(int(m.group("year")) if m.group("year") else today.year, month, day)
    return found


# -- references ------------------------------------------------------------------------------------------------------

_HYPHEN_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,8}(?:-[A-Za-z0-9]{2,})+)(?![A-Za-z0-9\-])")
_ALNUM_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,4}\d{6,}|\d{3,}[A-Za-z]+\d*)(?![A-Za-z0-9])")
_CUE_THEN_CODE = re.compile(
    r"(?i)(?:reference|ref|ticket|utr|transaction|txn|complaint|case|request|docket|rrn|acknowledg\w*)\s*(?:number|no\.?|id|code|is|:|#|\s)*\s*([A-Za-z0-9][A-Za-z0-9\-]{4,})"
)


def normalise_reference(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", to_ascii_digits(value).upper())


def reference_pairs(text: str) -> list[tuple[str, str]]:
    """(as written, normalised) for each reference and ticket number. Order ids are returned too: the caller tells
    them apart by comparing with the stored order id."""
    prepared = to_ascii_digits(text)
    found: list[tuple[str, str]] = []
    for pattern in (_HYPHEN_CODE, _ALNUM_CODE, _CUE_THEN_CODE):
        for m in pattern.finditer(prepared):
            token = normalise_reference(m.group(1))
            # a "hyphenated" run of plain words ("follow-up") has no digit and is dropped here
            if len(token) >= 5 and any(c.isdigit() for c in token) and all(token != n for _, n in found):
                found.append((m.group(1).upper(), token))
    return found


def references_in(text: str, normalise: Callable[[str], str] | None = None) -> list[str]:
    """Reference and ticket numbers, normalised (upper case, no separators)."""
    return [norm for _, norm in reference_pairs(text)]


# -- the check -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Credit:
    """Money the consumer's own evidence shows arriving (a bank statement credit, a refund confirmation)."""

    amount: str
    date: str = ""
    reference: str = ""


@dataclass(frozen=True)
class CaseEvidence:
    paid_amount: str = ""  # what the consumer paid and is owed back
    order_date: str = ""
    order_id: str = ""
    known_references: tuple[str, ...] = ()  # references the consumer already holds for this case
    credits: tuple[Credit, ...] = ()


@dataclass(frozen=True)
class FieldVerdict:
    field: str  # amount_received | amount_owed | date | reference
    verdict: str  # match | mismatch | missing
    claimed: str
    recorded: str = ""


@dataclass(frozen=True)
class Claim:
    amounts: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    references: tuple[str, ...] = ()  # order id removed


@dataclass(frozen=True)
class EvidenceVerdict:
    overall: str  # match | mismatch | missing
    fields: tuple[FieldVerdict, ...] = field(default_factory=tuple)
    claim: Claim = field(default_factory=Claim)

    def get(self, name: str) -> FieldVerdict | None:
        return next((f for f in self.fields if f.field == name), None)

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "fields": [{"field": f.field, "verdict": f.verdict, "claimed": f.claimed} for f in self.fields],
        }


def extract_claim(text: str, evidence: CaseEvidence, today: date, normalise: Callable[[str], str] | None = None) -> Claim:
    order = normalise_reference(evidence.order_id)
    refs = tuple(r for r in references_in(text, normalise) if r != order)
    return Claim(
        amounts=tuple(_fmt(float(a)) for a in amounts_in(text, normalise)),
        dates=tuple(dates_in(text, today, normalise)),
        references=refs,
    )


def check_case_evidence(text: str, evidence: CaseEvidence, today: date, normalise: Callable[[str], str] | None = None) -> EvidenceVerdict:
    """Compare the amounts, dates and references in a provider claim with the case, on normalised values."""
    claim = extract_claim(text, evidence, today, normalise)
    fields: list[FieldVerdict] = []
    credit_amounts = {normalise_amount(c.amount) for c in evidence.credits}
    credit_dates = {c.date for c in evidence.credits if c.date}
    credit_refs = {normalise_reference(c.reference) for c in evidence.credits if c.reference}
    known_refs = {normalise_reference(r) for r in evidence.known_references} | credit_refs
    owed = normalise_amount(evidence.paid_amount)

    if claim.amounts:
        amount = claim.amounts[0]
        if evidence.credits:
            hit = amount in credit_amounts
            fields.append(FieldVerdict("amount_received", "match" if hit else "mismatch", amount, ", ".join(sorted(credit_amounts))))
        else:
            fields.append(FieldVerdict("amount_received", "missing", amount))
        if owed:
            fields.append(FieldVerdict("amount_owed", "match" if amount == owed else "mismatch", amount, owed))
        else:
            fields.append(FieldVerdict("amount_owed", "missing", amount))
    if claim.dates:
        day = claim.dates[0]
        if credit_dates:
            fields.append(FieldVerdict("date", "match" if day in credit_dates else "mismatch", day, ", ".join(sorted(credit_dates))))
        else:
            fields.append(FieldVerdict("date", "missing", day))
    if claim.references:
        ref = claim.references[0]
        if known_refs:
            fields.append(FieldVerdict("reference", "match" if ref in known_refs else "mismatch", ref))
        else:
            fields.append(FieldVerdict("reference", "missing", ref))

    verdicts = {f.verdict for f in fields}
    received = [f for f in fields if f.field in {"amount_received", "date", "reference"}]
    if "mismatch" in verdicts:
        overall = "mismatch"
    elif received and all(f.verdict == "match" for f in received) and evidence.credits:
        overall = "match"
    else:
        overall = "missing"
    return EvidenceVerdict(overall, tuple(fields), claim)
