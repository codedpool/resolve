import json
from pathlib import Path

from resolve_workflows.nodes.reconcile import FactView, compare, question_for, reconcile
from resolve_workflows.schemas import FIELDS, ExtractionResult


def said(**values):
    data = {n: {"value": "", "certainty": "not_stated", "original_phrase": "", "ambiguity_note": ""} for n in FIELDS}
    for name, spec in values.items():
        value, certainty = spec if isinstance(spec, tuple) else (spec, "stated")
        data[name] = {"value": value, "certainty": certainty, "original_phrase": value, "ambiguity_note": ""}
    return ExtractionResult.model_validate(data)


def test_values_written_differently_do_not_disagree():
    facts = {"amount": FactView("1200", "stated"), "order_id": FactView("OD 123-456", "stated"), "company_name": FactView("Flipkart", "stated"),
             "desired_remedy": FactView("full refund", "stated")}
    got = said(amount="Rs. 1,200", order_id="od123456", company_name="flip kart", desired_remedy="money back refund")
    assert compare(got, facts) == []


def test_a_normalisation_set_sample_passes_through_reconciliation():
    path = Path(__file__).resolve().parents[1] / "evals" / "datasets" / "normalisation.json"
    amounts = [c for c in json.loads(path.read_text(encoding="utf-8")) if c["kind"] == "amount" and len(c["expect"]) == 1]
    for case in amounts:
        value = str(case["expect"][0])
        assert compare(said(amount=value), {"amount": FactView(value, "stated")}) == []


def test_different_critical_value_is_flagged():
    items = compare(said(amount="900"), {"amount": FactView("9000", "stated")})
    assert [(i.field, i.kind) for i in items] == [("amount", "different_value")]


def test_narration_value_with_no_fact_is_flagged():
    items = compare(said(order_date="2026-11-20"), {})
    assert [(i.field, i.kind) for i in items] == [("order_date", "missing_fact")]


def test_approximate_asserted_as_exact_is_flagged():
    items = compare(said(amount=("1200", "approximate")), {"amount": FactView("1200", "stated")})
    assert [(i.field, i.kind) for i in items] == [("amount", "approximate_as_exact")]
    assert compare(said(amount=("1200", "approximate")), {"amount": FactView("1200", "approximate")}) == []


def test_a_typed_value_the_narration_never_mentioned_is_not_a_disagreement():
    assert compare(said(), {"order_id": FactView("OD1", "stated")}) == []


def test_a_deliberate_correction_is_not_held_against_the_consumer():
    assert compare(said(amount="900"), {"amount": FactView("950", "stated", version=2)}) == []


def test_one_plain_question_per_disagreement():
    item = compare(said(amount="900"), {"amount": FactView("9000", "stated")})[0]
    text = question_for(item)
    assert "900" in text and "9000" in text and text.endswith("Which is right?")


class ScriptedLLM:
    def __init__(self, result):
        self.result = result

    def structured(self, role, prompt_text, variables, schema, mode="instruct"):
        return self.result.model_dump(), {}


def test_reconcile_runs_extraction_then_compares():
    extraction, items = reconcile(ScriptedLLM(said(amount="900")), "text", "2026-11-26", {"amount": FactView("9000", "stated")})
    assert extraction.amount.value == "900" and len(items) == 1
