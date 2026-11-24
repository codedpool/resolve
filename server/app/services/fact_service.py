"""Fact versions. A correction supersedes the previous row and clears confirmation on the new one."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import open_text, seal_text
from app.core.errors import AppError
from app.db.models import ConfirmationState, Fact, FactCertainty, FactSource


def current_fact(session: Session, case_id: uuid.UUID, field: str) -> Fact | None:
    return session.scalar(
        select(Fact)
        .where(Fact.case_id == case_id, Fact.field == field, Fact.superseded_by.is_(None))
        .order_by(Fact.version.desc())
    )


def propose_fact(
    session: Session,
    case_id: uuid.UUID,
    field: str,
    value: str,
    certainty: FactCertainty,
    source: FactSource,
    data_key: bytes,
    phrase: str = "",
    normalized: dict | None = None,
) -> Fact:
    previous = current_fact(session, case_id, field)
    version = 1 if previous is None else previous.version + 1
    row = Fact(
        case_id=case_id,
        field=field,
        value_enc=seal_text(value, data_key),
        normalized_enc=seal_text(json.dumps(normalized or {}), data_key),
        source=source,
        certainty=certainty,
        phrase_enc=seal_text(phrase, data_key) if phrase else None,
        confirmation_state=ConfirmationState.unconfirmed,
        confirmed_version=None,
        version=version,
    )
    session.add(row)
    session.flush()
    if previous is not None:
        previous.superseded_by = row.id
    return row


def confirm_fact(session: Session, fact: Fact) -> Fact:
    if fact.superseded_by is not None:
        raise AppError("stale_fact", "Confirm the current version", status_code=409)
    fact.confirmation_state = ConfirmationState.confirmed
    fact.confirmed_version = fact.version
    return fact


def read_value(fact: Fact, data_key: bytes) -> str:
    return open_text(fact.value_enc, data_key)
