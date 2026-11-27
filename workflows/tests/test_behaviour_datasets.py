import copy

from resolve_workflows import datasets


def test_all_new_sets_validate():
    problems = {k: v for k, v in datasets.validate_all().items() if v}
    assert problems == {}


def test_counts():
    assert len(datasets.load_behaviours()) == 15
    assert len(datasets.load_adversarial()) >= 10
    assert len(datasets.load_safety_suite()["cases"]) >= 12
    assert datasets.load_redteam()["id"]


def test_every_behaviour_is_covered_once():
    kinds = [c["behaviour"] for c in datasets.load_behaviours()]
    assert sorted(kinds) == sorted(datasets.BEHAVIOURS)


def test_cards_use_the_known_vocabulary():
    for card in datasets.load_behaviours() + datasets.load_adversarial():
        assert card["expect"]["outcome"] in datasets.OUTCOMES
        assert set(card["forbidden"]) <= datasets.FORBIDDEN


def test_safety_suite_has_a_canary_for_every_sensitive_field_and_a_case_that_leaks_it():
    suite = datasets.load_safety_suite()
    assert set(datasets.SENSITIVE_FIELDS) <= set(suite["fixture"]["canaries"])
    leaked = {f for c in suite["cases"] for f in c["canary_fields"]}
    assert set(datasets.SENSITIVE_FIELDS) <= leaked
    assert {c["category"] for c in suite["cases"]} == datasets.SAFETY_CATEGORIES


def test_no_canary_is_on_the_disclosure_list():
    fixture = datasets.load_safety_suite()["fixture"]
    assert not set(fixture["canaries"]) & set(fixture["disclosure_list"])


def test_validator_catches_a_missing_canary_and_a_short_suite():
    suite = copy.deepcopy(datasets.load_safety_suite())
    del suite["fixture"]["canaries"]["cvv"]
    suite["cases"] = suite["cases"][:5]
    errors = datasets.validate_safety(suite)
    assert any("no canary for cvv" in e for e in errors)
    assert any("need 12" in e for e in errors)


def test_validator_catches_a_leaked_sentence_in_the_held_out_set():
    cards = copy.deepcopy(datasets.load_adversarial())
    cards[0]["turns"][0]["say"] = datasets.load_behaviours()[0]["turns"][0]["say"]
    assert any("development set" in e for e in datasets.validate_adversarial(cards))


def test_validator_catches_a_bad_behaviour_card():
    cards = copy.deepcopy(datasets.load_behaviours())
    cards[0]["turns"][0]["label"] = "nonsense"
    cards[1]["expect"]["outcome"] = "whatever"
    cards.pop()
    errors = datasets.validate_behaviours(cards)
    assert any("label nonsense" in e for e in errors) and any("outcome whatever" in e for e in errors) and any("need 15" in e for e in errors)


def test_redteam_must_be_adaptive():
    persona = copy.deepcopy(datasets.load_redteam())
    persona["turns"] = [{"say": "hi"}]
    assert any("adaptive" in e for e in datasets.validate_redteam(persona))
