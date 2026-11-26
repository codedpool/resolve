"""Fills JWT_SECRET and MASTER_KEY in the repo-root .env when they are missing or empty.

Never prints a value. Existing values are left alone, so run it as often as you like.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.crypto import encode_master_key, generate_key  # noqa: E402

ENV = Path(__file__).resolve().parents[2] / ".env"


def main() -> int:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.is_file() else []
    wanted = {"JWT_SECRET": lambda: secrets.token_urlsafe(48), "MASTER_KEY": lambda: encode_master_key(generate_key())}
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        name, sep, value = line.partition("=")
        key = name.strip()
        if sep and key in wanted:
            seen.add(key)
            if not value.strip().strip('"').strip("'"):
                line = f"{key}={wanted[key]()}"
                print(f"set {key}")
        out.append(line)
    for key, make in wanted.items():
        if key not in seen:
            out.append(f"{key}={make()}")
            print(f"added {key}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
