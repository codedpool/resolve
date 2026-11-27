"""Starts the API for the browser end-to-end test: a throwaway database, throwaway keys, scripted vendors.

    server\\.venv\\Scripts\\python.exe server\\scripts\\run_e2e_server.py [--port 8010]

It drops and creates the database `resolve_e2e` on the local dev Postgres (the `resolve-db` container on port 5434),
runs `alembic upgrade head` on it, makes a fresh MASTER_KEY and JWT_SECRET for this run only (the real .env keys are
never used), blanks the vendor keys, sets RESOLVE_FAKE_VENDORS=1 with APP_ENV=dev, and serves the app with uvicorn.
Nothing is written to .env. Set E2E_DB_NAME or E2E_CORS_ORIGINS to change the database name or the allowed origin.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from base64 import urlsafe_b64encode
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("E2E_ADMIN_URL", "postgresql://resolve:resolve@127.0.0.1:5434/resolve")


def prepare(db_name: str) -> str:
    import psycopg

    if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", db_name) or db_name == "resolve":
        raise SystemExit(f"refusing to use {db_name!r} as the throwaway database name")
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {db_name}")
    url = ADMIN_URL.replace("postgresql://", "postgresql+psycopg://").rsplit("/", 1)[0] + f"/{db_name}"
    os.environ["ALEMBIC_URL"] = url
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(SERVER_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    os.chdir(SERVER_ROOT)
    sys.path.insert(0, str(SERVER_ROOT))
    url = prepare(os.environ.get("E2E_DB_NAME", "resolve_e2e"))
    os.environ.update(
        APP_ENV="dev",
        RESOLVE_FAKE_VENDORS="1",
        DATABASE_URL=url,
        MASTER_KEY=urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        JWT_SECRET=secrets.token_urlsafe(48),
        GROQ_API_KEY="",
        RUMIK_API_KEY="",
        CORS_ORIGINS=os.environ.get("E2E_CORS_ORIGINS", "http://localhost:3010,http://127.0.0.1:3010"),
    )
    import uvicorn

    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
