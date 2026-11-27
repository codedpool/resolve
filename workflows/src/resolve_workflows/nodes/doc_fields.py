"""Deterministic field finder for receipts, invoices and payment screenshots (OCR text in, fields out).

Label-based: a value is only taken when it sits next to a label such as "Order ID" or "Total". Anything
the finder cannot place is left empty, and the caller may then use a model on the redacted text.
"""

from __future__ import annotations

import re

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "जनवरी": 1, "फ़रवरी": 2, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8,
    "सितंबर": 9, "अक्टूबर": 10, "नवंबर": 11, "दिसंबर": 12,
}
_JOINERS = re.compile("[​‌‍]")
_ID_LABEL = re.compile(
    r"(?i)(?:order\s*(?:id|no\.?|number)|reference\s*(?:no\.?|number)|transaction\s*id|invoice\s*(?:no\.?|number)|booking\s*(?:id|reference)|ऑर\S{0,3}डर\s*नंबर)"
    r"\s*[:\-#]?\s*([A-Z0-9][A-Z0-9\-]{5,})"
)
_MONEY = re.compile(r"(?i)(?:₹|rs\.?|inr)\s*([0-9,]+(?:\.[0-9]{1,2})?)")
_AMOUNT_LABEL = re.compile(r"(?i)(?:total|amount|paid|कुल|रा\S{0,3}शा?|राशि)")
_NUMBER = re.compile(r"(?<![\w,.])[₹%०-९]?\s?([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)(?![\w])")
_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9}|[ऀ-ॿ]+)\s+(\d{4})\b")
_SUFFIX = re.compile(r"(?i)\s+(?:retail|pvt|private|ltd|limited|india|online|stores?)\b.*$")


def _clean_id(value: str) -> str:
    return value.strip("-").upper()


def _amounts(text: str) -> list[str]:
    """Candidate amounts in order of trust. A rupee sign is often read as a stray 7, 2 or %, so a labelled number
    that starts with 7 also yields the value without that digit as a second candidate."""
    labelled, marked, loose = [], [], []
    for line in text.splitlines():
        money = list(_MONEY.finditer(line))
        numbers = [m.group(1) for m in _NUMBER.finditer(line)]
        if money:
            (labelled if _AMOUNT_LABEL.search(line) else marked).append(money[-1].group(1))
        elif numbers and _AMOUNT_LABEL.search(line):
            loose.append(numbers[-1])
    ordered = labelled + marked + loose
    out: list[str] = []
    for raw in ordered:
        value = raw.replace(",", "")
        value = value[:-3] if value.endswith(".00") else value
        if value and value not in out:
            out.append(value)
        if raw in loose and value.startswith("7") and len(value) > 2 and value[1:] not in out:
            out.append(value[1:])
    return out


def _date(text: str) -> str:
    best = None
    for match in _DAY_MONTH.finditer(text):
        month = MONTHS.get(match.group(2).lower()[:3]) or MONTHS.get(match.group(2))
        if month:
            best = (int(match.group(3)), month, int(match.group(1)))
            break
    if best is None:
        match = _DMY.search(text)
        if match:
            best = (int(match.group(3)), int(match.group(2)), int(match.group(1)))
    if best is None:
        return ""
    year, month, day = best
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _company(text: str) -> str:
    paid = re.search(r"(?i)paid\s+to\s+([A-Za-z][A-Za-z ]{1,30})", text)
    if paid:
        return paid.group(1).strip()
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 3 and re.search(r"[A-Za-z]{3}", line) and not re.search(r"(?i)payment successful|order|invoice|summary", line):
            return _SUFFIX.sub("", line).strip(" -_.|:;")
    return ""


def find_fields(text: str) -> dict[str, str]:
    return {k: (v[0] if isinstance(v, list) and v else (v if isinstance(v, str) else "")) for k, v in find_candidates(text).items()}


def find_candidates(text: str) -> dict[str, list[str] | str]:
    """Like find_fields, but amount is a list of candidates (best first) so the caller can check each against what
    the consumer confirmed."""
    text = _JOINERS.sub("", text)
    order = _ID_LABEL.search(text)
    return {
        "company_name": _company(text),
        "order_id": _clean_id(order.group(1)) if order else "",
        "amount": _amounts(text),
        "order_date": _date(text),
    }
