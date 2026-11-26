"""Versioned mandates. Grant and revoke both need a fresh step-up."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import open_text, seal_text
from app.core.errors import AppError
from app.db.models import CaseStatus, Mandate, User
from app.deps import current_user, get_session, require_step_up
from app.services.access import data_key, owned_case, record_event

router = APIRouter(prefix="/cases", tags=["mandates"])

DEFAULT_DISCLOSURE = ["order_id", "amount", "order_date", "issue_summary", "consumer_name"]


class MandateBody(BaseModel):
    action: str = "grant"
    goal: str = "refund"
    disclosure: list[str] = Field(default_factory=lambda: list(DEFAULT_DISCLOSURE))
    allowed_actions: list[str] = Field(default_factory=lambda: ["ask_for_refund"])
    limits: dict = Field(default_factory=lambda: {"accept_partial": False})
    channels: list[str] = Field(default_factory=lambda: ["simulated_call"])
    call_limit_seconds: int = 600
    expires_in_days: int = 30


def _current(session: Session, case_id: uuid.UUID) -> Mandate | None:
    return session.scalar(select(Mandate).where(Mandate.case_id == case_id).order_by(Mandate.version.desc()))


def _view(row: Mandate, key: bytes, now) -> dict:
    return {
        "id": str(row.id),
        "version": row.version,
        "goal": open_text(row.goal_enc, key),
        "disclosure": json.loads(open_text(row.disclosure_enc, key)),
        "call_limit_seconds": row.call_limit_seconds,
        "expires_at": row.expires_at.isoformat(),
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "active": row.revoked_at is None and row.expires_at > now,
    }


@router.get("/{case_id}/mandate")
def get_mandate(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    row = _current(session, case.id)
    if row is None:
        return {"mandate": None}
    return {"mandate": _view(row, data_key(request, case), request.app.state.clock.now())}


@router.post("/{case_id}/mandate")
def set_mandate(
    case_id: uuid.UUID,
    body: MandateBody,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_step_up),
) -> dict:
    case = owned_case(session, user, case_id)
    key = data_key(request, case)
    now = request.app.state.clock.now()
    current = _current(session, case.id)
    if body.action != "revoke" and case.status == CaseStatus.confirming:
        raise AppError("confirm_details_first", "Confirm every detail, and settle any question about them, before giving permission", status_code=409)
    if body.action == "revoke":
        if current is None or current.revoked_at is not None:
            raise AppError("not_found", "Mandate was not found", status_code=404)
        current.revoked_at = now
        record_event(session, case, key, "mandate_revoked", {"version": current.version}, now)
        return {"mandate": _view(current, key, now)}
    if body.action != "grant":
        raise AppError("bad_action", "Mandate action must be grant or revoke", status_code=400)
    version = 1 if current is None else current.version + 1
    row = Mandate(
        case_id=case.id,
        version=version,
        goal_enc=seal_text(body.goal, key),
        allowed_actions_enc=seal_text(json.dumps(body.allowed_actions), key),
        disclosure_enc=seal_text(json.dumps(body.disclosure), key),
        limits_enc=seal_text(json.dumps(body.limits), key),
        channels_enc=seal_text(json.dumps(body.channels), key),
        call_limit_seconds=body.call_limit_seconds,
        expires_at=now + timedelta(days=body.expires_in_days),
        granted_at=now,
    )
    session.add(row)
    session.flush()
    record_event(session, case, key, "mandate_granted", {"version": version}, now)
    return {"mandate": _view(row, key, now)}
