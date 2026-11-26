"""The legal check with a scripted LLM. Nothing here calls a vendor."""

from __future__ import annotations

import pytest

from app.db.models import TagReviewState
from app.legal.verifier import (
    LegalVerifier,
    LlmLegalVerifier,
    NotConfigured,
    VerifyItem,
    WebSearchLegalVerifier,
    build_verifier,
)

TEXT = "No seller offering goods through a marketplace e-commerce entity shall refuse to refund consideration if paid."
MODELS = {"roles": {"legal_tagger": {"model": "qwen/qwen3.8-27b"}, "legal_reviewer": {"model": "openai/gpt-oss-120b"}}}


class ScriptedLLM:
    """Answers the tagger and the reviewer from fixed dictionaries and records every call."""

    def __init__(self, tag=None, review=None, answer=None):
        self.tag = tag or {"tags": ["seller_on_marketplace"], "rationale": "names sellers", "confidence": 0.9}
        self.review = review or {"verdict": "agree", "correct_tags": ["seller_on_marketplace"],
                                 "rationale": "right", "evidence": "No seller offering goods", "confidence": 0.9}
        self.answer = answer or {"verdict": "supports", "rationale": "states it", "evidence": "refuse to refund", "confidence": 0.9}
        self.calls = []

    def structured(self, role, prompt_text, variables, schema, mode="instruct"):
        self.calls.append((role, prompt_text, variables, schema))
        parsed = {"legal_tagger": self.tag}.get(role)
        if parsed is None:
            parsed = self.answer if "question" in variables else self.review
        return parsed, {"prompt_tokens": 1, "completion_tokens": 1}


def _item():
    return VerifyItem("chunk_tags", TEXT, "E-Commerce Rules", "6(3)", "Duties of sellers on marketplace")


def test_both_verifiers_follow_the_interface():
    assert isinstance(LlmLegalVerifier(ScriptedLLM(), MODELS), LegalVerifier)
    assert hasattr(WebSearchLegalVerifier, "verify")


def test_web_search_verifier_is_disabled_and_selecting_it_raises():
    with pytest.raises(NotConfigured):
        WebSearchLegalVerifier()
    with pytest.raises(NotConfigured):
        build_verifier("llm_web", ScriptedLLM(), MODELS)
    assert isinstance(build_verifier("llm", ScriptedLLM(), MODELS), LlmLegalVerifier)
    with pytest.raises(ValueError):
        build_verifier("something_else", ScriptedLLM())


def test_agreement_sets_llm_reviewed_and_never_legal_reviewed():
    llm = ScriptedLLM()
    review = LlmLegalVerifier(llm, MODELS).review_chunk(_item())
    assert review.state is TagReviewState.llm_reviewed
    assert review.tags == ("seller_on_marketplace",)
    assert review.state is not TagReviewState.legal_reviewed


def test_tagger_and_reviewer_use_their_own_roles_and_models_are_recorded():
    llm = ScriptedLLM()
    review = LlmLegalVerifier(llm, MODELS).review_chunk(_item())
    assert [c[0] for c in llm.calls] == ["legal_tagger", "legal_reviewer"]
    assert review.tagger_model == "qwen/qwen3.8-27b" and review.reviewer_model == "openai/gpt-oss-120b"
    assert len(review.prompt_hash.split("+")) == 2
    reviewer_vars = llm.calls[1][2]
    assert reviewer_vars["proposed_tags"] == ["seller_on_marketplace"] and reviewer_vars["text"] == TEXT


def test_disagreement_sets_needs_attention():
    llm = ScriptedLLM(review={"verdict": "disagree", "correct_tags": ["direct_seller"], "rationale": "not sellers",
                              "evidence": "", "confidence": 0.9})
    review = LlmLegalVerifier(llm, MODELS).review_chunk(_item())
    assert review.state is TagReviewState.needs_attention
    assert "reviewer verdict disagree" in review.rationale


def test_low_confidence_sets_needs_attention_even_when_the_reviewer_agrees():
    llm = ScriptedLLM(review={"verdict": "agree", "correct_tags": ["seller_on_marketplace"], "rationale": "maybe",
                              "evidence": "", "confidence": 0.4})
    assert LlmLegalVerifier(llm, MODELS).review_chunk(_item()).state is TagReviewState.needs_attention


def test_agree_verdict_with_different_correct_tags_is_a_disagreement():
    llm = ScriptedLLM(review={"verdict": "agree", "correct_tags": ["marketplace"], "rationale": "x",
                              "evidence": "", "confidence": 0.95})
    assert LlmLegalVerifier(llm, MODELS).review_chunk(_item()).state is TagReviewState.needs_attention


def test_unknown_tag_from_the_tagger_is_dropped_and_flags_the_chunk():
    llm = ScriptedLLM(tag={"tags": ["seller_on_marketplace", "lawyer"], "rationale": "x", "confidence": 0.9})
    review = LlmLegalVerifier(llm, MODELS).review_chunk(_item())
    assert review.tags == ("seller_on_marketplace",)
    assert review.state is TagReviewState.needs_attention


def test_an_invented_evidence_quote_cannot_support_an_agreement():
    llm = ScriptedLLM(review={"verdict": "agree", "correct_tags": ["seller_on_marketplace"], "rationale": "x",
                              "evidence": "sellers must always refund within 7 days", "confidence": 0.95})
    verifier = LlmLegalVerifier(llm, MODELS)
    verdict = verifier.verify(VerifyItem("chunk_tags", TEXT, proposed_tags=("seller_on_marketplace",)))
    assert verdict.verdict == "unsure" and "not a quote" in verdict.rationale
    assert verifier.review_chunk(_item()).state is TagReviewState.needs_attention


def test_empty_tag_list_is_a_valid_general_chunk():
    llm = ScriptedLLM(tag={"tags": [], "rationale": "procedure", "confidence": 0.9},
                      review={"verdict": "agree", "correct_tags": [], "rationale": "ok", "evidence": "", "confidence": 0.9})
    review = LlmLegalVerifier(llm, MODELS).review_chunk(_item())
    assert review.tags == () and review.state is TagReviewState.llm_reviewed


def test_answer_check_maps_supports_partial_unrelated():
    for given, expected in (("supports", "agree"), ("partial", "unsure"), ("unrelated", "disagree")):
        llm = ScriptedLLM(answer={"verdict": given, "rationale": "r", "evidence": "", "confidence": 0.8})
        verdict = LlmLegalVerifier(llm, MODELS).verify(VerifyItem("answer", TEXT, "Rules", "6(3)", question="Can a seller refuse a refund?"))
        assert verdict.verdict == expected
        assert llm.calls[0][0] == "legal_reviewer" and llm.calls[0][2]["question"].startswith("Can a seller")


def test_review_prompts_are_versioned_files():
    from resolve_workflows import prompts

    for name in ("legal_tag_chunk", "legal_review_tags", "legal_review_answer"):
        prompt = prompts.load(name)
        assert prompt.version >= 1 and len(prompt.sha) == 12 and "JSON" in prompt.text
