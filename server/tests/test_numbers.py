import json
from datetime import date
from pathlib import Path

import pytest

from app.privacy.numbers import extract_amounts, normalize_numbers, parse_date

DATASET = Path(__file__).resolve().parents[2] / "workflows" / "evals" / "datasets" / "normalisation.json"
CASES = json.loads(DATASET.read_text(encoding="utf-8"))


def test_dataset_has_sixty_cases_of_four_kinds():
    assert len(CASES) == 60
    assert {c["kind"] for c in CASES} == {"digits", "quantity", "amount", "date"}


@pytest.mark.parametrize("case", [c for c in CASES if c["kind"] in {"digits", "quantity"}], ids=lambda c: c["id"])
def test_number_runs(case):
    assert normalize_numbers(case["text"]) == case["expect"]


@pytest.mark.parametrize("case", [c for c in CASES if c["kind"] == "amount"], ids=lambda c: c["id"])
def test_amounts(case):
    assert extract_amounts(case["text"]) == case["expect"]


@pytest.mark.parametrize("case", [c for c in CASES if c["kind"] == "date"], ids=lambda c: c["id"])
def test_dates(case):
    parsed = parse_date(case["text"], date.fromisoformat(case["ref"]))
    assert parsed is not None
    assert parsed.value.isoformat() == case["expect"]
    assert parsed.approximate is case["approximate"]


def test_lone_hindi_words_are_not_converted():
    assert normalize_numbers("mujhe refund do") == "mujhe refund do"
    assert normalize_numbers("maine ek phone mangaya") == "maine ek phone mangaya"


def test_lone_word_next_to_rupee_cue_is_converted():
    assert normalize_numbers("do rupaye") == "2 rupaye"


def test_digit_groups_are_not_merged():
    assert normalize_numbers("ZM 11 22 33 44") == "ZM 11 22 33 44"


def test_text_around_a_run_is_kept():
    assert normalize_numbers("amount barah sau hai") == "amount 1200 hai"


def test_devanagari_digits():
    assert normalize_numbers("रिफंड १२०० का") == "रिफंड 1200 का"
