"""Case ownership and append-only timeline rows."""

from __future__ import annotations

import json
import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.crypto import seal_text, unwrap_data_key
from app.core.errors import AppError
from app.db.models import Case, Event, User


def owned_case(session: Session, user: User, case_id: uuid.UUID) -> Case:
    case = session.get(Case, case_id)
    if case is None or case.user_id != user.id:
        raise AppError("not_found", "Case was not found", status_code=404)
    return case


def data_key(request: Request, case: Case) -> bytes:
    return unwrap_data_key(case.data_key_enc, request.app.state.master_key)


def record_event(session: Session, case: Case, key: bytes, kind: str, body: dict, when) -> Event:
    row = Event(
        case_id=case.id,
        kind=kind,
        body_enc=seal_text(json.dumps(body), key),
        created_at=when,
    )
    session.add(row)
    session.flush()
    return row
