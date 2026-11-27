"""answer_with_citations with a scripted LLM and a fake retriever."""

from __future__ import annotations

from dataclasses import dataclass

from resolve_workflows import prompts
from resolve_workflows.nodes.answer import DISCLAIMER, answer_with_citations, numbers_in, validate


@dataclass
class FakeChunk:
    id: str
    text: str
    layer: str = "rules"
    source_url: str = "https://example.test/rules"
    section: str = "4"
    review_state: str = "unreviewed"
    source_title: str = "Consumer Protection (E-Commerce) Rules, 2020"
    clause: str = "(5)"
    fetched_at: str = "2026-11-26"


GRIEVANCE = FakeChunk(
    "c-1",
    "(5) Every e-commerce entity shall ensure that the grievance officer acknowledges the receipt of any "
    "consumer complaint within forty-eight hours and redresses the complaint within one month.",
)
REFUND = FakeChunk("c-2", "(3) No seller shall refuse to refund consideration, if paid, if goods are defective.",
                   section="6", clause="(3)")


class FakeRetriever:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def search(self, query, entity_type=None, k=5):
        self.calls.append((query, entity_type, k))
        return self.chunks[:k]


class ScriptedLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def structured(self, role, prompt_text, variables, schema, mode="instruct"):
        self.calls.append((role, variables))
        return self.replies.pop(0), {"prompt_tokens": 1, "completion_tokens": 1}


def _reply(statements, answerable=True, question=""):
    return {"answerable": answerable, "statements": statements, "clarifying_question": question}


def _rule(text, *cites):
    return {"text": text, "kind": "rule", "cites": list(cites)}


GOOD = _reply([_rule("The grievance officer must acknowledge your complaint within 48 hours.", "c-1")])


def test_grounded_answer_cites_the_chunk_and_carries_the_disclaimer():
    result = answer_with_citations(ScriptedLLM(GOOD), FakeRetriever([GRIEVANCE, REFUND]), "How fast must they reply?")
    assert result.kind == "grounded"
    assert [c.chunk_id for c in result.citations] == ["c-1"]
    assert "Consumer Protection (E-Commerce) Rules, 2020, section 4(5)" in result.text
    assert DISCLAIMER in result.text and result.disclaimer
    assert result.citations[0].source_url == "https://example.test/rules" and result.citations[0].review_state == "unreviewed"


def test_no_disclaimer_when_every_cited_source_is_legal_reviewed():
    reviewed = FakeChunk("c-1", GRIEVANCE.text, review_state="legal_reviewed")
    result = answer_with_citations(ScriptedLLM(GOOD), FakeRetriever([reviewed]), "How fast must they reply?")
    assert result.kind == "grounded" and not result.disclaimer and DISCLAIMER not in result.text


def test_disclaimer_is_added_if_any_cited_source_is_not_legal_reviewed():
    reviewed = FakeChunk("c-1", GRIEVANCE.text, review_state="legal_reviewed")
    reply = _reply([_rule("A seller must refund a defective item.", "c-2"), _rule("Acknowledge within 48 hours.", "c-1")])
    result = answer_with_citations(ScriptedLLM(reply), FakeRetriever([reviewed, REFUND]), "q")
    assert result.disclaimer and DISCLAIMER in result.text


def test_validator_rejects_a_rule_without_a_retrieved_chunk_id():
    assert any("without citing" in p for p in validate(_reply([_rule("Sellers must refund.")]), [GRIEVANCE]))
    assert any("not retrieved" in p for p in validate(_reply([_rule("Sellers must refund.", "made-up")]), [GRIEVANCE]))
    assert validate(GOOD, [GRIEVANCE]) == []


def test_rejected_answer_is_retried_once_with_the_problems_then_accepted():
    bad = _reply([_rule("Sellers must refund.")])
    llm = ScriptedLLM(bad, GOOD)
    result = answer_with_citations(llm, FakeRetriever([GRIEVANCE]), "q")
    assert result.kind == "grounded" and result.attempts == 2
    assert "fix_these_problems" in llm.calls[1][1] and "fix_these_problems" not in llm.calls[0][1]


def test_two_rejected_answers_end_in_an_honest_unknown_not_an_uncited_claim():
    bad = _reply([_rule("Sellers must refund.")])
    result = answer_with_citations(ScriptedLLM(bad, bad), FakeRetriever([GRIEVANCE]), "q")
    assert result.kind == "unknown" and not result.citations and result.problems
    assert "I do not know" in result.text and result.text.count("?") == 1


def test_nothing_retrieved_means_i_do_not_know_and_one_question_without_calling_the_model():
    llm = ScriptedLLM()
    result = answer_with_citations(llm, FakeRetriever([]), "What is the weather?")
    assert result.kind == "unknown" and "I do not know" in result.text and result.text.count("?") == 1
    assert llm.calls == [] and result.question and not result.citations


def test_model_can_say_it_cannot_answer_and_ask_one_question():
    reply = _reply([], answerable=False, question="Which company is this about?")
    result = answer_with_citations(ScriptedLLM(reply), FakeRetriever([GRIEVANCE]), "q")
    assert result.kind == "unknown" and result.question == "Which company is this about?"
    assert result.text.endswith("Which company is this about?")


def test_two_questions_are_rejected():
    reply = _reply([], answerable=False, question="Which company? What did you buy?")
    assert any("exactly one question" in p for p in validate(reply, [GRIEVANCE]))


def test_a_deadline_without_a_source_is_rejected_even_if_labelled_general():
    general = {"text": "You have 30 days to complain.", "kind": "general", "cites": []}
    problems = validate(_reply([_rule("Acknowledge within 48 hours.", "c-1"), general]), [GRIEVANCE])
    assert any("without a source" in p for p in problems)


def test_a_legal_threat_without_a_source_is_rejected():
    threat = {"text": "Tell them you will take them to court.", "kind": "general", "cites": []}
    problems = validate(_reply([_rule("Acknowledge within 48 hours.", "c-1"), threat]), [GRIEVANCE])
    assert any("without a source" in p for p in problems)


def test_a_number_that_is_not_in_the_cited_text_is_rejected():
    wrong = _reply([_rule("The grievance officer must acknowledge within 24 hours.", "c-1")])
    assert any("numbers that are not in the cited text" in p for p in validate(wrong, [GRIEVANCE]))
    assert validate(_reply([_rule("Redress within one month, acknowledge within 48 hours.", "c-1")]), [GRIEVANCE]) == []


def test_claiming_to_be_a_lawyer_is_rejected():
    reply = _reply([_rule("As your lawyer I say they must acknowledge within 48 hours.", "c-1")])
    assert any("lawyer" in p for p in validate(reply, [GRIEVANCE]))


def test_an_answer_needs_at_least_one_cited_rule():
    only_general = _reply([{"text": "Keep your receipts.", "kind": "general", "cites": []}])
    assert any("at least one cited rule" in p for p in validate(only_general, [GRIEVANCE]))


def test_number_extraction_reads_words_digits_and_devanagari_digits():
    assert numbers_in("within forty-eight hours and one month") == {48, 1}
    assert numbers_in("48 घंटे और ३० दिन") == {48, 30}


def test_hindi_question_gets_a_grounded_hindi_answer_with_the_disclaimer():
    reply = _reply([_rule("शिकायत अधिकारी को 48 घंटे के भीतर आपकी शिकायत की पावती देनी होगी।", "c-1")])
    llm = ScriptedLLM(reply)
    retriever = FakeRetriever([GRIEVANCE])
    result = answer_with_citations(llm, retriever, "शिकायत अधिकारी कितने घंटे में पावती देगा?", language="hi")
    assert result.kind == "grounded" and "पावती" in result.text and "स्रोत:" in result.text
    assert DISCLAIMER in result.text and "कानूनी सलाह नहीं" in result.text
    assert llm.calls[0][1]["language"] == "hi" and retriever.calls[0][0].startswith("शिकायत")


def test_hindi_deadline_without_a_source_is_rejected_and_hindi_unknown_has_one_question():
    problems = validate(_reply([_rule("आपको 30 दिन में शिकायत करनी होगी।", "c-1")]), [GRIEVANCE])
    assert any("numbers that are not in the cited text" in p for p in problems)
    general = {"text": "आप 30 दिन में शिकायत करें।", "kind": "general", "cites": []}
    assert any("without a source" in p for p in validate(_reply([_rule("48 घंटे।", "c-1"), general]), [GRIEVANCE]))
    result = answer_with_citations(ScriptedLLM(), FakeRetriever([]), "मौसम कैसा है?", language="hi")
    assert result.kind == "unknown" and "मुझे इसका उत्तर नहीं पता" in result.text and result.text.count("?") == 1


def test_entity_type_is_passed_to_the_retriever_and_the_role_is_the_draft_role():
    llm = ScriptedLLM(GOOD)
    retriever = FakeRetriever([GRIEVANCE])
    answer_with_citations(llm, retriever, "q", entity_type="marketplace", k=3)
    assert retriever.calls == [("q", "marketplace", 3)] and llm.calls[0][0] == "draft"


def test_prompt_is_a_versioned_file_with_the_citation_rule():
    prompt = prompts.load("answer_with_citations")
    assert prompt.version >= 1 and "cites" in prompt.text and len(prompt.sha) == 12


def test_language_defaults_from_the_script_of_the_question():
    llm = ScriptedLLM(GOOD, GOOD)
    answer_with_citations(llm, FakeRetriever([GRIEVANCE]), "शिकायत की समय सीमा क्या है?")
    answer_with_citations(llm, FakeRetriever([GRIEVANCE]), "What is the time limit?")
    assert [c[1]["language"] for c in llm.calls] == ["hi", "en"]
