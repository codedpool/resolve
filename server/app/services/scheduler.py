"""Deadline scan. Due rows become one outbox job each."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Case, Deadline, DeadlineStatus
from app.services.outbox import enqueue


def fire_due_deadlines(session: Session, clock, master_key: bytes) -> int:
    now = clock.now()
    due = session.scalars(
        select(Deadline).where(Deadline.status == DeadlineStatus.scheduled, Deadline.due_at <= now)
    ).all()
    created = 0
    for row in due:
        case = session.get(Case, row.case_id)
        _, fresh = enqueue(
            session,
            key=f"deadline:{row.id}",
            kind="deadline",
            payload={"deadline_id": str(row.id), "deadline_kind": row.kind},
            master_key=master_key,
            when=now,
            user_id=case.user_id if case is not None else None,
        )
        if fresh:
            created += 1
    return created
