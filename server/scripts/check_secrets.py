"""Scan git-tracked files for key-like strings and for values loaded from .env.

Never prints secret values. Exit 0 when clean, 1 when a finding is reported.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

KEY_PATTERNS = (
    re.compile(r"gsk_[A-Za-z0-9]{10,}"),
    re.compile(r"rk_(?:live|test)_[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

SKIP_NAMES = {".env", ".env.local"}


def load_env_secrets(env_path: Path) -> list[str]:
    if not env_path.is_file():
        return []
    secrets: list[str] = []
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        _, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if len(value) >= 8:
            secrets.append(value)
    return secrets


def candidate_files(repo: Path) -> list[Path]:
    if not (repo / ".git").exists():
        return []
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode != 0:
        return []
    files: list[Path] = []
    for rel in tracked.stdout.splitlines():
        path = repo / rel
        if path.name in SKIP_NAMES or not path.is_file():
            continue
        files.append(path)
    return files


def scan_text(text: str, secrets: list[str]) -> str | None:
    for pattern in KEY_PATTERNS:
        if pattern.search(text):
            return "key-like pattern"
    for secret in secrets:
        if secret in text:
            return "contains a value from .env"
    return None


def scan(root: Path | None = None) -> list[str]:
    root = root or ROOT
    secrets = load_env_secrets(root / ".env")
    repos = [root, root / "client", root / "server", root / "workflows"]
    findings: list[str] = []
    for repo in repos:
        for path in candidate_files(repo):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            reason = scan_text(text, secrets)
            if reason:
                findings.append(f"{path.relative_to(root)}: {reason}")
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("Secrets scan failed:")
        for finding in findings:
            print(f" - {finding}")
        return 1
    print("Secrets scan clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
