"""Versioned mandates. Grant and revoke both need a fresh step-up."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.crypto import open_text
from app.core.errors import AppError
from app.db.models import CaseStatus, Mandate, User
from app.deps import current_user, get_session, require_step_up
from app.services.access import data_key, owned_case
from app.services.mandate_service import DEFAULT_DISCLOSURE, grant_mandate, latest_row, revoke_mandate, state_of

router = APIRouter(prefix="/cases", tags=["mandates"])


class MandateBody(BaseModel):
    action: str = "grant"
    goal: str = "refund"
    disclosure: list[str] = Field(default_factory=lambda: list(DEFAULT_DISCLOSURE))
    allowed_actions: list[str] = Field(default_factory=lambda: ["ask_for_refund"])
    limits: dict = Field(default_factory=lambda: {"accept_partial": False})
    channels: list[str] = Field(default_factory=lambda: ["simulated_call"])
    call_limit_seconds: int = 600
    expires_in_days: int = 30


def _view(row: Mandate, key: bytes, now) -> dict:
    return {
        "id": str(row.id),
        "version": row.version,
        "goal": open_text(row.goal_enc, key),
        "disclosure": json.loads(open_text(row.disclosure_enc, key)),
        "call_limit_seconds": row.call_limit_seconds,
        "expires_at": row.expires_at.isoformat(),
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "active": state_of(row, now) == "active",
    }


@router.get("/{case_id}/mandate")
def get_mandate(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    row = latest_row(session, case.id)
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
    if body.action != "revoke" and case.status == CaseStatus.confirming:
        raise AppError("confirm_details_first", "Confirm every detail, and settle any question about them, before giving permission", status_code=409)
    if body.action == "revoke":
        return {"mandate": _view(revoke_mandate(session, case, key, now), key, now)}
    if body.action != "grant":
        raise AppError("bad_action", "Mandate action must be grant or revoke", status_code=400)
    row = grant_mandate(
        session, case, key, now,
        goal=body.goal,
        disclosure=body.disclosure,
        allowed_actions=body.allowed_actions,
        limits=body.limits,
        channels=body.channels,
        call_limit_seconds=body.call_limit_seconds,
        expires_in_days=body.expires_in_days,
    )
    return {"mandate": _view(row, key, now)}
