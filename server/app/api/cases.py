"""Cases the signed-in user owns. Payloads are sealed with that case's data key."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import generate_key, open_text, wrap_data_key
from app.core.errors import AppError
from app.db.models import Approval, ApprovalStatus, Case, CaseStatus, Event, Fact, FactCertainty, FactSource, Run, User
from app.deps import current_user, get_session, require_step_up
from app.runtime.run_service import drop_case_checkpoints
from app.services.access import data_key, owned_case, record_event
from app.services.fact_service import confirm_fact, propose_fact, read_value

router = APIRouter(prefix="/cases", tags=["cases"])


class FactBody(BaseModel):
    field: str
    value: str = ""
    certainty: FactCertainty = FactCertainty.stated
    source: FactSource = FactSource.consumer_said
    phrase: str = ""


@router.post("", status_code=201)
def create_case(request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    raw_key = generate_key()
    case = Case(
        user_id=user.id,
        status=CaseStatus.intake,
        simulated=True,
        complaint_type="online_refund",
        data_key_enc=wrap_data_key(raw_key, request.app.state.master_key),
        created_at=request.app.state.clock.now(),
    )
    session.add(case)
    session.flush()
    return {"id": str(case.id), "status": case.status.value, "simulated": True}


@router.get("")
def list_cases(session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    rows = session.scalars(select(Case).where(Case.user_id == user.id).order_by(Case.created_at)).all()
    return {"cases": [{"id": str(row.id), "status": row.status.value, "simulated": row.simulated} for row in rows]}


@router.get("/{case_id}")
def get_case(case_id: uuid.UUID, request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    case = owned_case(session, user, case_id)
    key = data_key(request, case)
    remedy = open_text(case.remedy_enc, key) if case.remedy_enc else None
    facts = [_fact_view(fact, key) for fact in session.scalars(select(Fact).where(Fact.case_id == case.id, Fact.superseded_by.is_(None)))]
    timeline = []
    for event in session.scalars(select(Event).where(Event.case_id == case.id).order_by(Event.created_at)):
        timeline.append({"id": str(event.id), "kind": event.kind, "body": json.loads(open_text(event.body_enc, key))})
    approvals = session.scalars(select(Approval).where(Approval.case_id == case.id, Approval.status == ApprovalStatus.pending)).all()
    return {
        "id": str(case.id),
        "status": case.status.value,
        "simulated": case.simulated,
        "remedy": remedy,
        "facts": facts,
        "timeline": timeline,
        "open_approvals": [{"id": str(row.id), "kind": row.kind.value} for row in approvals],
    }


def _fact_view(fact: Fact, key: bytes) -> dict:
    return {
        "id": str(fact.id),
        "field": fact.field,
        "value": read_value(fact, key),
        "certainty": fact.certainty.value,
        "confirmation_state": fact.confirmation_state.value,
        "version": fact.version,
        "phrase": open_text(fact.phrase_enc, key) if fact.phrase_enc else "",
    }


@router.delete("/{case_id}")
def delete_case(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_step_up),
) -> dict:
    case = owned_case(session, user, case_id)
    thread_ids = [str(row) for row in session.scalars(select(Run.id).where(Run.case_id == case.id))]
    case.data_key_enc = None
    case.status = CaseStatus.deleted
    case.deleted_at = request.app.state.clock.now()
    request.app.state.objects.wipe(str(case.id))
    drop_case_checkpoints(request.app.state.settings.database_url, thread_ids)
    return {"id": str(case.id), "status": case.status.value}


@router.post("/{case_id}/facts", status_code=201)
def add_fact(
    case_id: uuid.UUID,
    body: FactBody,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    key = data_key(request, case)
    fact = propose_fact(session, case.id, body.field, body.value, body.certainty, body.source, key, phrase=body.phrase)
    record_event(session, case, key, "fact_proposed", {"fact_id": str(fact.id), "field": fact.field, "version": fact.version}, request.app.state.clock.now())
    return {"id": str(fact.id), "field": fact.field, "version": fact.version, "confirmation_state": fact.confirmation_state.value}


@router.get("/{case_id}/facts")
def list_facts(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    key = data_key(request, case)
    rows = session.scalars(select(Fact).where(Fact.case_id == case.id, Fact.superseded_by.is_(None))).all()
    return {"facts": [_fact_view(fact, key) for fact in rows]}


@router.post("/{case_id}/facts/{fact_id}/confirm")
def confirm(
    case_id: uuid.UUID,
    fact_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    fact = session.get(Fact, fact_id)
    if fact is None or fact.case_id != case.id:
        raise AppError("not_found", "Fact was not found", status_code=404)
    confirm_fact(session, fact)
    return {"id": str(fact.id), "confirmed_version": fact.confirmed_version, "value": read_value(fact, data_key(request, case))}
