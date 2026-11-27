"""A simulated provider call in text. The provider's turns are typed in; the agent's sentences come back already
checked by the output guard. The summary approval appears in the approvals API and only the owner decides it."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Call, CallMode, CallRole, CaseStatus, User
from app.deps import current_user, get_session
from app.services.access import data_key, owned_case
from app.services.mandate_service import check_outreach
from app.services.outreach_store import build_runner

router = APIRouter(tags=["outreach"])


class ProviderTurn(BaseModel):
    text: str = Field(default="", max_length=2000)


def _view(result) -> dict:
    out = {"sentences": result.sentences, "phase": result.phase, "ended": result.ended}
    if result.approval_id:
        out["approval_id"] = result.approval_id
    if result.end_reason:
        out["end_reason"] = result.end_reason
    return out


def _owned_text_call(session: Session, user: User, call_id: uuid.UUID, lock: bool = True) -> Call:
    query = select(Call).where(Call.id == call_id, Call.mode == CallMode.text)
    call = session.scalar(query.with_for_update() if lock else query)
    if call is None:
        raise AppError("not_found", "Call was not found", status_code=404)
    owned_case(session, user, call.case_id)  # another user's call is a 404, never a 403
    return call


@router.post("/cases/{case_id}/outreach/calls", status_code=201)
def start_text_call(case_id: uuid.UUID, request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    case = owned_case(session, user, case_id)
    key = data_key(request, case)
    now = request.app.state.clock.now()
    if case.status in {CaseStatus.deleted, CaseStatus.closed}:
        raise AppError("case_closed", "This case is closed", status_code=409)
    problem = check_outreach(session, case.id, key, now)
    if problem is not None:
        raise AppError("mandate_required", "A current permission from you is needed before the call", status_code=409, details={"reason": problem})
    call = Call(case_id=case.id, role=CallRole.provider_human, mode=CallMode.text, simulated=True)
    session.add(call)
    session.flush()
    result = build_runner(request, session, user, case, call, key).start(str(case.id), str(call.id))
    if result.blocked:
        raise AppError("mandate_required", "A current permission from you is needed before the call", status_code=409, details={"reason": result.blocked})
    return {"call_id": str(call.id), "simulated": True, **_view(result)}


@router.post("/calls/{call_id}/provider-turn")
def provider_turn(call_id: uuid.UUID, body: ProviderTurn, request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    call = _owned_text_call(session, user, call_id)
    case = owned_case(session, user, call.case_id)
    result = build_runner(request, session, user, case, call, data_key(request, case)).turn(str(case.id), str(call.id), body.text)
    return _view(result)


def end_text_call(request: Request, session: Session, user: User, call_id: uuid.UUID) -> dict:
    call = _owned_text_call(session, user, call_id)
    case = owned_case(session, user, call.case_id)
    result = build_runner(request, session, user, case, call, data_key(request, case)).end(str(case.id), str(call.id))
    return {"call_id": str(call.id), "state": "closed", **_view(result)}
