"""Runs one intake event for a case. Shared by the REST routes and the voice gateway."""

from __future__ import annotations

import sys
import uuid

from sqlalchemy.orm import Session

from app.adapters.factory import get_llm
from app.config import SERVER_ROOT
from app.db.models import CaseStatus, User
from app.privacy.redact import Redactor
from app.services.access import data_key, owned_case
from app.services.intake_store import ServerIntakeStore

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.graphs.intake import IntakePorts, build_intake_graph  # noqa: E402


def run_intake_event(holder, session: Session, user: User, case_id: uuid.UUID, event: str, text: str = "") -> dict:
    """`holder` is anything with an `.app` (a Request or a WebSocket)."""
    case = owned_case(session, user, case_id)
    if case.status not in {CaseStatus.intake, CaseStatus.confirming}:
        return {"text": None, "phase": "closed", "status": case.status.value, "handoff_fields": []}
    key = data_key(holder, case)
    store = ServerIntakeStore(session, case, user, key, holder.app.state.clock.now)
    llm = get_llm(holder)
    ports = IntakePorts(llm=llm, classifier=llm, screen=llm, redactor=Redactor(), store=store)
    out = build_intake_graph(ports).invoke({"case_id": str(case.id), "event": event, "text": text})
    return {
        "text": out.get("reply"),
        "phase": store.phase(str(case.id))["phase"],
        "status": case.status.value,
        "handoff_fields": out.get("handoff_fields", []),
    }
