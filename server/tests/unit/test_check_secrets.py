"""Unit tests for the secrets scanner. Uses synthetic strings only."""

import subprocess
import sys
from pathlib import Path

from scripts.check_secrets import scan_text

WORKSPACE = Path(__file__).resolve().parents[3]
SCRIPT = WORKSPACE / "server" / "scripts" / "check_secrets.py"


def test_scan_text_flags_key_like_pattern():
    reason = scan_text("token = gsk_" + "a" * 20, secrets=[])
    assert reason == "key-like pattern"


def test_scan_text_flags_env_value_without_echoing_it():
    secret = "synthetic-secret-value"
    reason = scan_text(f"leaked {secret} here", secrets=[secret])
    assert reason == "contains a value from .env"
    assert secret not in (reason or "")


def test_scan_text_clean():
    assert scan_text("DATABASE_URL is configured", secrets=["other-secret"]) is None


def test_check_secrets_script_exits_zero_on_workspace():
    python = WORKSPACE / "server" / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        python = Path(sys.executable)
    result = subprocess.run([str(python), str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "clean" in result.stdout.lower()
