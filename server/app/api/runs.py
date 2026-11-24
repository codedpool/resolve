"""Graph runs. The same idempotency key returns the run already created."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import Run, RunStatus, User
from app.deps import current_user, get_session
from app.services.access import data_key, owned_case, record_event

router = APIRouter(tags=["runs"])


class RunBody(BaseModel):
    graph: str


@router.post("/cases/{case_id}/runs", status_code=201)
def create_run(
    case_id: uuid.UUID,
    body: RunBody,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    if not idempotency_key:
        raise AppError("idempotency_key_required", "Send an Idempotency-Key header", status_code=400)
    case = owned_case(session, user, case_id)
    existing = session.scalar(select(Run).where(Run.case_id == case.id, Run.idempotency_key == idempotency_key))
    if existing is not None:
        return {"run_id": str(existing.id), "status": existing.status.value, "replayed": True}
    now = request.app.state.clock.now()
    row = Run(
        case_id=case.id,
        graph=body.graph[:64],
        status=RunStatus.queued,
        idempotency_key=idempotency_key[:128],
        started_at=now,
    )
    session.add(row)
    session.flush()
    record_event(session, case, data_key(request, case), "run_created", {"run_id": str(row.id), "graph": row.graph}, now)
    return {"run_id": str(row.id), "status": row.status.value, "replayed": False}


def _owned_run(session: Session, user: User, run_id: uuid.UUID) -> Run:
    row = session.get(Run, run_id)
    if row is None:
        raise AppError("not_found", "Run was not found", status_code=404)
    owned_case(session, user, row.case_id)
    return row


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    row = _owned_run(session, user, run_id)
    return {"run_id": str(row.id), "graph": row.graph, "status": row.status.value}


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> StreamingResponse:
    row = _owned_run(session, user, run_id)
    payload = json.dumps({"run_id": str(row.id), "status": row.status.value})

    def chunks():
        yield f"data: {payload}\n\n"

    return StreamingResponse(chunks(), media_type="text/event-stream")
