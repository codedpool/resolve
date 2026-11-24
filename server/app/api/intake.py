"""Text intake. Replies stay short until the intake graph exists."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import User
from app.deps import current_user, get_session
from app.services.access import data_key, owned_case, record_event

router = APIRouter(prefix="/cases", tags=["intake"])


class IntakeMessage(BaseModel):
    text: str


@router.post("/{case_id}/intake/messages")
def intake_message(
    case_id: uuid.UUID,
    body: IntakeMessage,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    record_event(
        session,
        case,
        data_key(request, case),
        "intake_message",
        {"text": body.text},
        request.app.state.clock.now(),
    )
    return {"text": "I have that. Add anything else, or press Done."}


@router.post("/{case_id}/narration-done")
def narration_done(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    record_event(session, case, data_key(request, case), "narration_done", {}, request.app.state.clock.now())
    return {"ok": True}
