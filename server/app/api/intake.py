"""Text intake. Each request runs the intake graph for one event."""

from __future__ import annotations

import sys
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.factory import get_llm
from app.config import SERVER_ROOT
from app.db.models import CaseStatus, User
from app.deps import current_user, get_session
from app.privacy.redact import Redactor
from app.services.access import data_key, owned_case
from app.services.intake_store import ServerIntakeStore

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.graphs.intake import IntakePorts, build_intake_graph  # noqa: E402

router = APIRouter(prefix="/cases", tags=["intake"])


class IntakeMessage(BaseModel):
    text: str


def _run(request: Request, session: Session, user: User, case_id: uuid.UUID, event: str, text: str = "") -> dict:
    case = owned_case(session, user, case_id)
    if case.status not in {CaseStatus.intake, CaseStatus.confirming}:
        return {"text": None, "phase": "closed", "status": case.status.value, "handoff_fields": []}
    key = data_key(request, case)
    store = ServerIntakeStore(session, case, user, key, request.app.state.clock.now)
    llm = get_llm(request)
    ports = IntakePorts(llm=llm, classifier=llm, screen=llm, redactor=Redactor(), store=store)
    out = build_intake_graph(ports).invoke({"case_id": str(case.id), "event": event, "text": text})
    return {
        "text": out.get("reply"),
        "phase": store.phase(str(case.id))["phase"],
        "status": case.status.value,
        "handoff_fields": out.get("handoff_fields", []),
    }


@router.post("/{case_id}/intake/messages")
def intake_message(
    case_id: uuid.UUID,
    body: IntakeMessage,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    return _run(request, session, user, case_id, "message", body.text)


@router.post("/{case_id}/narration-done")
def narration_done(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    return _run(request, session, user, case_id, "done")


@router.post("/{case_id}/intake/silence")
def intake_silence(
    case_id: uuid.UUID,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    return _run(request, session, user, case_id, "silence")
