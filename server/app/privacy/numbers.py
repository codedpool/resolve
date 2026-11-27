"""Spoken-number, amount and date normaliser (Hindi, English and mixed).

Runs before redaction. Everything here is local, deterministic and has no model call.

Rules worth knowing:
- A run of single digit words is a digit string ("nau aath saat" -> "987", "double paanch" -> "55").
- A run that contains tens, teens or a multiplier is a quantity ("twelve hundred" -> "1200").
- A lone word is left alone unless it is unambiguous (English "twenty") or sits next to a rupee cue,
  because "do" also means "give" and "ek" also means "a".
- Digit groups written as digits are never merged here. The redactor does that for detection only.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_DIGIT_WORDS = {
    "zero": 0, "shunya": 0, "sifar": 0, "jero": 0, "शून्य": 0,
    "one": 1, "ek": 1, "एक": 1,
    "two": 2, "do": 2, "दो": 2,
    "three": 3, "teen": 3, "तीन": 3,
    "four": 4, "char": 4, "chaar": 4, "चार": 4,
    "five": 5, "paanch": 5, "panch": 5, "paach": 5, "पांच": 5, "पाँच": 5,
    "six": 6, "chhe": 6, "che": 6, "chah": 6, "chhah": 6, "chhe": 6, "छह": 6, "छः": 6, "छे": 6,
    "seven": 7, "saat": 7, "sat": 7, "सात": 7,
    "eight": 8, "aath": 8, "ath": 8, "आठ": 8,
    "nine": 9, "nau": 9, "नौ": 9,
}

_ENGLISH_TEENS_TENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_HINDI_10_99 = (
    "das dus|gyarah|barah|terah|chaudah|pandrah|solah|satrah|atharah|unnis unnees|bees|ikkis ikis|baais bais|"
    "teis teyis|chaubis|pachchis pachis pachees pachchees|chhabbis chabbis|sattais|atthais|untis|tees|ikatis|"
    "battis|taintis tentis|chauntis|paintis|chhattis chattis|saintis|adtis|untalis|chalis chaalis chaalees|ikatalis|bayalis|"
    "taintalis|chauvalis|paintalis|chhiyalis|saintalis|adtalis|unchas|pachas pachaas|ikyavan|baavan bavan|"
    "trepan|chauvan|pachpan|chhappan|sattavan|athavan|unsath|saath saath|iksath|baasath|tirsath|chausath|"
    "painsath|chhiyasath|sadsath|adsath|unhattar|sattar|ikahattar|bahattar|tihattar|chauhattar|pachhattar|"
    "chhihattar|satahattar|athahattar|unnasi|assi|ikyasi|bayasi|tirasi|chaurasi|pachasi|chhiyasi|sattasi|"
    "atthasi|nauasi|nabbe|ikyanave|baanave|tiranave|chauranave|pachanave|chhiyanave|sattanave|atthanave|"
    "ninyanave"
).split("|")

_TENS_WORDS: dict[str, int] = dict(_ENGLISH_TEENS_TENS)
for _offset, _group in enumerate(_HINDI_10_99):
    for _name in _group.split():
        _TENS_WORDS.setdefault(_name, 10 + _offset)
_TENS_WORDS.update({"दस": 10, "बीस": 20, "तीस": 30, "चालीस": 40, "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90})

_MULT = {
    "hundred": 100, "sau": 100, "सौ": 100,
    "thousand": 1000, "hazaar": 1000, "hazar": 1000, "hajar": 1000, "हज़ार": 1000, "हजार": 1000,
    "lakh": 100_000, "lac": 100_000, "lakhs": 100_000, "लाख": 100_000,
    "crore": 10_000_000, "करोड़": 10_000_000, "karod": 10_000_000,
}
_FRACTIONS = {"dedh": 1.5, "ded": 1.5, "dhai": 2.5, "dhaai": 2.5, "adhai": 2.5, "sawa": 1.25, "सवा": 1.25, "डेढ़": 1.5, "ढाई": 2.5}
_REPEAT = {"double": 2, "dabal": 2, "डबल": 2, "triple": 3, "tripal": 3, "ट्रिपल": 3}
_HALF_PREFIX = {"saadhe", "sadhe", "साढ़े"}
_CUES = {"rupaye", "rupees", "rupee", "rs", "rupiya", "rupay", "inr", "रुपये", "रुपए", "रुपया"}

_TOKEN = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?|[A-Za-zऀ-ॿ]+")

_RANK_ENGLISH_TENS = set(_ENGLISH_TEENS_TENS)
_NOT_ID_PREFIXES = {"OTP", "CVV", "CVC", "PIN", "UPI", "ID", "NO", "RS", "INR", "OK"}


@dataclass
class _Tok:
    start: int
    end: int
    kind: str  # digit, tens, mult, frac, repeat, half, literal, and
    value: float | int | str
    word: str


def _classify(match: re.Match[str]) -> _Tok | None:
    raw = match.group(0)
    word = raw.lower()
    start, end = match.span()
    if raw[0].isdigit():
        return _Tok(start, end, "literal", raw.replace(",", ""), raw)
    if word in _REPEAT:
        return _Tok(start, end, "repeat", _REPEAT[word], word)
    if word in _DIGIT_WORDS:
        return _Tok(start, end, "digit", _DIGIT_WORDS[word], word)
    if word in _TENS_WORDS:
        return _Tok(start, end, "tens", _TENS_WORDS[word], word)
    if word in _MULT:
        return _Tok(start, end, "mult", _MULT[word], word)
    if word in _FRACTIONS:
        return _Tok(start, end, "frac", _FRACTIONS[word], word)
    if word in _HALF_PREFIX or word == "paune":
        return _Tok(start, end, "half", word, word)
    if word == "and":
        return _Tok(start, end, "and", word, word)
    return None


def word_to_int(word: str) -> int | None:
    """Value of one number word (0 to 99), or None."""
    w = word.lower().strip()
    if w in _DIGIT_WORDS:
        return _DIGIT_WORDS[w]
    return _TENS_WORDS.get(w)


def _quantity(tokens: list[_Tok]) -> int | float | None:
    big = 0.0
    small = 0.0
    last = ""
    half = ""
    for tok in tokens:
        if tok.kind == "and":
            continue
        if tok.kind == "half":
            half = str(tok.value)
            last = "half"
            continue
        if tok.kind in {"digit", "tens", "literal", "frac"}:
            value = float(tok.value)
            if half:
                value = value + 0.5 if half != "paune" else value - 0.25
                half = ""
            if last in {"digit", "literal", "frac"} and last != "":
                return None
            if last == "tens":
                if tok.kind != "digit":
                    return None
                small += value
            else:
                small += value
            last = tok.kind
            continue
        if tok.kind == "mult":
            multiplier = float(tok.value)
            if multiplier >= 1000:
                big += (small or 1.0) * multiplier
                small = 0.0
            else:
                small = (small or 1.0) * multiplier
            last = "mult"
            continue
        return None
    total = big + small
    return int(total) if total == int(total) else total


def _digits(tokens: list[_Tok]) -> str | None:
    out: list[str] = []
    repeat = 1
    for tok in tokens:
        if tok.kind == "repeat":
            repeat = int(tok.value)
            continue
        if tok.kind == "digit":
            out.append(str(tok.value) * repeat)
            repeat = 1
        elif tok.kind == "literal":
            out.append(str(tok.value) * repeat)
            repeat = 1
        else:
            return None
    if repeat != 1:
        return None
    return "".join(out)


def _convert(tokens: list[_Tok]) -> str | None:
    kinds = {t.kind for t in tokens}
    if kinds <= {"digit", "repeat", "literal"}:
        if "digit" not in kinds and "repeat" not in kinds:
            return None  # only digit groups: left as written
        return _digits(tokens)
    value = _quantity(tokens)
    if value is None:
        return None
    return str(value)


def _cue_follows(text: str, end: int) -> bool:
    match = re.match(r"\s*([A-Za-zऀ-ॿ]+)", text[end:])
    return bool(match) and match.group(1).lower() in _CUES


def _cue_precedes(text: str, start: int) -> bool:
    before = text[:start].rstrip()
    return before.endswith("₹") or bool(re.search(r"(?i)\b(?:rs\.?|inr)$", before))


def normalize_numbers(text: str) -> str:
    """Return the text with spoken number runs replaced by digits."""
    text = text.translate(_DEVANAGARI_DIGITS)
    toks: list[_Tok | None] = [_classify(m) for m in _TOKEN.finditer(text)]
    out: list[str] = []
    cursor = 0
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok is None or tok.kind == "and":
            i += 1
            continue
        # Build a run of adjacent number tokens separated only by spaces.
        run = [tok]
        j = i + 1
        while j < len(toks):
            nxt = toks[j]
            if nxt is None:
                break
            gap = text[run[-1].end : nxt.start]
            if gap.strip() != "":
                break
            if nxt.kind == "and":
                after = toks[j + 1] if j + 1 < len(toks) else None
                if run[-1].kind in {"mult", "tens"} and after is not None and after.kind in {"digit", "tens"} and text[nxt.end : after.start].strip() == "":
                    run.append(nxt)
                    j += 1
                    continue
                break
            run.append(nxt)
            j += 1
        while run and run[-1].kind == "and":
            run.pop()
        words = [t for t in run if t.kind != "literal"]
        replacement: str | None = None
        if len(run) == 1:
            only = run[0]
            if only.kind == "tens" and only.word in _RANK_ENGLISH_TENS:
                replacement = str(only.value)
            elif only.kind in {"digit", "tens", "mult", "frac"} and (_cue_follows(text, only.end) or _cue_precedes(text, only.start)):
                replacement = str(only.value)
        elif words:
            replacement = _convert(run)
        if replacement is not None:
            prefix = text[cursor : run[0].start]
            if replacement.isdigit():
                glued = re.search(r"(?<![A-Za-z])([A-Z]{1,5})\s+$", prefix)
                if glued and glued.group(1) not in _NOT_ID_PREFIXES:
                    prefix = prefix.rstrip()  # "OD 1234" -> "OD1234"
            out.append(prefix)
            out.append(replacement)
            cursor = run[-1].end
        i += len(run)
    out.append(text[cursor:])
    return "".join(out)


_AMOUNT = re.compile(
    r"(?:(?<![A-Za-z])(?:₹|rs\.?|inr)\s*(?P<pre>\d+(?:,\d+)*(?:\.\d+)?)(?:\s*/-)?)"
    r"|(?:(?P<post>\d+(?:,\d+)*(?:\.\d+)?)\s*(?:/-)?\s*(?:rupees?|rupaye|rupiya|rupay|rs\b|inr\b|₹|रुपये|रुपए|रुपया))",
    re.IGNORECASE,
)


def extract_amounts(text: str) -> list[int]:
    """Rupee amounts mentioned in the text, as whole rupees, in order."""
    normalised = normalize_numbers(text)
    amounts: list[int] = []
    for match in _AMOUNT.finditer(normalised):
        raw = (match.group("pre") or match.group("post")).replace(",", "")
        value = float(raw)
        amounts.append(int(value) if value == int(value) else int(round(value)))
    return amounts


@dataclass(frozen=True)
class ParsedDate:
    value: date
    approximate: bool


_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_WEEKDAYS = {
    "monday": 0, "somvar": 0, "somwar": 0, "tuesday": 1, "mangalvar": 1, "mangalwar": 1, "wednesday": 2, "budhvar": 2,
    "budhwar": 2, "thursday": 3, "guruvar": 3, "guruwar": 3, "brihaspativar": 3, "virvar": 3, "friday": 4, "shukravar": 4,
    "shukrawar": 4, "saturday": 5, "shanivar": 5, "shaniwar": 5, "sunday": 6, "ravivar": 6, "raviwar": 6, "itwar": 6,
}
_LAST = r"(?:last|pichhle|pichle|pichhla|pichla)"


def _shift_month(ref: date, months: int, day: int | None = None) -> date:
    index = ref.year * 12 + (ref.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    wanted = day if day is not None else ref.day
    return date(year, month, min(wanted, calendar.monthrange(year, month)[1]))


def _day_number(token: str) -> int | None:
    token = token.translate(_DEVANAGARI_DIGITS)
    if token.isdigit():
        return int(token)
    return word_to_int(token)


def parse_date(text: str, ref: date) -> ParsedDate | None:
    """Resolve a spoken or written date against a reference date. Returns None if not understood."""
    t = text.translate(_DEVANAGARI_DIGITS).lower().strip().rstrip(".")
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t):
        return ParsedDate(date(int(m[1]), int(m[2]), int(m[3])), False)
    if m := re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", t):
        year = int(m[3]) + (2000 if int(m[3]) < 100 else 0)
        try:
            return ParsedDate(date(year, int(m[2]), int(m[1])), False)
        except ValueError:
            return None
    names = "|".join(sorted(_MONTHS, key=len, reverse=True))
    if m := re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({names})(?:\s+(\d{{4}}))?", t):
        return ParsedDate(date(int(m[3] or ref.year), _MONTHS[m[2]], int(m[1])), False)
    if m := re.fullmatch(rf"({names})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", t):
        return ParsedDate(date(int(m[3] or ref.year), _MONTHS[m[1]], int(m[2])), False)
    if t in {"today", "aaj"}:
        return ParsedDate(ref, False)
    if t == "yesterday":
        return ParsedDate(ref - timedelta(days=1), False)
    if t == "kal":
        return ParsedDate(ref - timedelta(days=1), True)  # past tense assumed; "kal" can also mean tomorrow
    if t in {"parso", "parson", "day before yesterday"}:
        return ParsedDate(ref - timedelta(days=2), True)
    if m := re.fullmatch(r"(\S+)\s+(?:days?\s+ago|din\s+(?:pehle|pahle))", t):
        n = _day_number(m[1])
        if n is not None:
            return ParsedDate(ref - timedelta(days=n), False)
    if m := re.fullmatch(rf"{_LAST}\s+(\w+)", t):
        word = m[1]
        if word in _WEEKDAYS:
            delta = (ref.weekday() - _WEEKDAYS[word]) % 7 or 7
            return ParsedDate(ref - timedelta(days=delta), False)
        if word in {"week", "hafte", "hafta", "saptah"}:
            return ParsedDate(ref - timedelta(days=7), True)
        if word in {"month", "mahine", "mahina"}:
            return ParsedDate(_shift_month(ref, -1), True)
    if m := re.fullmatch(rf"{_LAST}\s+(?:mahine|mahina)\s+(?:ki|ka)\s+(\S+)\s+tarikh(?:\s+ko)?", t):
        n = _day_number(m[1])
        if n is not None and 1 <= n <= 31:
            return ParsedDate(_shift_month(ref, -1, n), False)
    if m := re.fullmatch(r"(\S+?)(?:st|nd|rd|th)?(?:\s+tarikh(?:\s+ko)?)?", t):
        n = _day_number(m[1])
        if n is not None and 1 <= n <= 31 and (t.endswith(("th", "st", "nd", "rd")) or "tarikh" in t):
            if n <= ref.day:
                return ParsedDate(_shift_month(ref, 0, n), True)
            return ParsedDate(_shift_month(ref, -1, n), True)
    return None
