"""Shared fixtures for the legal corpus tests. Uses its own database (TEST_DB_NAME, default resolve_test)."""

from __future__ import annotations

import os

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import EMBEDDING_DIM
from app.legal.chunker import build_corpus
from app.legal.embeddings import HashEmbedder
from app.legal.ingest import ingest

ADMIN_URL = "postgresql://resolve:resolve@127.0.0.1:5434/resolve"
TEST_DB = os.environ.get("TEST_DB_NAME", "resolve_test")
TEST_URL = f"postgresql+psycopg://resolve:resolve@127.0.0.1:5434/{TEST_DB}"


def fresh_legal_database() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    os.environ["ALEMBIC_URL"] = TEST_URL
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_URL)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="module")
def legal_engine():
    fresh_legal_database()
    engine = create_engine(TEST_URL)
    yield engine
    engine.dispose()


@pytest.fixture()
def legal_session(legal_engine):
    """A session whose changes are rolled back at the end of the test."""
    connection = legal_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="module")
def hash_embedder():
    return HashEmbedder(EMBEDDING_DIM)


@pytest.fixture()
def loaded_session(legal_session, hash_embedder):
    ingest(legal_session, build_corpus(), hash_embedder)
    return legal_session
