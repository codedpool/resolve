"""In-app notifications for the signed-in user."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import open_text
from app.core.errors import AppError
from app.db.models import Notification, User
from app.deps import current_user, get_session

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    rows = session.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at)).all()
    return {
        "notifications": [
            {
                "id": str(row.id),
                "kind": row.kind,
                "payload": json.loads(open_text(row.payload_enc, request.app.state.master_key)),
                "read_at": row.read_at.isoformat() if row.read_at else None,
            }
            for row in rows
        ]
    }


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    row = session.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise AppError("not_found", "Notification was not found", status_code=404)
    row.read_at = request.app.state.clock.now()
    return {"id": str(row.id), "read_at": row.read_at.isoformat()}
