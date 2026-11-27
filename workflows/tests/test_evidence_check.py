from datetime import date

import pytest

from resolve_workflows.nodes.evidence_check import (
    CaseEvidence, Credit, amounts_in, check_case_evidence, dates_in, normalise_amount, normalise_reference, references_in,
    spoken_to_digits,
)

TODAY = date(2026, 11, 17)
OWED = CaseEvidence(paid_amount="4999", order_date="2026-11-12", order_id="OD43817265")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("twelve hundred rupees", [1200]),
        ("Rs. 1,200", [1200]),
        ("₹1200", [1200]),
        ("1,200 rupees", [1200]),
        ("four thousand nine hundred ninety nine rupees", [4999]),
        ("the refund of 4999 was processed", [4999]),
        ("paanch hazaar rupaye ka voucher", [5000]),
        ("do hazaar rupaye", [2000]),
        ("तीन हज़ार रुपये", [3000]),
        ("Rs 4,999.00", [4999]),
        ("I can do three thousand rupees today", [3000]),
        ("refund two thousand rupees as a final settlement", [2000]),
    ],
)
def test_amounts_are_normalised_before_they_are_compared(text, expected):
    assert amounts_in(text) == expected


@pytest.mark.parametrize(
    "text",
    ["on the twentieth of November", "call 1800 555 0142 for the refund desk", "ticket ZM-TKT-90417", "in 48 hours", "OD43817265", "on 15 November 2026"],
)
def test_dates_codes_and_phone_numbers_are_not_amounts(text):
    assert amounts_in(text) == []


def test_twelve_hundred_and_1200_are_the_same_value():
    assert amounts_in("twelve hundred") == [] or amounts_in("twelve hundred rupees") == amounts_in("Rs. 1,200")
    assert normalise_amount("1,200") == normalise_amount("twelve hundred rupees") == "1200"
    assert spoken_to_digits("twelve hundred") == "1200"


def test_a_lone_hindi_word_that_means_give_is_left_alone():
    assert spoken_to_digits("aap mujhe de do") == "aap mujhe de do"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("by the twentieth of November", ["2026-11-20"]),
        ("will be credited by twenty first November", ["2026-11-21"]),
        ("on 15 November", ["2026-11-15"]),
        ("November 15th, 2026", ["2026-11-15"]),
        ("2026-11-20", ["2026-11-20"]),
        ("20/11/2026", ["2026-11-20"]),
        ("das November ko", ["2026-11-10"]),
        ("the fifteenth of November", ["2026-11-15"]),
        ("no date here", []),
    ],
)
def test_dates_are_normalised(text, expected):
    assert dates_in(text, TODAY) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("My reference for this is ZM-REF-558201.", ["ZMREF558201"]),
        ("ticket ZM-TKT-90417 for order OD43817265", ["ZMTKT90417", "OD43817265"]),
        ("reference number 558201", ["558201"]),
        ("the follow-up is done", []),
    ],
)
def test_references_are_normalised(text, expected):
    assert references_in(text) == expected


def test_reference_spelling_does_not_matter():
    assert normalise_reference("zm-ref 558201") == normalise_reference("ZM-REF-558201")


def test_a_refund_claim_with_no_evidence_of_receipt_is_missing():
    verdict = check_case_evidence("the refund of four thousand nine hundred ninety nine rupees was processed on the fifteenth of November", OWED, TODAY)
    assert verdict.overall == "missing"
    assert verdict.get("amount_received").verdict == "missing"
    assert verdict.get("amount_owed").verdict == "match"
    assert verdict.get("date").claimed == "2026-11-15"


def test_a_claim_with_the_wrong_amount_is_a_mismatch_against_what_is_owed():
    verdict = check_case_evidence("we refunded two thousand rupees", OWED, TODAY)
    assert verdict.overall == "mismatch"
    assert verdict.get("amount_owed").verdict == "mismatch"


def test_a_claim_that_matches_a_credit_on_the_consumers_own_statement_matches():
    evidence = CaseEvidence("4999", "2026-11-12", "OD43817265", credits=(Credit("4,999.00", "2026-11-15", "ZM-REF-1"),))
    verdict = check_case_evidence("refund of 4999 was credited on 15 November, reference ZM-REF-1", evidence, TODAY)
    assert verdict.overall == "match"


def test_a_credit_on_another_date_is_a_mismatch():
    evidence = CaseEvidence("4999", "2026-11-12", "OD43817265", credits=(Credit("4999", "2026-11-16"),))
    verdict = check_case_evidence("credited on 15 November", evidence, TODAY)
    assert verdict.overall == "mismatch" and verdict.get("date").verdict == "mismatch"


def test_the_order_id_is_not_treated_as_a_refund_reference():
    verdict = check_case_evidence("it is for order OD43817265", OWED, TODAY)
    assert verdict.claim.references == ()


def test_a_reference_that_differs_from_the_one_the_consumer_holds_is_a_mismatch():
    evidence = CaseEvidence("4999", known_references=("ZM-REF-1",))
    assert check_case_evidence("reference ZM-REF-2", evidence, TODAY).overall == "mismatch"
    assert check_case_evidence("reference zm ref 1 is ZMREF1", evidence, TODAY).overall != "mismatch"


def test_a_spoken_number_normaliser_from_the_server_can_be_plugged_in():
    seen = []

    def shout(text):
        seen.append(text)
        return text.replace("fifty", "50")

    check_case_evidence("refund of fifty rupees", OWED, TODAY, normalise=shout)
    assert seen
