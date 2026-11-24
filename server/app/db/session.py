"""Database sessions."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def make_engine(settings: Settings):
    return create_engine(settings.database_url, future=True)


def make_session_factory(settings: Settings):
    return sessionmaker(bind=make_engine(settings), expire_on_commit=False, class_=Session)
