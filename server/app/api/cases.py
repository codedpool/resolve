"""Cases the signed-in user owns. Payloads are sealed with that case's data key."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import open_text, unwrap_data_key, wrap_data_key, generate_key
from app.core.errors import AppError
from app.db.models import Case, CaseStatus, Fact, FactCertainty, FactSource, User
from app.deps import current_user, get_session, require_step_up
from app.services.fact_service import confirm_fact, propose_fact, read_value

router = APIRouter(prefix="/cases", tags=["cases"])


class FactBody(BaseModel):
    field: str
    value: str = ""
    certainty: FactCertainty = FactCertainty.stated
    source: FactSource = FactSource.consumer_said
    phrase: str = ""


def _owned_case(session: Session, user: User, case_id: uuid.UUID) -> Case:
    case = session.get(Case, case_id)
    if case is None or case.user_id != user.id:
        raise AppError("not_found", "Case was not found", status_code=404)
    return case


def _data_key(request: Request, case: Case) -> bytes:
    return unwrap_data_key(case.data_key_enc, request.app.state.master_key)


@router.post("", status_code=201)
def create_case(request: Request, session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    data_key = generate_key()
    case = Case(
        user_id=user.id,
        status=CaseStatus.intake,
        simulated=True,
        complaint_type="online_refund",
        data_key_enc=wrap_data_key(data_key, request.app.state.master_key),
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
    case = _owned_case(session, user, case_id)
    remedy = None
    if case.remedy_enc:
        remedy = open_text(case.remedy_enc, _data_key(request, case))
    facts = []
    for fact in session.scalars(select(Fact).where(Fact.case_id == case.id, Fact.superseded_by.is_(None))):
        facts.append(
            {
                "id": str(fact.id),
                "field": fact.field,
                "value": read_value(fact, _data_key(request, case)),
                "certainty": fact.certainty.value,
                "confirmation_state": fact.confirmation_state.value,
                "version": fact.version,
            }
        )
    return {
        "id": str(case.id),
        "status": case.status.value,
        "simulated": case.simulated,
        "remedy": remedy,
        "facts": facts,
    }


@router.delete("/{case_id}")
def delete_case(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_step_up),
) -> dict:
    case = _owned_case(session, user, case_id)
    case.data_key_enc = None
    case.status = CaseStatus.deleted
    case.deleted_at = request.app.state.clock.now()
    request.app.state.objects.wipe(str(case.id))
    return {"id": str(case.id), "status": case.status.value}


@router.post("/{case_id}/facts", status_code=201)
def add_fact(
    case_id: uuid.UUID,
    body: FactBody,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = _owned_case(session, user, case_id)
    fact = propose_fact(
        session,
        case.id,
        body.field,
        body.value,
        body.certainty,
        body.source,
        _data_key(request, case),
        phrase=body.phrase,
    )
    return {"id": str(fact.id), "field": fact.field, "version": fact.version, "confirmation_state": fact.confirmation_state.value}


@router.post("/{case_id}/facts/{fact_id}/confirm")
def confirm(
    case_id: uuid.UUID,
    fact_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = _owned_case(session, user, case_id)
    fact = session.get(Fact, fact_id)
    if fact is None or fact.case_id != case.id:
        raise AppError("not_found", "Fact was not found", status_code=404)
    confirm_fact(session, fact)
    return {"id": str(fact.id), "confirmed_version": fact.confirmed_version, "value": read_value(fact, _data_key(request, case))}
