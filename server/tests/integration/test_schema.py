import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.db.models import Base, Case, CaseStatus, Fact, FactCertainty, FactSource, User

ADMIN_URL = "postgresql://resolve:resolve@127.0.0.1:5434/resolve"
TEST_DB = os.environ.get("TEST_DB_NAME", "resolve_test")
TEST_URL = f"postgresql+psycopg://resolve:resolve@127.0.0.1:5434/{TEST_DB}"
PERSONAL_TOKENS = {
    "email",
    "phone",
    "address",
    "name",
    "body",
    "value",
    "transcript",
    "summary",
    "phrase",
    "remedy",
    "payload",
    "password",
}


def _fresh_database():
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")


def _alembic(direction: str) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_URL)
    if direction == "up":
        command.upgrade(cfg, "head")
    else:
        command.downgrade(cfg, "base")


@pytest.fixture()
def migrated_engine(monkeypatch):
    monkeypatch.setenv("ALEMBIC_URL", TEST_URL)
    _fresh_database()
    _alembic("up")
    engine = create_engine(TEST_URL)
    yield engine
    engine.dispose()
    _alembic("down")


def test_column_names_keep_personal_content_out_of_plain_columns():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.name.endswith("_enc") or column.name.endswith("_hash") or column.name.endswith("_ref"):
                continue
            tokens = set(column.name.split("_"))
            overlap = tokens & PERSONAL_TOKENS
            assert not overlap, f"{table.name}.{column.name} looks like personal plaintext"


def test_migrate_up_and_down(migrated_engine):
    names = set(Base.metadata.tables)
    with migrated_engine.connect() as conn:
        found = {row[0] for row in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))}
    assert names <= found


def test_invalid_case_status_is_rejected(migrated_engine):
    with migrated_engine.begin() as conn:
        with pytest.raises(Exception):
            conn.execute(
                text(
                    "INSERT INTO cases (id, user_id, status, simulated, complaint_type, created_at) "
                    "VALUES (:id, :user_id, 'not-a-status', true, 'online_refund', now())"
                ),
                {"id": uuid.uuid4(), "user_id": uuid.uuid4()},
            )


def test_superseded_fact_must_point_at_a_real_fact(migrated_engine):
    from sqlalchemy.orm import Session

    now = datetime.now(timezone.utc)
    with Session(migrated_engine) as session:
        user = User(
            email_hash="a" * 64,
            email_enc=b"enc",
            password_hash="hash",
            language="en",
            created_at=now,
        )
        session.add(user)
        session.flush()
        case = Case(user_id=user.id, status=CaseStatus.intake, simulated=True, complaint_type="online_refund", created_at=now)
        session.add(case)
        session.flush()
        older = Fact(
            case_id=case.id,
            field="amount",
            value_enc=b"1",
            source=FactSource.consumer_said,
            certainty=FactCertainty.approximate,
            version=1,
        )
        newer = Fact(
            case_id=case.id,
            field="amount",
            value_enc=b"2",
            source=FactSource.consumer_said,
            certainty=FactCertainty.stated,
            version=2,
        )
        session.add_all([older, newer])
        session.flush()
        older.superseded_by = newer.id
        session.commit()
        older_id = older.id

    with Session(migrated_engine) as session:
        row = session.get(Fact, older_id)
        row.superseded_by = uuid.uuid4()
        with pytest.raises(IntegrityError):
            session.commit()


def test_events_reject_updates(migrated_engine):
    from sqlalchemy.orm import Session

    from app.db.models import Event

    now = datetime.now(timezone.utc)
    with Session(migrated_engine) as session:
        user = User(email_hash="b" * 64, email_enc=b"enc", password_hash="hash", language="en", created_at=now)
        session.add(user)
        session.flush()
        case = Case(user_id=user.id, status=CaseStatus.intake, simulated=True, complaint_type="online_refund", created_at=now)
        session.add(case)
        session.flush()
        event = Event(case_id=case.id, kind="note", body_enc=b"hello", created_at=now)
        session.add(event)
        session.commit()
        event.body_enc = b"changed"
        with pytest.raises(Exception):
            session.commit()
