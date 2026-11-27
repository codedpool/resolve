"""Deadline scan. Due rows become one outbox job each."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Case, CaseStatus, Deadline, DeadlineStatus
from app.services.outbox import deliver_in_app, drain, enqueue

SETTLED = {CaseStatus.deleted, CaseStatus.closed, CaseStatus.resolved_consumer_confirmed}


def fire_due_deadlines(session: Session, clock, master_key: bytes) -> int:
    now = clock.now()
    due = session.scalars(
        select(Deadline).where(Deadline.status == DeadlineStatus.scheduled, Deadline.due_at <= now)
    ).all()
    created = 0
    for row in due:
        case = session.get(Case, row.case_id)
        if case is None or case.status in SETTLED:  # nobody is waiting for a reminder on a settled case
            row.status = DeadlineStatus.cancelled
            continue
        _, fresh = enqueue(
            session,
            key=f"deadline:{row.id}",
            kind="deadline",
            payload={"deadline_id": str(row.id), "deadline_kind": row.kind, "case_id": str(row.case_id)},
            master_key=master_key,
            when=now,
            user_id=case.user_id,
        )
        if fresh:
            created += 1
    return created


def run_due(session: Session, clock, master_key: bytes) -> int:
    """One scheduler tick: due deadlines become jobs, and due jobs become in-app notifications. Safe to run any number
    of times; a deadline notifies once."""
    fire_due_deadlines(session, clock, master_key)
    return drain(session, clock, master_key, deliver_in_app)
