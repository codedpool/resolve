import pytest

from resolve_workflows import datasets, prompts
from resolve_workflows.evals import run as runner
from resolve_workflows.evals.scoring import score_scenario, values_match
from resolve_workflows.nodes.extract import check, extract_facts
from resolve_workflows.schemas import FIELDS, ExtractionResult, extraction_json_schema


class ScriptedLLM:
    def __init__(self, parsed):
        self.parsed = parsed
        self.seen = []

    def structured(self, role, prompt_text, variables, schema, mode="instruct"):
        self.seen.append((role, prompt_text, variables, schema))
        return self.parsed, {"prompt_tokens": 10, "completion_tokens": 5}


def _fact(value="", certainty="not_stated", phrase="", note=""):
    return {"value": value, "certainty": certainty, "original_phrase": phrase, "ambiguity_note": note}


def _full(**over):
    data = {name: _fact() for name in FIELDS}
    data.update(over)
    return data


def test_schema_is_strict_compatible():
    schema = extraction_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(FIELDS) == set(schema["properties"])
    for prop in schema["properties"].values():
        assert prop["additionalProperties"] is False
        assert set(prop["required"]) == set(prop["properties"])


def test_prompt_is_versioned_and_hashed():
    p = prompts.load("extract_facts")
    assert p.version == 1 and len(p.sha) == 12 and "not_stated" in p.text


def test_node_passes_date_and_text_and_returns_checked_result():
    llm = ScriptedLLM(_full(amount=_fact("Rs. 1,299", "stated"), order_date=_fact("kal", "stated")))
    result, usage, _ = extract_facts(llm, "text here", "2026-11-26")
    assert llm.seen[0][2] == {"narration_date": "2026-11-26", "text": "text here"}
    assert result.amount.value == "1299"
    assert result.order_date.value == "" and result.order_date.certainty == "not_stated"  # not an ISO date
    assert "date not understood" in result.order_date.ambiguity_note
    assert usage["prompt_tokens"] == 10


def test_empty_value_is_always_not_stated_and_value_is_never_not_stated():
    result = check(ExtractionResult.model_validate(_full(company_name=_fact("", "stated"), product=_fact("phone", "not_stated"))))
    assert result.company_name.certainty == "not_stated"
    assert result.product.certainty == "inferred"


def test_approximate_is_kept_as_approximate():
    result = check(ExtractionResult.model_validate(_full(amount=_fact("15000", "approximate", "15000 ke aas paas"))))
    assert result.amount.certainty == "approximate" and result.amount.value == "15000"


def test_value_matching_rules():
    assert values_match("order_id", "OD1234567890", "od 1234567890")
    assert values_match("amount", "10900", "10,900")
    assert values_match("desired_remedy", "full refund", "money back")
    assert values_match("desired_remedy", "replacement or refund", "refund")
    assert not values_match("desired_remedy", "replacement", "refund")
    assert values_match("company_name", "Reliance Digital", "reliance  digital")


def test_scoring_counts_fabrication_on_not_stated_fields():
    scenario = next(s for s in datasets.load("intake") if s["id"] == "in16")  # order id and remedy not stated
    got = ExtractionResult.model_validate(_full(order_id=_fact("AB123", "stated"), company_name=_fact("Amazon", "stated"),
                                                amount=_fact("18000", "stated"), order_date=_fact("2026-11-22", "stated")))
    score = score_scenario(scenario["expect"], got)
    assert score["fabricated"] == 1 and score["not_stated_total"] == 3
    assert score["fields"]["company_name"]["ok"] and score["fields"]["amount"]["ok"] and not score["fields"]["order_id"]["ok"]


def test_approximate_expected_requires_approximate_certainty():
    scenario = next(s for s in datasets.load("intake") if s["id"] == "in11")
    got = ExtractionResult.model_validate(_full(amount=_fact("15000", "stated")))
    assert not score_scenario(scenario["expect"], got)["fields"]["amount"]["ok"]


def test_runner_self_test_runs_all_scenarios_and_respects_the_cost_cap():
    summary = runner.run_intake(runner._SelfTestLLM(), 2, lambda: 0.0, 1.0)
    assert summary["runs"] == 40
    calls = {"n": 0}

    def cost():
        calls["n"] += 1
        return 0.0 if calls["n"] < 4 else 5.0

    with pytest.raises(runner.CostCapReached):
        runner.run_intake(runner._SelfTestLLM(), 1, cost, 1.0)


def test_report_lists_thresholds_and_failures():
    summary = runner.run_intake(runner._SelfTestLLM(), 1, lambda: 0.0, 1.0)
    text = runner.report_markdown("intake_extraction", summary, {"models": "self-test", "cost": 0})
    assert "at least 90%" in text and "at most 2%" in text and "## Failures" in text
