"""Mandate versions, expiry and revocation. One row per version; the latest row is the one that counts.

Granting again never edits a row: it adds the next version, and a run that was pinned to an older version stops.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SERVER_ROOT
from app.core.crypto import open_text, seal_text
from app.core.errors import AppError
from app.db.models import Case, Mandate
from app.services.access import record_event

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.mandate import MandateView, mandate_problem  # noqa: E402

DEFAULT_DISCLOSURE = ["order_id", "amount", "order_date", "issue_summary", "consumer_name"]


def latest_row(session: Session, case_id: uuid.UUID) -> Mandate | None:
    return session.scalar(select(Mandate).where(Mandate.case_id == case_id).order_by(Mandate.version.desc()))


def row_for_version(session: Session, case_id: uuid.UUID, version: int) -> Mandate | None:
    return session.scalar(select(Mandate).where(Mandate.case_id == case_id, Mandate.version == version))


def state_of(row: Mandate | None, now: datetime) -> str:
    """missing, revoked, expired or active, for the row alone (version currency is checked by mandate_problem)."""
    if row is None:
        return "missing"
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= now:
        return "expired"
    return "active"


def to_view(row: Mandate, latest_version: int, key: bytes) -> MandateView:
    return MandateView(
        case_id=str(row.case_id),
        version=row.version,
        latest_version=latest_version,
        goal=open_text(row.goal_enc, key),
        disclosure=tuple(json.loads(open_text(row.disclosure_enc, key))),
        allowed_actions=tuple(json.loads(open_text(row.allowed_actions_enc, key))),
        limits=json.loads(open_text(row.limits_enc, key)),
        channels=tuple(json.loads(open_text(row.channels_enc, key))),
        call_limit_seconds=row.call_limit_seconds,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


def mandate_view(session: Session, case_id: uuid.UUID, key: bytes, version: int | None = None) -> MandateView | None:
    """The mandate as the graphs see it. `version` None means the latest."""
    latest = latest_row(session, case_id)
    if latest is None:
        return None
    row = latest if version is None else row_for_version(session, case_id, version)
    return None if row is None else to_view(row, latest.version, key)


def check_outreach(session: Session, case_id: uuid.UUID, key: bytes, now: datetime, version: int | None = None) -> str | None:
    """None if the outreach graph may run, otherwise the reason: missing, revoked, expired, superseded or channel."""
    return mandate_problem(mandate_view(session, case_id, key, version), now)


def grant_mandate(
    session: Session,
    case: Case,
    key: bytes,
    now: datetime,
    *,
    goal: str = "refund",
    disclosure: list[str] | None = None,
    allowed_actions: list[str] | None = None,
    limits: dict | None = None,
    channels: list[str] | None = None,
    call_limit_seconds: int = 600,
    expires_in_days: float = 30,
) -> Mandate:
    current = latest_row(session, case.id)
    version = 1 if current is None else current.version + 1
    row = Mandate(
        case_id=case.id,
        version=version,
        goal_enc=seal_text(goal, key),
        allowed_actions_enc=seal_text(json.dumps(allowed_actions if allowed_actions is not None else ["ask_for_refund"]), key),
        disclosure_enc=seal_text(json.dumps(disclosure if disclosure is not None else list(DEFAULT_DISCLOSURE)), key),
        limits_enc=seal_text(json.dumps(limits if limits is not None else {"accept_partial": False}), key),
        channels_enc=seal_text(json.dumps(channels if channels is not None else ["simulated_call"]), key),
        call_limit_seconds=call_limit_seconds,
        expires_at=now + timedelta(days=expires_in_days),
        granted_at=now,
    )
    session.add(row)
    session.flush()
    record_event(session, case, key, "mandate_granted", {"version": version}, now)
    return row


def revoke_mandate(session: Session, case: Case, key: bytes, now: datetime) -> Mandate:
    current = latest_row(session, case.id)
    if current is None or current.revoked_at is not None:
        raise AppError("not_found", "Mandate was not found", status_code=404)
    current.revoked_at = now
    record_event(session, case, key, "mandate_revoked", {"version": current.version}, now)
    return current
