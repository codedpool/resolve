"""Legal check (plan 8.5). A tagger model proposes entity-type tags for a chunk, a reviewer from a
different model family checks them against the chunk text. Disagreement or low confidence sets
`needs_attention`, which switches the chunk's retrieval boost off. Nothing here sets
`legal_reviewed`; that state is reserved for a human legal professional."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.config import SERVER_ROOT
from app.db.models import LegalChunk, TagReviewState
from app.legal.chunker import source_titles
from app.legal.quotecheck import normalise

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows import prompts  # noqa: E402

ALLOWED_TAGS = ("marketplace", "seller_on_marketplace", "direct_seller", "payment_intermediary")
LOW_CONFIDENCE = 0.7

TAG_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "tags": {"type": "array", "items": {"type": "string", "enum": list(ALLOWED_TAGS)}},
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["tags", "rationale", "confidence"],
}
REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["agree", "disagree", "unsure"]},
        "correct_tags": {"type": "array", "items": {"type": "string", "enum": list(ALLOWED_TAGS)}},
        "rationale": {"type": "string"},
        "evidence": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["verdict", "correct_tags", "rationale", "evidence", "confidence"],
}
ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["supports", "partial", "unrelated"]},
        "rationale": {"type": "string"},
        "evidence": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["verdict", "rationale", "evidence", "confidence"],
}


class NotConfigured(RuntimeError):
    """Raised when a verifier that is not built yet is selected."""


@dataclass(frozen=True)
class VerifyItem:
    """kind `chunk_tags`: are `proposed_tags` right for `source_text`?
    kind `answer`: does `source_text` answer `question`?"""

    kind: str
    source_text: str
    source: str = ""
    section: str = ""
    heading: str = ""
    proposed_tags: tuple[str, ...] = ()
    question: str = ""


@dataclass(frozen=True)
class LegalVerdict:
    verdict: str  # agree | disagree | unsure
    rationale: str
    confidence: float
    evidence: str = ""
    correct_tags: tuple[str, ...] = ()
    model: str = ""
    prompt_hash: str = ""


@dataclass(frozen=True)
class TagProposal:
    tags: tuple[str, ...]
    rationale: str
    confidence: float
    model: str
    prompt_hash: str
    invalid_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChunkReview:
    tags: tuple[str, ...]
    state: TagReviewState
    rationale: str
    reviewer_confidence: float
    tagger_model: str
    reviewer_model: str
    prompt_hash: str
    reasons: tuple[str, ...] = field(default=())


@runtime_checkable
class LegalVerifier(Protocol):
    def verify(self, item: VerifyItem) -> LegalVerdict: ...


class WebSearchLegalVerifier:
    """Disabled. Selecting it raises NotConfigured."""

    # TODO(developer): decide when web search is added. Groq documents a built-in browser_search
    # tool for gpt-oss models (not combinable with structured outputs):
    # https://console.groq.com/docs/browser-search
    # The hook: after the LLM reviewer agrees, ask a gpt-oss model with browser_search to confirm
    # the claim against the issuing authority's own page, then fold its verdict and the pages it
    # opened into LegalVerdict.evidence. It must run as a separate call because browser search
    # cannot be combined with structured outputs.

    def __init__(self, *args, **kwargs) -> None:
        raise NotConfigured("LEGAL_VERIFIER=llm_web is not implemented yet; use LEGAL_VERIFIER=llm")

    def verify(self, item: VerifyItem) -> LegalVerdict:  # pragma: no cover - never constructed
        raise NotConfigured("web search verification is not implemented")


class LlmLegalVerifier:
    def __init__(self, llm, models: dict | None = None, low_confidence: float = LOW_CONFIDENCE) -> None:
        self.llm = llm
        roles = (models or {}).get("roles", {})
        self.tagger_model = roles.get("legal_tagger", {}).get("model", "legal_tagger")
        self.reviewer_model = roles.get("legal_reviewer", {}).get("model", "legal_reviewer")
        self.low_confidence = low_confidence
        self._tag_prompt = prompts.load("legal_tag_chunk")
        self._review_prompt = prompts.load("legal_review_tags")
        self._answer_prompt = prompts.load("legal_review_answer")

    @property
    def prompt_hash(self) -> str:
        return f"{self._tag_prompt.sha}+{self._review_prompt.sha}"

    def propose_tags(self, item: VerifyItem) -> TagProposal:
        parsed, _usage = self.llm.structured(
            "legal_tagger",
            self._tag_prompt.text,
            {"source": item.source, "heading": item.heading, "section": item.section, "text": item.source_text},
            TAG_SCHEMA,
        )
        raw = [str(t) for t in parsed.get("tags", [])]
        valid = tuple(dict.fromkeys(t for t in raw if t in ALLOWED_TAGS))
        invalid = tuple(t for t in raw if t not in ALLOWED_TAGS)
        return TagProposal(valid, str(parsed.get("rationale", "")), _confidence(parsed), self.tagger_model,
                           self._tag_prompt.sha, invalid)

    def verify(self, item: VerifyItem) -> LegalVerdict:
        if item.kind == "answer":
            return self._verify_answer(item)
        parsed, _usage = self.llm.structured(
            "legal_reviewer",
            self._review_prompt.text,
            {"source": item.source, "heading": item.heading, "section": item.section, "text": item.source_text,
             "proposed_tags": list(item.proposed_tags)},
            REVIEW_SCHEMA,
        )
        verdict = str(parsed.get("verdict", "unsure"))
        if verdict not in ("agree", "disagree", "unsure"):
            verdict = "unsure"
        correct = tuple(t for t in parsed.get("correct_tags", []) if t in ALLOWED_TAGS)
        return self._checked(item, LegalVerdict(verdict, str(parsed.get("rationale", "")), _confidence(parsed),
                                                 str(parsed.get("evidence", "")), correct, self.reviewer_model,
                                                 self._review_prompt.sha))

    def _verify_answer(self, item: VerifyItem) -> LegalVerdict:
        parsed, _usage = self.llm.structured(
            "legal_reviewer",
            self._answer_prompt.text,
            {"question": item.question, "chunk": {"source": item.source, "section": item.section, "text": item.source_text}},
            ANSWER_SCHEMA,
        )
        mapped = {"supports": "agree", "partial": "unsure", "unrelated": "disagree"}.get(str(parsed.get("verdict")), "unsure")
        return self._checked(item, LegalVerdict(mapped, str(parsed.get("rationale", "")), _confidence(parsed),
                                                 str(parsed.get("evidence", "")), (), self.reviewer_model,
                                                 self._answer_prompt.sha))

    def _checked(self, item: VerifyItem, verdict: LegalVerdict) -> LegalVerdict:
        """Evidence must be a real quote. An invented quote cannot support an agreement."""
        if verdict.evidence and normalise(verdict.evidence) not in normalise(item.source_text):
            note = "evidence is not a quote from the source text"
            return LegalVerdict("unsure" if verdict.verdict == "agree" else verdict.verdict,
                                f"{verdict.rationale} [{note}]".strip(), min(verdict.confidence, 0.5), "",
                                verdict.correct_tags, verdict.model, verdict.prompt_hash)
        return verdict

    def review_chunk(self, item: VerifyItem) -> ChunkReview:
        proposal = self.propose_tags(item)
        verdict = self.verify(VerifyItem("chunk_tags", item.source_text, item.source, item.section, item.heading,
                                         proposal.tags))
        reasons = []
        if proposal.invalid_tags:
            reasons.append(f"tagger proposed unknown tags {list(proposal.invalid_tags)}")
        if verdict.verdict != "agree":
            reasons.append(f"reviewer verdict {verdict.verdict}")
        if set(verdict.correct_tags) != set(proposal.tags):
            reasons.append("reviewer would assign different tags")
        if min(proposal.confidence, verdict.confidence) < self.low_confidence:
            reasons.append("low confidence")
        state = TagReviewState.needs_attention if reasons else TagReviewState.llm_reviewed
        rationale = f"tagger: {proposal.rationale} | reviewer: {verdict.rationale}"
        if reasons:
            rationale += " | " + "; ".join(reasons)
        return ChunkReview(proposal.tags, state, rationale, verdict.confidence, proposal.model, verdict.model,
                           self.prompt_hash, tuple(reasons))


def _confidence(parsed: dict) -> float:
    try:
        return max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
    except (TypeError, ValueError):
        return 0.0


def build_verifier(setting: str, llm, models: dict | None = None) -> LegalVerifier:
    """LEGAL_VERIFIER = llm | llm_web. llm_web raises NotConfigured until web search is built."""
    if setting == "llm":
        return LlmLegalVerifier(llm, models)
    if setting == "llm_web":
        return WebSearchLegalVerifier()
    raise ValueError(f"LEGAL_VERIFIER must be llm or llm_web, got {setting!r}")


def item_for_chunk(row: LegalChunk, source_title: str = "") -> VerifyItem:
    return VerifyItem("chunk_tags", row.text, source_title or row.source_id, f"{row.section}{row.clause}", row.heading)


def apply_review(row: LegalChunk, review: ChunkReview) -> None:
    """Store a review on a chunk row. The row's old tags are replaced by the proposal."""
    row.entity_type_tags = list(review.tags)
    row.tag_review_state = review.state
    row.review_rationale = review.rationale
    row.reviewer_confidence = review.reviewer_confidence
    row.tagger_model = review.tagger_model
    row.reviewer_model = review.reviewer_model
    row.prompt_hash = review.prompt_hash


def review_rows(session, verifier: LlmLegalVerifier, rows, on_review=None) -> list[ChunkReview]:
    """Tag and review each chunk row, store the result on the row, and return the reviews in order."""
    titles = source_titles()
    reviews = []
    for row in rows:
        review = verifier.review_chunk(item_for_chunk(row, titles.get(row.source_id, "")))
        apply_review(row, review)
        session.flush()
        reviews.append(review)
        if on_review:
            on_review(row, review)
    return reviews
