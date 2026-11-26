"""Text intake. Each request runs the intake graph for one event."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import User
from app.deps import current_user, get_session
from app.services.access import data_key, owned_case
from app.services.intake_run import run_intake_event

router = APIRouter(prefix="/cases", tags=["intake"])


class IntakeMessage(BaseModel):
    text: str


def _run(request: Request, session: Session, user: User, case_id: uuid.UUID, event: str, text: str = "") -> dict:
    return run_intake_event(request, session, user, case_id, event, text)


@router.post("/{case_id}/intake/messages")
def intake_message(
    case_id: uuid.UUID,
    body: IntakeMessage,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    return _run(request, session, user, case_id, "message", body.text)


@router.post("/{case_id}/narration-done")
def narration_done(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    return _run(request, session, user, case_id, "done")


@router.post("/{case_id}/intake/silence")
def intake_silence(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    return _run(request, session, user, case_id, "silence")


@router.post("/{case_id}/reconcile")
def reconcile(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    from app.services.reconcile_service import reconcile_case

    case = owned_case(session, user, case_id)
    open_items = reconcile_case(request, session, user, case, data_key(request, case))
    return {"open": open_items, "status": case.status.value}
