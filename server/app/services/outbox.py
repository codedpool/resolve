"""Outbox worker. A failed send waits, then runs once."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import open_text, seal_text
from app.db.models import Deadline, DeadlineStatus, Notification, OutboxJob


def enqueue(session: Session, key: str, kind: str, payload: dict, master_key: bytes, when, user_id) -> tuple[OutboxJob, bool]:
    existing = session.scalar(select(OutboxJob).where(OutboxJob.idempotency_key == key))
    if existing is not None:
        return existing, False
    row = OutboxJob(
        idempotency_key=key[:128],
        kind=kind[:64],
        payload_enc=seal_text(json.dumps(payload), master_key),
        status="pending",
        attempts=0,
        next_attempt_at=when,
        user_id=user_id,
    )
    session.add(row)
    session.flush()
    return row, True


def deliver_in_app(session: Session, job: OutboxJob, master_key: bytes, clock) -> None:
    if job.kind != "deadline" or job.user_id is None:
        return
    body = json.loads(open_text(job.payload_enc, master_key))
    deadline = session.get(Deadline, uuid.UUID(body["deadline_id"]))
    if deadline is not None and deadline.status == DeadlineStatus.scheduled:
        deadline.status = DeadlineStatus.fired
    session.add(
        Notification(
            user_id=job.user_id,
            kind="deadline",
            payload_enc=seal_text(json.dumps(body), master_key),
            channel="in_app",
            created_at=clock.now(),
        )
    )


def drain(session: Session, clock, master_key: bytes, sender) -> int:
    now = clock.now()
    rows = session.scalars(
        select(OutboxJob).where(OutboxJob.status != "sent", OutboxJob.next_attempt_at <= now, OutboxJob.attempts < 5)
    ).all()
    sent = 0
    for row in rows:
        try:
            sender(session, row, master_key, clock)
        except Exception:
            row.attempts += 1
            row.status = "failed"
            row.next_attempt_at = now + timedelta(seconds=2**row.attempts)
            continue
        row.status = "sent"
        sent += 1
    session.flush()
    return sent
