"""Finding and ranking complaint contacts on a company's pages. No model is used: the evidence is the page text."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\d])(?:\+?91[\s-]?)?(?:1800[\s-]?\d{3}[\s-]?\d{4}|[6-9]\d{9})(?![\d])")
GRIEVANCE = re.compile(r"(?i)grievance|nodal|appellate")
CARE = re.compile(r"(?i)customer care|customer support|help|support|contact")
CONFIDENCE_MARGIN = 2.0


@dataclass(frozen=True)
class Page:
    url: str
    text: str  # plain text, headings on their own lines
    official: bool


@dataclass
class Candidate:
    kind: str  # email | phone
    value: str
    role: str  # grievance | customer_care | other
    url: str
    official: bool
    score: float = 0.0
    snippet: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip = True
        if tag in {"h1", "h2", "h3", "p", "li", "div", "br", "tr"}:
            self.lines.append("")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip = False

    def handle_data(self, data):
        if not self._skip and data.strip():
            if not self.lines:
                self.lines.append("")
            self.lines[-1] += data.strip() + " "


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(re.sub(r"<!--.*?-->", "", html, flags=re.S))
    return "\n".join(line.strip() for line in parser.lines if line.strip())


def _normal(kind: str, value: str) -> str:
    return value.lower() if kind == "email" else re.sub(r"[^\d+]", "", value)


def extract(page: Page, domain: str) -> list[Candidate]:
    out: list[Candidate] = []
    heading = ""
    for line in page.text.splitlines():
        if len(line) < 60 and not _EMAIL.search(line) and not _PHONE.search(line):
            heading = line
        context = f"{heading} {line}"
        role = "grievance" if GRIEVANCE.search(context) else "customer_care" if CARE.search(context) else "other"
        for match in _EMAIL.finditer(line):
            out.append(Candidate("email", match.group(0), role, page.url, page.official, snippet=line[:120]))
        for match in _PHONE.finditer(line):
            out.append(Candidate("phone", match.group(0).strip(), role, page.url, page.official, snippet=line[:120]))
    for cand in out:
        cand.score = _score(cand, domain)
    return out


def _score(cand: Candidate, domain: str) -> float:
    score = 3.0 if cand.official else 0.5
    score += {"grievance": 3.0, "customer_care": 1.5, "other": 0.0}[cand.role]
    if cand.kind == "email" and cand.value.lower().endswith("@" + domain):
        score += 2.0
    return score


def rank(candidates: list[Candidate], rejected: list[str] | None = None) -> list[Candidate]:
    """Merge repeats (a value on two pages gets a small bonus) and sort best first."""
    gone = {_normal("email", v) for v in (rejected or [])} | {_normal("phone", v) for v in (rejected or [])}
    merged: dict[tuple[str, str], Candidate] = {}
    for cand in candidates:
        key = (cand.kind, _normal(cand.kind, cand.value))
        if key[1] in gone:
            continue
        if key in merged:
            merged[key].score = max(merged[key].score, cand.score) + 1.0
        else:
            merged[key] = cand
    return sorted(merged.values(), key=lambda c: c.score, reverse=True)


def confident(ranked: list[Candidate]) -> bool:
    """One clear winner: official, a grievance or care contact, and well ahead of every other value of the same kind."""
    if not ranked:
        return False
    top = ranked[0]
    if not top.official or top.role == "other":
        return False
    rivals = [c for c in ranked[1:] if c.kind == top.kind]
    if not rivals or top.score - rivals[0].score >= CONFIDENCE_MARGIN:
        return True
    # The company's own grievance contact beats its general customer-care contacts, even by a short margin.
    return top.role == "grievance" and all(c.role != "grievance" or not c.official for c in rivals)
