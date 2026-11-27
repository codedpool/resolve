"""The server side of the follow-up graph's ports. One of each per request; nothing is kept in process memory between events.

The graph's working state is sealed with the case key. Every write the graph makes (state, timeline events, approvals,
reminders, the status) goes through the request's own database session, so a request that fails part-way rolls all of it
back and the same event can be sent again.
"""

from __future__ import annotations

import json
import sys
import uuid
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SERVER_ROOT
from app.core.crypto import open_text, seal_text
from app.db.models import Case, CaseStatus, ConfirmationState, Deadline, DeadlineStatus, Fact, FactCertainty, FollowUpState, User
from app.legal.providers import load_providers
from app.privacy.redact import Redactor
from app.runtime.run_service import once_in_session
from app.services.access import record_event
from app.services.fact_service import read_value
from app.services.outreach_store import ENTITY_TYPES, ServerApprovalPort, case_evidence_of

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.graphs.followup import GRAPH_STATUSES, FollowUpPorts, FollowUpRunner  # noqa: E402

# How sure the case is of the provider's type: a type the consumer stated or confirmed is trusted, a guess is not.
CONFIDENCE = {FactCertainty.stated: 0.9, FactCertainty.inferred: 0.55, FactCertainty.approximate: 0.4, FactCertainty.not_stated: 0.0}


@lru_cache(maxsize=1)
def _routes() -> dict[str, list[dict]]:
    routes: dict[str, list[dict]] = {}
    for provider in load_providers():
        routes[provider.entity_type.value] = [
            {"kind": t.kind, "name": t.name, "url": str(t.url) if t.url else "", "contact": t.contact or "", "source_url": str(t.source_url)}
            for t in provider.escalation_targets
        ]
    return routes


class ServerFollowUpStore:
    def __init__(self, session: Session, case: Case, user: User, key: bytes, now) -> None:
        self.session, self.case, self.user, self.key, self._now = session, case, user, key, now

    # -- working state ----------------------------------------------------------------------------------------------
    def load(self, case_id: str) -> dict | None:
        row = self.session.get(FollowUpState, uuid.UUID(case_id))
        return None if row is None else json.loads(open_text(row.body_enc, self.key))

    def save(self, case_id: str, state: dict) -> None:
        body = seal_text(json.dumps(state), self.key)
        row = self.session.get(FollowUpState, uuid.UUID(case_id))
        if row is None:
            self.session.add(FollowUpState(case_id=uuid.UUID(case_id), body_enc=body, updated_at=self._now()))
        else:
            row.body_enc, row.updated_at = body, self._now()
        self.session.flush()

    # -- case reads -------------------------------------------------------------------------------------------------
    def _facts(self) -> dict[str, Fact]:
        rows = self.session.scalars(select(Fact).where(Fact.case_id == self.case.id, Fact.superseded_by.is_(None))).all()
        return {r.field: r for r in rows}

    def provider(self, case_id: str) -> dict:
        facts = self._facts()
        kind = facts.get("provider_entity_type")
        entity = read_value(kind, self.key) if kind is not None else "unknown"
        confidence = 0.0
        if kind is not None and entity in ENTITY_TYPES:
            confidence = 0.9 if kind.confirmation_state == ConfirmationState.confirmed else CONFIDENCE[kind.certainty]
        name = read_value(facts["company_name"], self.key) if "company_name" in facts else "the company"
        return {"name": name or "the company", "entity_type": entity if entity in ENTITY_TYPES else "unknown", "confidence": confidence}

    def routes_by_type(self) -> dict[str, list[dict]]:
        return {k: [dict(r) for r in v] for k, v in _routes().items()}

    def case_evidence(self, case_id: str):
        return case_evidence_of(self.session, self.case, self.key, {f: read_value(row, self.key) for f, row in self._facts().items()})

    def case_status(self, case_id: str) -> str:
        return self.case.status.value

    # -- case writes ------------------------------------------------------------------------------------------------
    def set_status(self, case_id: str, status: str) -> None:
        if status not in GRAPH_STATUSES:  # the consumer's confirmation is not something a graph may write
            raise ValueError(f"follow-up may not set the status {status!r}")
        self.case.status = CaseStatus(status)
        self.session.flush()

    def record_event(self, case_id: str, kind: str, body: dict) -> None:
        record_event(self.session, self.case, self.key, kind, body, self._now())

    def schedule_reminder(self, case_id: str, due_at, kind: str, key: str) -> str:
        row = Deadline(case_id=self.case.id, due_at=due_at, kind=kind[:64], status=DeadlineStatus.scheduled)
        self.session.add(row)
        self.session.flush()
        return str(row.id)


def build_followup_runner(request, session: Session, user: User, case: Case, key: bytes) -> tuple[FollowUpRunner, ServerFollowUpStore]:
    from app.adapters.factory import get_llm

    state = request.app.state
    now = state.clock.now
    store = ServerFollowUpStore(session, case, user, key, now)
    llm = get_llm(request)
    ports = FollowUpPorts(
        classifier=llm, store=store, approvals=ServerApprovalPort(session, case, user, key, state.master_key, now),
        once=lambda k, fn: once_in_session(session, k, fn), now=now, redactor=Redactor(),
    )
    return FollowUpRunner(ports), store
