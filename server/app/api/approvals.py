"""Approvals are decided only by the signed-in owner, after step-up."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import open_text, seal_text
from app.core.errors import AppError
from app.db.models import Approval, ApprovalStatus, Evidence, Notification, User
from app.deps import current_user, get_session, require_step_up
from app.services.access import data_key, owned_case, record_event

router = APIRouter(tags=["approvals"])


class DecisionBody(BaseModel):
    decision: str


@router.get("/approvals")
def list_approvals(
    request: Request,
    case: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    owned = owned_case(session, user, case)
    key = data_key(request, owned)
    rows = session.scalars(select(Approval).where(Approval.case_id == owned.id)).all()
    return {
        "approvals": [
            {
                "id": str(row.id),
                "kind": row.kind.value,
                "status": row.status.value,
                "payload": open_text(row.payload_enc, key),
            }
            for row in rows
        ]
    }


@router.post("/approvals/{approval_id}/decision")
def decide(
    approval_id: uuid.UUID,
    body: DecisionBody,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(require_step_up),
) -> dict:
    row = session.get(Approval, approval_id)
    if row is None:
        raise AppError("not_found", "Approval was not found", status_code=404)
    case = owned_case(session, user, row.case_id)
    if body.decision not in {"approve", "reject"}:
        raise AppError("bad_decision", "Decision must be approve or reject", status_code=400)
    if row.status != ApprovalStatus.pending:
        raise AppError("already_decided", "Approval was already decided", status_code=409)
    now = request.app.state.clock.now()
    row.status = ApprovalStatus.approved if body.decision == "approve" else ApprovalStatus.rejected
    row.decided_at = now
    if row.status == ApprovalStatus.approved:
        evidence = session.scalar(select(Evidence).where(Evidence.vision_approval_id == row.id))
        if evidence is not None:
            evidence.sent_to_vision = True
    key = data_key(request, case)
    record_event(session, case, key, "approval_decided", {"approval_id": str(row.id), "decision": body.decision}, now)
    session.add(
        Notification(
            user_id=user.id,
            kind="approval_decided",
            payload_enc=seal_text(json.dumps({"approval_id": str(row.id), "decision": body.decision}), request.app.state.master_key),
            channel="in_app",
            created_at=now,
        )
    )
    return {"id": str(row.id), "status": row.status.value}
