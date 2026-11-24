import pytest
from datetime import datetime, timezone

import psycopg
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config
from app.config import Settings
from app.core.clock import FrozenClock
from app.core.crypto import encode_master_key, generate_key
from app.main import create_app

ADMIN_URL = "postgresql://resolve:resolve@127.0.0.1:5434/resolve"
TEST_URL = "postgresql+psycopg://resolve:resolve@127.0.0.1:5434/resolve_test"


def _database():
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS resolve_test WITH (FORCE)")
        conn.execute("CREATE DATABASE resolve_test")
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_URL)
    command.upgrade(cfg, "head")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ALEMBIC_URL", TEST_URL)
    _database()
    engine = create_engine(TEST_URL)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    clock = FrozenClock(datetime.now(timezone.utc).replace(microsecond=0))
    settings = Settings(
        app_env="test",
        jwt_secret="test-jwt-secret-value-32-bytes-minimum",
        master_key=encode_master_key(generate_key()),
        groq_api_key="",
        rumik_api_key="",
        database_url=TEST_URL,
    )
    app = create_app(settings=settings, clock=clock, session_factory=factory)
    app.state.objects.root = tmp_path
    test_client = TestClient(app)
    test_client.clock = clock
    test_client.db_engine = engine
    yield test_client
    engine.dispose()
