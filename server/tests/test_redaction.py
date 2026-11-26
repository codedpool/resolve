import json
import logging
from pathlib import Path

from app.privacy import redact as redact_module
from app.privacy.redact import Redactor

DATASET = Path(__file__).resolve().parents[2] / "workflows" / "evals" / "datasets" / "redaction.json"
ITEMS = json.loads(DATASET.read_text(encoding="utf-8"))
R = Redactor()


def test_dataset_has_150_labelled_strings():
    assert len(ITEMS) == 150
    assert {"otp", "card", "identity", "address", "order_id", "keep", "other_long"} <= {i["class"] for i in ITEMS}


def _failures(kind_filter):
    leaks, lost = [], []
    for item in ITEMS:
        if kind_filter(item):
            out = R.redact_or_withhold(item["text"]).text
            leaks += [(item["id"], s) for s in item["redact"] if s in out]
            lost += [(item["id"], s) for s in item["keep"] if s not in out]
    return leaks, lost


def test_no_otp_card_or_identity_value_survives():
    leaks, _ = _failures(lambda i: i["class"] in {"otp", "card", "identity"})
    assert leaks == []


def test_no_other_sensitive_value_survives():
    leaks, _ = _failures(lambda i: i["class"] in {"phone", "email", "other_long", "order_id"})
    assert leaks == []


def test_address_recall_is_reported_and_high():
    hits = total = 0
    for item in ITEMS:
        if item["class"] == "address":
            out = R.redact_or_withhold(item["text"]).text
            for s in item["redact"]:
                total += 1
                hits += s not in out
    assert hits / total >= 0.9, f"address recall {hits}/{total}"


def test_amounts_dates_and_counts_survive():
    _, lost = _failures(lambda i: i["class"] == "keep")
    assert len(lost) / sum(len(i["keep"]) for i in ITEMS if i["class"] == "keep") < 0.02, lost


def test_order_id_tokens_round_trip():
    for item in ITEMS:
        if item["reversible"]:
            result = R.redact(item["text"])
            assert any(t.startswith("[NUM_") for t in result.tokens), item["id"]
            restored = R.restore(result.text, result.tokens)
            for value in item["redact"]:
                if any(ch.isdigit() for ch in value):
                    assert value in restored, item["id"]


def test_same_order_id_reuses_its_token():
    first = R.redact("order id OD1234567890 hai")
    second = R.redact("phir se OD1234567890 dekhiye", first.tokens)
    assert list(second.tokens) == list(first.tokens)


def test_card_cue_wins_over_order_context():
    out = R.redact("order id 4111 1111 1111 1111 card number").text
    assert "4111" not in out


def test_luhn_failing_run_is_still_redacted():
    out = R.redact("card number 4111 1111 1111 1112").text
    assert "4111" not in out and "1112" not in out


def test_detector_error_withholds_the_segment(monkeypatch):
    def boom(text):
        raise ValueError("detector broke")

    monkeypatch.setattr(redact_module, "_find", boom)
    result = R.redact_or_withhold("mera OTP 123456 hai")
    assert result.withheld is True
    assert result.text == ""


def test_redaction_never_logs_raw_digits(caplog):
    with caplog.at_level(logging.DEBUG):
        R.redact_or_withhold("card number 4111 1111 1111 1111 aur OTP 482913")
    assert "4111" not in caplog.text and "482913" not in caplog.text


def test_held_out_strings():
    cases = {
        "OTP is 4 7 2 9": "4 7 2 9",
        "verification code four seven two nine": "4729",
        "mera cvv 123 hai": "123",
        "my card 4111-1111-1111-1111 expiry 12/27": "4111",
        "number hai 98765 43210": "98765",
        "call +91-9876543210": "9876543210",
        "delivery address 12 Park Street, Kolkata 700016": "700016",
        "UPI id rahul@okhdfc": "rahul@okhdfc",
        "passport number K1234567": "K1234567",
        "account number 123456789012 ka statement": "123456789012",
    }
    for text, secret in cases.items():
        assert secret not in R.redact_or_withhold(text).text, text


def test_counts_and_amounts_in_ordinary_speech_survive():
    text = "main 1 saal se customer hoon, 3 baar complaint ki, 2500 rupaye ka maamla"
    assert R.redact_or_withhold(text).text == text
