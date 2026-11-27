import json
import logging

from app.config import Settings
from app.core.logging import RedactionFilter, configure_logging


def test_settings_read_role_models_from_yaml(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("roles:\n  extract:\n    model: qwen/qwen3.8-27b\n", encoding="utf-8")
    settings = Settings(models_path=path, groq_api_key="", rumik_api_key="")
    assert settings.load_models()["roles"]["extract"]["model"] == "qwen/qwen3.8-27b"


def test_log_filter_removes_a_canary_secret():
    canary = "canary-secret-value-should-not-leak"
    filt = RedactionFilter([canary])
    record = logging.LogRecord("resolve", logging.INFO, __file__, 1, "token %s", (canary,), None)
    assert filt.filter(record) is True
    assert canary not in record.getMessage()
    assert "[redacted]" in record.getMessage()


def test_configured_logger_emits_json_without_the_canary():
    canary = "gsk_" + "a" * 20
    logger = configure_logging([canary])
    record = logging.LogRecord("resolve", logging.INFO, __file__, 1, "calling vendor with %s", (canary,), None)
    handler = logger.handlers[-1]
    handler.handle(record)
    payload = json.loads(handler.format(record))
    assert canary not in payload["message"]
    assert "[redacted]" in payload["message"]


def test_log_filter_keeps_numeric_formats_working_and_still_strips_secrets():
    canary = "canary-secret-value-should-not-leak"
    filt = RedactionFilter([canary])
    record = logging.LogRecord("resolve", logging.INFO, __file__, 1, "took %.2fs for %d items using %s", (1.2345, 3, canary), None)
    assert filt.filter(record) is True
    message = record.getMessage()
    assert message.startswith("took 1.23s for 3 items") and canary not in message
