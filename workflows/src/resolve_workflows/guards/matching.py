"""Matching of registered values (anything the mandate does not allow) against free text.

Used by the output guard to find leaks and by the context builder to mask a value that sits inside an allowed
field. Matching is on normalised forms: Devanagari digits become ASCII digits, spoken digit runs ("nine eight seven")
become digits, digit groups separated by spaces or hyphens are joined, case and punctuation are ignored.
"""

from __future__ import annotations

import re
import unicodedata

_DIGIT_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "shunya": 0, "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6,
    "cheh": 6, "chhey": 6, "saat": 7, "sat": 7, "aath": 8, "ath": 8, "nau": 9,
    "शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6, "छः": 6, "छे": 6, "सात": 7,
    "आठ": 8, "नौ": 9,
}
_MULTIPLIERS = {"double": 2, "dabal": 2, "triple": 3, "तिगुना": 3, "डबल": 2, "ट्रिपल": 3}
_TOKEN = re.compile(r"\S+")
_RUN = re.compile(r"\d(?:[ \-.]?\d)*")
_PUNCT = re.compile(r"[^\w@#]+", re.UNICODE)


def ascii_digits(text: str) -> str:
    """Map every Unicode decimal digit (for example Devanagari) to its ASCII form."""
    return "".join(str(unicodedata.decimal(ch)) if ch.isdigit() and unicodedata.decimal(ch, None) is not None else ch for ch in text)


def _strip(token: str) -> str:
    return token.strip(".,;:!?()[]{}\"'।|").casefold()


def spoken_digits_to_digits(text: str, min_run: int = 3) -> str:
    """Replace runs of at least `min_run` spoken digits with the digits ("double five" counts as two)."""
    tokens = _TOKEN.findall(text)
    out: list[str] = []
    index = 0
    while index < len(tokens):
        run: list[str] = []
        cursor = index
        while cursor < len(tokens):
            word = _strip(tokens[cursor])
            if word in _MULTIPLIERS and cursor + 1 < len(tokens) and _strip(tokens[cursor + 1]) in _DIGIT_WORDS:
                run.append(str(_DIGIT_WORDS[_strip(tokens[cursor + 1])]) * _MULTIPLIERS[word])
                cursor += 2
            elif word in _DIGIT_WORDS:
                run.append(str(_DIGIT_WORDS[word]))
                cursor += 1
            else:
                break
        if sum(len(part) for part in run) >= min_run and cursor - index >= min_run - 1:
            out.append("".join(run))
            index = cursor
        else:
            out.append(tokens[index])
            index += 1
    return " ".join(out)


def normalise_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = ascii_digits(text)
    text = spoken_digits_to_digits(text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def digit_runs(text: str) -> list[tuple[int, int, list[str], str]]:
    """Digit runs in already normalised text: (start, end, groups, joined digits)."""
    runs = []
    for match in _RUN.finditer(text):
        groups = re.findall(r"\d+", match.group(0))
        runs.append((match.start(), match.end(), groups, "".join(groups)))
    return runs


def digit_variants(value: str) -> list[str]:
    digits = re.sub(r"\D", "", ascii_digits(value))
    variants = [digits] if digits else []
    if len(digits) == 12 and digits.startswith("91"):
        variants.append(digits[2:])
    if len(digits) == 11 and digits.startswith("0"):
        variants.append(digits[1:])
    return variants


def is_digit_value(value: str) -> bool:
    digits = re.sub(r"\D", "", ascii_digits(value))
    return len(digits) >= 3 and len(digits) >= 0.6 * len(re.sub(r"[\s\-.+()]", "", value))


def _squash(text: str) -> str:
    return _PUNCT.sub("", normalise_text(text))


def _words(text: str) -> list[str]:
    return [w for w in _PUNCT.sub(" ", normalise_text(text)).split() if w]


def _run_hits(variant: str, groups: list[str], joined: str) -> bool:
    if len(variant) < 6:
        return variant in groups
    return variant in joined


def _digit_value_hit(text_norm: str, value: str) -> bool:
    variants = digit_variants(value)
    for _start, _end, groups, joined in digit_runs(text_norm):
        for variant in variants:
            if _run_hits(variant, groups, joined):
                return True
    return False


def _text_value_hit(text_norm: str, value: str, allowed_norm: str) -> bool:
    value_norm = normalise_text(value)
    if not value_norm:
        return False
    marked = any(ch.isdigit() or ch in "@#" for ch in value_norm) or len(value_norm) >= 12
    if marked:
        squashed = _PUNCT.sub("", value_norm)
        if len(squashed) >= 4 and squashed in _PUNCT.sub("", text_norm):
            return True
    elif len(value_norm) >= 4:
        if re.search(rf"(?<!\w){re.escape(value_norm)}(?!\w)", text_norm):
            return True
    words = _words(value)
    if len(words) >= 3:  # a long value such as an address: two consecutive words of it are a partial leak
        text_words = _words(text_norm)
        for first, second in zip(words, words[1:]):
            if len(first) < 3 or len(second) < 3:
                continue
            if f"{first} {second}" in allowed_norm:
                continue
            if any(a == first and b == second for a, b in zip(text_words, text_words[1:])):
                return True
    return False


def _allowed_digit_sets(allowed_norm: str) -> tuple[set[str], list[str]]:
    groups: set[str] = set()
    joined: list[str] = []
    for _s, _e, parts, whole in digit_runs(allowed_norm):
        groups.update(parts)
        joined.append(whole)
    return groups, joined


def find_values(text: str, values, allowed_text: str = "") -> list[str]:
    """Return the registered values that appear in text. A value that is itself part of the allowed text is ignored.

    `allowed_text` is the allowed values joined with " | "; a registered value that equals one of them is not a leak.
    """
    text_norm = normalise_text(text)
    allowed_norm = normalise_text(allowed_text)
    allowed_groups, allowed_joined = _allowed_digit_sets(allowed_norm)
    found = []
    for value in values:
        value = str(value or "").strip()
        if not value:
            continue
        if is_digit_value(value):
            variants = digit_variants(value)
            if any(v in allowed_groups if len(v) < 6 else any(v in j for j in allowed_joined) for v in variants):
                continue
            if _digit_value_hit(text_norm, value):
                found.append(value)
        else:
            if normalise_text(value) in allowed_norm:
                continue
            if _text_value_hit(text_norm, value, allowed_norm):
                found.append(value)
    return found


def mask_values(text: str, values, placeholder: str = "[withheld]") -> str:
    """Replace every occurrence of the registered values in text. Spoken digit runs are left alone."""
    out = ascii_digits(unicodedata.normalize("NFKC", text))
    for value in values:
        value = str(value or "").strip()
        if not value:
            continue
        if is_digit_value(value):
            variants = digit_variants(value)

            def sub(match: re.Match, variants=variants) -> str:
                groups = re.findall(r"\d+", match.group(0))
                joined = "".join(groups)
                return placeholder if any(_run_hits(v, groups, joined) for v in variants) else match.group(0)

            out = _RUN.sub(sub, out)
        elif len(value) >= 4:
            out = re.sub(re.escape(value), placeholder, out, flags=re.IGNORECASE)
    return out
