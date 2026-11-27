"""The server side of the outreach graph's ports: the call's working state, the case records a call writes, the approval
rows it asks for, and the legal retriever. One of each per request; nothing is kept in process memory between turns."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.factory import get_llm
from app.config import SERVER_ROOT
from app.core.crypto import open_text, seal_text
from app.db.models import (
    Approval, ApprovalKind, ApprovalStatus, Call, Case, CaseStatus, Evidence, Fact, Notification, OutreachState, Promise, PromiseStatus, User,
)
from app.privacy.numbers import normalize_numbers
from app.services.access import record_event
from app.services.case_store import ServerCaseStore
from app.services.fact_service import read_value

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.graphs.outreach import OutreachPorts, OutreachRunner  # noqa: E402
from resolve_workflows.guards.output_guard import LLMPolicyClassifier, OutputGuard  # noqa: E402
from resolve_workflows.nodes.evidence_check import CaseEvidence, Credit  # noqa: E402

log = logging.getLogger("resolve")
ENTITY_TYPES = {"marketplace", "seller_on_marketplace", "direct_seller", "payment_intermediary", "unknown"}
CREDIT_DOC_WORDS = ("refund", "credit")  # an evidence document of this type shows money arriving


def case_evidence_of(session: Session, case: Case, key: bytes, facts: dict[str, str]) -> CaseEvidence:
    """What the code compares a provider's claim with: the stored facts and, as credits, evidence documents that show a
    refund arriving. A receipt or invoice is a purchase document, not a credit."""
    credits = []
    for row in session.scalars(select(Evidence).where(Evidence.case_id == case.id)).all():
        if not row.fields_enc or not any(w in (row.type or "") for w in CREDIT_DOC_WORDS):
            continue
        body = json.loads(open_text(row.fields_enc, key)).get("fields", {})
        credits.append(Credit(str(body.get("amount", "")), str(body.get("order_date", body.get("date", ""))), str(body.get("reference", ""))))
    refs = tuple(v for k, v in facts.items() if k == "refund_reference" and v)
    return CaseEvidence(facts.get("amount", ""), facts.get("order_date", ""), facts.get("order_id", ""), refs, tuple(c for c in credits if c.amount))


class ServerOutreachStore:
    def __init__(self, session: Session, case: Case, user: User, call: Call, key: bytes, now) -> None:
        self.session, self.case, self.user, self.call, self.key, self._now = session, case, user, call, key, now

    # -- working state, sealed with the case key --------------------------------------------------------------------
    def load_call(self, call_id: str) -> dict | None:
        row = self.session.get(OutreachState, uuid.UUID(call_id))
        return None if row is None else json.loads(open_text(row.body_enc, self.key))

    def save_call(self, call_id: str, state: dict) -> None:
        body = seal_text(json.dumps(state), self.key)
        row = self.session.get(OutreachState, uuid.UUID(call_id))
        if row is None:
            self.session.add(OutreachState(call_id=uuid.UUID(call_id), body_enc=body, updated_at=self._now()))
        else:
            row.body_enc, row.updated_at = body, self._now()
        self.session.flush()

    # -- case reads -------------------------------------------------------------------------------------------------
    def _facts(self) -> dict[str, str]:
        rows = self.session.scalars(select(Fact).where(Fact.case_id == self.case.id, Fact.superseded_by.is_(None))).all()
        return {r.field: read_value(r, self.key) for r in rows}

    def language(self, case_id: str) -> str:
        return self.user.language if self.user.language in ("en", "hi", "hinglish") else "en"

    def provider(self, case_id: str) -> dict:
        facts = self._facts()
        entity = facts.get("provider_entity_type", "unknown")
        return {"name": facts.get("company_name") or "the company", "entity_type": entity if entity in ENTITY_TYPES else "unknown"}

    def case_evidence(self, case_id: str) -> CaseEvidence:
        return case_evidence_of(self.session, self.case, self.key, self._facts())

    # -- case writes ------------------------------------------------------------------------------------------------
    def save_promise(self, case_id: str, call_id: str, who: str, what: str, by_when: str, reference: str, key: str) -> str:
        due = datetime.combine(datetime.fromisoformat(by_when).date(), time(23, 59), tzinfo=timezone.utc)
        row = Promise(
            case_id=self.case.id, who_enc=seal_text(who, self.key),
            what_enc=seal_text(json.dumps({"what": what, "reference": reference, "call_id": call_id}), self.key), by_when=due, status=PromiseStatus.open,
        )
        self.session.add(row)
        self.session.flush()
        record_event(self.session, self.case, self.key, "promise_recorded", {"promise_id": str(row.id), "by_when": by_when}, self._now())
        return str(row.id)

    def record_offer(self, case_id: str, call_id: str, offer: dict, key: str) -> None:
        record_event(self.session, self.case, self.key, "offer_recorded", {"call_id": call_id, **offer}, self._now())

    def set_status(self, case_id: str, status: str) -> None:
        self.case.status = CaseStatus(status)
        self.session.flush()

    def save_summary(self, case_id: str, call_id: str, summary: dict) -> None:
        event = record_event(self.session, self.case, self.key, "call_summary", {"call_id": call_id, **summary}, self._now())
        self.call.summary_ref = f"event:{event.id}"
        self.session.flush()


class ServerApprovalPort:
    """Creates Approval rows. The owner decides them in the approvals API, with step-up; nothing here decides one."""

    def __init__(self, session: Session, case: Case, user: User, key: bytes, master_key: bytes, now) -> None:
        self.session, self.case, self.user, self.key, self.master_key, self._now = session, case, user, key, master_key, now

    def create(self, case_id: str, kind: str, payload: dict, key: str) -> str:
        row = Approval(case_id=self.case.id, kind=ApprovalKind(kind), payload_enc=seal_text(json.dumps(payload), self.key), status=ApprovalStatus.pending)
        self.session.add(row)
        self.session.flush()
        record_event(self.session, self.case, self.key, "approval_requested", {"approval_id": str(row.id), "kind": kind}, self._now())
        self.session.add(Notification(
            user_id=self.user.id, kind="approval_requested",
            payload_enc=seal_text(json.dumps({"approval_id": str(row.id), "kind": kind, "case_id": str(self.case.id)}), self.master_key),
            channel="in_app", created_at=self._now(),
        ))
        return str(row.id)


class ServerRetriever:
    """Adapter from the legal retrieval service (app.legal.retrieval) to the graph's Retriever port."""

    def __init__(self, service) -> None:
        self.service = service

    def search(self, query: str, entity_type: str | None = None, k: int = 5):
        return self.service.search(query, entity_type, k)


class NoRetriever:
    """Used only when no embedder can be built (the model files are missing): the call goes on and says it cannot confirm a rule."""

    def search(self, query: str, entity_type: str | None = None, k: int = 5):
        raise RuntimeError("legal retrieval is not available")


def get_retriever(request, session: Session):
    state = request.app.state
    if getattr(state, "retriever", None) is not None:
        return state.retriever
    try:
        from app.legal.embeddings import FastEmbedder
        from app.legal.retrieval import RetrievalService

        if getattr(state, "embedder", None) is None:
            state.embedder = FastEmbedder()
        return ServerRetriever(RetrievalService(session, state.embedder))
    except Exception:  # noqa: BLE001 - a missing optional model must not stop a call
        log.warning("legal retrieval could not be built; calls will not cite rules")
        return NoRetriever()


def build_runner(request, session: Session, user: User, case: Case, call: Call, key: bytes) -> OutreachRunner:
    state = request.app.state
    now = state.clock.now
    llm = get_llm(request)
    case_store = ServerCaseStore(session, case, key, now, account_email="")
    case_store.account_email = _account_email(user, state)
    guard = OutputGuard(LLMPolicyClassifier(llm), events=lambda kind, body: case_store.record_event(str(case.id), kind, body), normalise=normalize_numbers)
    ports = OutreachPorts(
        llm=llm, classifier=llm, screen=llm, case_store=case_store, store=ServerOutreachStore(session, case, user, call, key, now),
        approvals=ServerApprovalPort(session, case, user, key, state.master_key, now), retriever=get_retriever(request, session), guard=guard,
        now=now, normalise=normalize_numbers,
    )
    return OutreachRunner(ports)


def _account_email(user: User, state) -> str:
    try:
        return open_text(user.email_enc, state.master_key)
    except Exception:  # noqa: BLE001
        return ""
