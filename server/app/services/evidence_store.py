"""Server side of the evidence graph's store port, and the function that runs the graph."""

from __future__ import annotations

import json
import logging
import sys
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.cost import shared_meter
from app.adapters.factory import GROQ_BASE, get_llm
from app.adapters.ocr import TesseractOCR
from app.adapters.vision import GroqVision
from app.config import SERVER_ROOT
from app.core.crypto import open_text, seal_text
from app.db.models import Approval, ApprovalKind, ApprovalStatus, Case, Evidence, Fact, Notification, User
from app.privacy.redact import Redactor
from app.services.access import record_event
from app.services.fact_service import read_value

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.graphs.evidence import EvidencePorts, build_evidence_graph  # noqa: E402

log = logging.getLogger("resolve")


class ServerEvidenceStore:
    def __init__(self, session: Session, case: Case, user: User, evidence: Evidence, key: bytes, objects, now, master_key: bytes = b"") -> None:
        self.session, self.case, self.user, self.row, self.key, self.objects, self._now = session, case, user, evidence, key, objects, now
        self.master_key = master_key

    def _body(self) -> dict:
        return json.loads(open_text(self.row.fields_enc, self.key)) if self.row.fields_enc else {}

    def _write(self, body: dict) -> None:
        self.row.fields_enc = seal_text(json.dumps(body), self.key)

    def image(self, evidence_id: str) -> bytes:
        return self.objects.get(str(self.case.id), self.row.file_ref, self.key)

    def request_vision_approval(self, evidence_id: str) -> str:
        if self.row.vision_approval_id:
            return str(self.row.vision_approval_id)
        approval = Approval(case_id=self.case.id, kind=ApprovalKind.send_image_to_llm,
                            payload_enc=seal_text(str(self.row.id), self.key), status=ApprovalStatus.pending)
        self.session.add(approval)
        self.session.flush()
        self.row.vision_approval_id = approval.id
        return str(approval.id)

    def approval_status(self, evidence_id: str) -> str | None:
        if not self.row.vision_approval_id:
            return None
        approval = self.session.get(Approval, self.row.vision_approval_id)
        return approval.status.value if approval else None

    def confirmed_facts(self, case_id: str) -> dict[str, str]:
        rows = self.session.scalars(select(Fact).where(Fact.case_id == self.case.id, Fact.superseded_by.is_(None))).all()
        return {r.field: read_value(r, self.key) for r in rows if r.confirmed_version == r.version}

    def save_result(self, evidence_id: str, doc_type: str, fields: dict, source: str) -> None:
        body = self._body()
        body.update({"doc_type": doc_type, "fields": fields, "source": source})
        self._write(body)
        self.row.type = doc_type[:32]
        record_event(self.session, self.case, self.key, "evidence_read", {"evidence_id": str(self.row.id), "source": source}, self._now())

    def flag(self, case_id: str, evidence_id: str, field: str, evidence_value: str, fact_value: str) -> None:
        body = self._body()
        body.setdefault("flags", []).append({"field": field, "evidence": evidence_value, "fact": fact_value})
        self._write(body)
        record_event(self.session, self.case, self.key, "evidence_contradiction", {"evidence_id": str(self.row.id), "field": field}, self._now())
        question = {"field": field, "evidence": evidence_value, "fact": fact_value, "evidence_id": str(self.row.id), "case_id": str(self.case.id)}
        self.session.add(Notification(user_id=self.user.id, kind="evidence_mismatch",
                                      payload_enc=seal_text(json.dumps(question), self.master_key), channel="in_app", created_at=self._now()))

    def set_state(self, evidence_id: str, state: str) -> None:
        body = self._body()
        body["state"] = state
        self._write(body)

    def mark_sent(self) -> None:
        self.row.sent_to_vision = True

    def today(self) -> str:
        return self._now().date().isoformat()


class _MarkingVision:
    """Records that the image left this machine, immediately before it does."""

    def __init__(self, inner, store: ServerEvidenceStore) -> None:
        self.inner, self.store = inner, store

    def read_text(self, image: bytes) -> str:
        self.store.mark_sent()
        self.store.session.flush()
        return self.inner.read_text(image)


def _vision(request):
    state = request.app.state
    if getattr(state, "evidence_vision", None) is not None:
        return state.evidence_vision
    settings = state.settings
    http = httpx.Client(base_url=GROQ_BASE, headers={"Authorization": f"Bearer {settings.groq_api_key}"}, timeout=90)
    return GroqVision(settings.load_models(), shared_meter(state), http)


def run_evidence(request, session: Session, user: User, case: Case, evidence: Evidence, key: bytes, event: str) -> dict:
    state = request.app.state
    store = ServerEvidenceStore(session, case, user, evidence, key, state.objects, state.clock.now, state.master_key)
    ocr = getattr(state, "evidence_ocr", None) or TesseractOCR()
    ports = EvidencePorts(ocr=ocr, vision=_MarkingVision(_vision(request), store), llm=get_llm(request), redactor=Redactor(), store=store)
    out = build_evidence_graph(ports).invoke({"case_id": str(case.id), "evidence_id": str(evidence.id), "event": event})
    return {"state": out.get("state", "none"), "flags": out.get("flags", [])}


def safe_run_evidence(request, session, user, case, evidence, key, event) -> dict:
    """Used after an approval decision: a vision failure must not undo the decision."""
    try:
        return run_evidence(request, session, user, case, evidence, key, event)
    except Exception:  # noqa: BLE001
        log.warning("evidence processing failed for event %s", event)
        ServerEvidenceStore(session, case, user, evidence, key, request.app.state.objects, request.app.state.clock.now, request.app.state.master_key).set_state(str(evidence.id), "failed")
        return {"state": "failed", "flags": []}


_ = uuid
