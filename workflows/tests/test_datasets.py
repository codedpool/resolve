from resolve_workflows import datasets


def test_every_dataset_validates():
    problems = {name: errors for name, errors in datasets.validate_all().items() if errors}
    assert problems == {}


def test_counts_are_met():
    assert len(datasets.load("intake")) == 20
    assert len(datasets.load("normalisation")) == 60
    assert len(datasets.load("redaction")) == 150
    assert len(datasets.load("turn_sentences")) == 30


def test_intake_validator_catches_a_bad_certainty():
    items = datasets.load("intake")
    items[0]["expect"]["amount"] = {"value": "", "certainty": "stated"}
    assert any("amount" in e for e in datasets.validate_intake(items))
