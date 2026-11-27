"""Follow-up after the company writes back or a date passes: the reply or the deadline goes through the follow-up graph,
which proposes the next step. Anything that leaves the app is an approval the owner decides (with step-up) in the approvals
API. The case becomes `resolved_consumer_confirmed` only through `POST /cases/{id}/confirm-resolved`, never through the graph."""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Case, CaseStatus, Deadline, DeadlineStatus, User
from app.deps import current_user, get_session, require_step_up
from app.services.access import data_key, owned_case, record_event
from app.services.followup_store import build_followup_runner

router = APIRouter(tags=["follow-up"])

CLOSED = {CaseStatus.deleted, CaseStatus.closed}
CONFIRMABLE = {
    CaseStatus.mandate_active, CaseStatus.outreach, CaseStatus.awaiting_provider, CaseStatus.awaiting_consumer, CaseStatus.provider_claimed_resolved,
}


class FollowUpBody(BaseModel):
    reply_text: str | None = Field(default=None, max_length=4000)
    deadline_id: uuid.UUID | None = None


class RouteChoice(BaseModel):
    kind: str = Field(min_length=1, max_length=64)


def _locked_case(session: Session, user: User, case_id: uuid.UUID) -> Case:
    owned_case(session, user, case_id)  # another user's case is a 404, never a 403
    return session.scalar(select(Case).where(Case.id == case_id).with_for_update())  # one event at a time per case


def _view(result, case: Case) -> dict:
    out = asdict(result)
    out["case_status"] = case.status.value
    out["simulated"] = case.simulated
    return out


@router.post("/cases/{case_id}/follow-up")
def follow_up(case_id: uuid.UUID, body: FollowUpBody, request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    case = _locked_case(session, user, case_id)
    if case.status in CLOSED:
        raise AppError("case_closed", "This case is closed", status_code=409)
    if (body.reply_text is None) == (body.deadline_id is None):
        raise AppError("bad_follow_up", "Send either reply_text or deadline_id", status_code=400)
    key = data_key(request, case)
    runner, _store = build_followup_runner(request, session, user, case, key)
    if body.deadline_id is not None:
        deadline = session.get(Deadline, body.deadline_id)
        if deadline is None or deadline.case_id != case.id:
            raise AppError("not_found", "Deadline was not found", status_code=404)
        if deadline.due_at > request.app.state.clock.now() or deadline.status == DeadlineStatus.cancelled:
            raise AppError("deadline_not_due", "That date has not passed yet", status_code=409)
        result = runner.deadline(str(case.id), str(deadline.id), deadline.kind)
        if deadline.status == DeadlineStatus.scheduled:
            deadline.status = DeadlineStatus.fired
    else:
        if not body.reply_text.strip():
            raise AppError("bad_follow_up", "The reply is empty; use deadline_id to report silence", status_code=400)
        result = runner.reply(str(case.id), body.reply_text)
    return _view(result, case)


@router.get("/cases/{case_id}/follow-up")
def get_follow_up(case_id: uuid.UUID, request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    case = owned_case(session, user, case_id)
    _runner, store = build_followup_runner(request, session, user, case, data_key(request, case))
    state = store.load(str(case.id)) or {}
    pending = state.get("pending")
    deadlines = session.scalars(select(Deadline).where(Deadline.case_id == case.id, Deadline.status == DeadlineStatus.scheduled).order_by(Deadline.due_at)).all()
    return {
        "case_status": case.status.value,
        "simulated": case.simulated,
        "last": state.get("last") or None,
        "pending_choice": None if not pending else {"candidates": pending["selection"]["candidates"], "entity_type": pending["selection"]["entity_type"], "reason": pending["selection"]["reason"]},
        "reminders": [{"id": str(d.id), "kind": d.kind, "due_at": d.due_at.isoformat()} for d in deadlines],
    }


@router.post("/cases/{case_id}/follow-up/choose-route")
def choose_route(case_id: uuid.UUID, body: RouteChoice, request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    case = _locked_case(session, user, case_id)
    if case.status in CLOSED:
        raise AppError("case_closed", "This case is closed", status_code=409)
    runner, _store = build_followup_runner(request, session, user, case, data_key(request, case))
    try:
        result = runner.choose(str(case.id), body.kind)
    except ValueError as exc:
        raise AppError("bad_route", "That is not one of the routes offered", status_code=400) from exc
    if result.ignored:
        raise AppError("no_choice_pending", "There is no escalation choice waiting", status_code=409)
    return _view(result, case)


@router.post("/cases/{case_id}/confirm-resolved")
def confirm_resolved(case_id: uuid.UUID, request: Request, session: Session = Depends(get_session), user: User = Depends(require_step_up)) -> dict:
    """The consumer says the problem is resolved. This is the only way a case reaches `resolved_consumer_confirmed`."""
    case = _locked_case(session, user, case_id)
    if case.status == CaseStatus.resolved_consumer_confirmed:
        raise AppError("already_confirmed", "You already confirmed this case as resolved", status_code=409)
    if case.status not in CONFIRMABLE:
        raise AppError("not_resolvable", "This case is not at a stage where it can be marked resolved", status_code=409, details={"status": case.status.value})
    now = request.app.state.clock.now()
    case.status = CaseStatus.resolved_consumer_confirmed
    session.execute(update(Deadline).where(Deadline.case_id == case.id, Deadline.status == DeadlineStatus.scheduled).values(status=DeadlineStatus.cancelled))
    record_event(session, case, data_key(request, case), "consumer_confirmed_resolved", {}, now)
    return {"id": str(case.id), "status": case.status.value, "simulated": case.simulated}
