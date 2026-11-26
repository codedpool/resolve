"""Grounded answers: every rule claim cites a retrieved chunk, or the agent says it does not know.

The model writes the statements; code decides whether they may be said. Code builds the citations,
adds the "AI-checked, not legal advice" wording and rejects anything that states a rule, deadline or
penalty without a retrieved source. The agent never claims to be a lawyer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from resolve_workflows import prompts

DISCLAIMER = "AI-checked, not legal advice"
LEGAL_REVIEWED = "legal_reviewed"

ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answerable": {"type": "boolean"},
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": ["rule", "general"]},
                    "cites": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "kind", "cites"],
            },
        },
        "clarifying_question": {"type": "string"},
    },
    "required": ["answerable", "statements", "clarifying_question"],
}

_UNKNOWN = {
    "en": "I do not know the answer to that from the sources I have.",
    "hi": "मेरे पास मौजूद स्रोतों से मुझे इसका उत्तर नहीं पता।",
    "hinglish": "Mere paas jo sources hain unse mujhe iska jawab nahi pata.",
}
_ASK = {
    "en": "Could you tell me a little more about what happened, for example what you bought and what the company told you?",
    "hi": "क्या आप थोड़ा और बता सकते हैं कि क्या हुआ, जैसे आपने क्या खरीदा और कंपनी ने क्या कहा?",
    "hinglish": "Kya aap thoda aur bata sakte hain ki kya hua, jaise aapne kya kharida aur company ne kya kaha?",
}
_DISCLAIMER_LINE = {
    "en": f"This is {DISCLAIMER}.",
    "hi": f"यह एआई द्वारा जाँचा गया है, कानूनी सलाह नहीं ({DISCLAIMER}).",
    "hinglish": f"Yeh AI se jaanchi gayi jaankari hai: {DISCLAIMER}.",
}
_SOURCE = {"en": "source", "hi": "स्रोत", "hinglish": "source"}

_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_WORD_PATTERN = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_NUMBER_TOKEN = re.compile(rf"(?<![A-Za-z])(?:(?:{_WORD_PATTERN})(?:[- ](?:{_WORD_PATTERN}))?)(?![A-Za-z])|\d+", re.I)
_TIME_UNIT = (
    r"(?:hours?|days?|weeks?|months?|years?|working days|"
    r"घंटे|घण्टे|दिन|हफ्ते|हफ़्ते|सप्ताह|महीने|महीना|माह|साल|वर्ष|"
    r"ghante|ghanta|din|hafte|mahine|mahina|saal|varsh)"
)
_DEADLINE = re.compile(rf"(?:(?:{_WORD_PATTERN})(?:[- ](?:{_WORD_PATTERN}))?|\d+)\s*{_TIME_UNIT}\b", re.I)
_THREAT = re.compile(
    r"\b(?:court|sue|suing|lawsuit|legal action|prosecut\w*|imprison\w*|jail|penalt\w*|fine of|punish\w*|criminal|"
    r"jurmana|saza|mukadma|kanooni karwai)\b|अदालत|कोर्ट|मुकदमा|जेल|कारावास|जुर्माना|दंड|सज़ा|सजा|कानूनी कार्रवाई|कार्यवाही",
    re.I,
)
_LAWYER_CLAIM = re.compile(r"(?:i am|i'm|as your|as a)\s+(?:a\s+)?(?:lawyer|advocate|attorney)|मैं (?:एक )?वकील|main vakeel", re.I)
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


@dataclass
class Citation:
    chunk_id: str
    label: str
    source_url: str
    section: str
    layer: str
    review_state: str
    fetched_at: str = ""


@dataclass
class AnswerResult:
    kind: str  # grounded | unknown
    text: str
    citations: list[Citation] = field(default_factory=list)
    disclaimer: bool = False
    question: str = ""
    problems: list[str] = field(default_factory=list)
    attempts: int = 0
    usage: list[dict] = field(default_factory=list)
    prompt_hash: str = ""


def numbers_in(text: str) -> set[int]:
    """Integers written as digits (ASCII or Devanagari) or English number words."""
    found: set[int] = set()
    for token in _NUMBER_TOKEN.findall(text.translate(_DEVANAGARI_DIGITS)):
        token = token.lower()
        if token.isdigit():
            found.add(int(token))
            continue
        parts = re.split(r"[- ]", token)
        found.add(sum(_NUMBER_WORDS[p] for p in parts if p in _NUMBER_WORDS))
    return found


def _label(chunk) -> str:
    title = getattr(chunk, "source_title", "") or chunk.layer
    return f"{title}, section {chunk.section}{getattr(chunk, 'clause', '')}".strip()


def _unknown(language: str, question: str = "", problems: list[str] | None = None, attempts: int = 0) -> AnswerResult:
    ask = question.strip() or _ASK[language]
    return AnswerResult("unknown", f"{_UNKNOWN[language]} {ask}", question=ask, problems=problems or [], attempts=attempts)


def validate(parsed: dict, chunks: list) -> list[str]:
    """Return the reasons the model's answer may not be said. Empty list means it passes."""
    problems: list[str] = []
    by_id = {c.id: c for c in chunks}
    if not isinstance(parsed.get("answerable"), bool):
        return ["answerable must be true or false"]
    question = str(parsed.get("clarifying_question", "")).strip()
    statements = parsed.get("statements") or []
    if not parsed["answerable"]:
        if statements:
            problems.append("an unanswerable question must have no statements")
        if not question:
            problems.append("an unanswerable question needs one clarifying question")
        if question.count("?") > 1:
            problems.append("ask exactly one question")
        return problems
    if not statements:
        return ["an answerable question needs at least one statement"]
    if question:
        problems.append("an answered question must not also ask a question")
    for index, statement in enumerate(statements, start=1):
        text = str(statement.get("text", "")).strip()
        kind = statement.get("kind")
        cites = list(statement.get("cites") or [])
        tag = f"statement {index}"
        if not text:
            problems.append(f"{tag} is empty")
            continue
        unknown_ids = [c for c in cites if c not in by_id]
        if unknown_ids:
            problems.append(f"{tag} cites an id that was not retrieved: {unknown_ids}")
        if kind == "rule" and not cites:
            problems.append(f"{tag} states a rule without citing a retrieved chunk")
        legal_claim = bool(_DEADLINE.search(text) or _THREAT.search(text))
        if legal_claim and (kind != "rule" or not cites):
            problems.append(f"{tag} states a legal threat, penalty or deadline without a source")
        if cites and not unknown_ids:
            source_numbers: set[int] = set()
            for cite in cites:
                source_numbers |= numbers_in(by_id[cite].text)
            unsupported = numbers_in(text) - source_numbers
            if unsupported:
                problems.append(f"{tag} uses numbers that are not in the cited text: {sorted(unsupported)}")
        if _LAWYER_CLAIM.search(text):
            problems.append(f"{tag} claims to be a lawyer")
    if not any(s.get("kind") == "rule" for s in statements):
        problems.append("an answer must contain at least one cited rule statement")
    return problems


def _assemble(parsed: dict, chunks: list, language: str) -> AnswerResult:
    by_id = {c.id: c for c in chunks}
    cited: list = []
    sentences = []
    for statement in parsed["statements"]:
        text = statement["text"].strip()
        labels = []
        for cite in statement["cites"]:
            chunk = by_id[cite]
            if chunk not in cited:
                cited.append(chunk)
            label = _label(chunk)
            if label not in labels:
                labels.append(label)
        if labels:
            text = f"{text} [{_SOURCE[language]}: {'; '.join(labels)}]"
        sentences.append(text)
    needs_disclaimer = any(c.review_state != LEGAL_REVIEWED for c in cited)
    if needs_disclaimer:
        sentences.append(_DISCLAIMER_LINE[language])
    citations = [
        Citation(c.id, _label(c), c.source_url, c.section, c.layer, c.review_state, getattr(c, "fetched_at", ""))
        for c in cited
    ]
    return AnswerResult("grounded", " ".join(sentences), citations, needs_disclaimer)


def answer_with_citations(
    llm,
    retriever,
    question: str,
    *,
    entity_type: str | None = None,
    language: str | None = None,
    k: int = 4,
    role: str = "draft",
    max_attempts: int = 2,
) -> AnswerResult:
    """Retrieve, ask the model for cited statements, validate, and assemble the spoken answer."""
    if language is None:  # a question written in Devanagari takes the Hindi path
        language = "hi" if re.search("[ऀ-ॿ]", question) else "en"
    if language not in _UNKNOWN:
        language = "en"
    chunks = list(retriever.search(question, entity_type, k))
    if not chunks:
        return _unknown(language)
    prompt = prompts.load("answer_with_citations")
    variables = {
        "question": question,
        "language": language,
        "chunks": [{"id": c.id, "source": _label(c).split(", section")[0], "section": f"{c.section}{getattr(c, 'clause', '')}",
                    "text": c.text} for c in chunks],
    }
    problems: list[str] = []
    usages: list[dict] = []
    for attempt in range(1, max_attempts + 1):
        call_vars = dict(variables)
        if problems:
            call_vars["fix_these_problems"] = problems
        parsed, usage = llm.structured(role, prompt.text, call_vars, ANSWER_SCHEMA)
        usages.append(usage)
        problems = validate(parsed, chunks)
        if not problems:
            if not parsed["answerable"]:
                result = _unknown(language, parsed.get("clarifying_question", ""), attempts=attempt)
            else:
                result = _assemble(parsed, chunks, language)
                result.attempts = attempt
            result.usage, result.prompt_hash = usages, prompt.sha
            return result
    result = _unknown(language, problems=problems, attempts=max_attempts)
    result.usage, result.prompt_hash = usages, prompt.sha
    return result
