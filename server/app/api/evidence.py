"""Encrypted evidence files. Vision stays off until an approval is decided."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import seal_text
from app.core.errors import AppError
from app.db.models import Approval, ApprovalKind, ApprovalStatus, Evidence, User
from app.deps import current_user, get_session
from app.services.access import data_key, owned_case, record_event

router = APIRouter(prefix="/cases", tags=["evidence"])


@router.post("/{case_id}/evidence", status_code=201)
async def upload_evidence(
    case_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    type: str = Form("document"),
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    key = data_key(request, case)
    ref = f"{uuid.uuid4().hex}.bin"
    payload = await file.read()
    request.app.state.objects.put(str(case.id), ref, payload, key)
    row = Evidence(case_id=case.id, file_ref=ref, type=type[:32], sent_to_vision=False)
    session.add(row)
    session.flush()
    record_event(session, case, key, "evidence_uploaded", {"evidence_id": str(row.id), "type": row.type}, request.app.state.clock.now())
    return {"id": str(row.id), "type": row.type, "file_ref": row.file_ref, "sent_to_vision": False}


@router.get("/{case_id}/evidence")
def list_evidence(
    case_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    rows = session.scalars(select(Evidence).where(Evidence.case_id == case.id)).all()
    return {
        "evidence": [
            {
                "id": str(row.id),
                "type": row.type,
                "file_ref": row.file_ref,
                "sent_to_vision": row.sent_to_vision,
                "vision_approval_id": str(row.vision_approval_id) if row.vision_approval_id else None,
            }
            for row in rows
        ]
    }


@router.post("/{case_id}/evidence/{evidence_id}/approve-vision", status_code=201)
def request_vision(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    case = owned_case(session, user, case_id)
    row = session.get(Evidence, evidence_id)
    if row is None or row.case_id != case.id:
        raise AppError("not_found", "Evidence was not found", status_code=404)
    key = data_key(request, case)
    approval = Approval(
        case_id=case.id,
        kind=ApprovalKind.send_image_to_llm,
        payload_enc=seal_text(str(row.id), key),
        status=ApprovalStatus.pending,
    )
    session.add(approval)
    session.flush()
    row.vision_approval_id = approval.id
    return {"approval_id": str(approval.id), "status": approval.status.value, "sent_to_vision": row.sent_to_vision}
