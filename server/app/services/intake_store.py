"""The server's implementation of the intake store port. Working state is one sealed row per case."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import open_text, seal_text
from app.db.models import Case, CaseStatus, Event, Fact, FactCertainty, FactSource, IntakeState, User
from app.services.access import record_event
from app.services.fact_service import current_fact, propose_fact, read_value

CRITICAL = ("company_name", "amount", "order_id", "order_date", "desired_remedy")


class ServerIntakeStore:
    def __init__(self, session: Session, case: Case, user: User, key: bytes, now) -> None:
        self.session = session
        self.case = case
        self.user = user
        self.key = key
        self._now = now
        self._state: dict | None = None

    # -- sealed working state ------------------------------------------------
    def _load(self) -> dict:
        if self._state is None:
            row = self.session.get(IntakeState, self.case.id)
            self._state = (
                json.loads(open_text(row.body_enc, self.key))
                if row is not None
                else {"messages": [], "tokens": {}, "asked": [], "phase": "narrating", "asked_field": "", "silence": False}
            )
        return self._state

    def _save(self) -> None:
        state = self._load()
        body = seal_text(json.dumps(state), self.key)
        row = self.session.get(IntakeState, self.case.id)
        if row is None:
            self.session.add(IntakeState(case_id=self.case.id, body_enc=body, updated_at=self._now()))
        else:
            row.body_enc = body
            row.updated_at = self._now()
        self.session.flush()

    # -- port ----------------------------------------------------------------
    def language(self, case_id: str) -> str:
        return self.user.language

    def today(self) -> str:
        return self._now().date().isoformat()

    def tokens(self, case_id: str) -> dict[str, str]:
        return dict(self._load()["tokens"])

    def set_tokens(self, case_id: str, tokens: dict[str, str]) -> None:
        self._load()["tokens"] = dict(tokens)
        self._save()

    def append_message(self, case_id: str, text: str, redacted: str, withheld: bool) -> None:
        self._load()["messages"].append({"text": text, "redacted": redacted, "withheld": withheld})
        self._save()
        record_event(self.session, self.case, self.key, "intake_message", {"withheld": withheld}, self._now())

    def narration_redacted(self, case_id: str) -> str:
        return " ".join(m["redacted"] for m in self._load()["messages"] if not m["withheld"] and m["redacted"])

    def phase(self, case_id: str) -> dict:
        state = self._load()
        return {"phase": state["phase"], "asked_field": state["asked_field"]}

    def set_phase(self, case_id: str, phase: str, asked_field: str = "") -> None:
        state = self._load()
        state["phase"], state["asked_field"] = phase, asked_field
        self._save()

    def fact_values(self, case_id: str) -> dict[str, str]:
        rows = self.session.scalars(select(Fact).where(Fact.case_id == self.case.id, Fact.superseded_by.is_(None))).all()
        return {row.field: read_value(row, self.key) for row in rows}

    def propose(self, case_id: str, field: str, value: str, certainty: str, phrase: str, note: str) -> None:
        fact = propose_fact(
            self.session, self.case.id, field, value, FactCertainty(certainty), FactSource.consumer_said, self.key,
            phrase=phrase, normalized={"ambiguity_note": note} if note else None,
        )
        record_event(self.session, self.case, self.key, "fact_proposed", {"fact_id": str(fact.id), "field": field, "version": fact.version}, self._now())

    def asked_fields(self, case_id: str) -> list[str]:
        return list(self._load()["asked"])

    def mark_asked(self, case_id: str, field: str) -> None:
        self._load()["asked"].append(field)
        self._save()

    def silence_prompted(self, case_id: str) -> bool:
        return bool(self._load()["silence"])

    def mark_silence_prompted(self, case_id: str) -> None:
        self._load()["silence"] = True
        self._save()

    def flag_injection(self, case_id: str, score: float) -> None:
        record_event(self.session, self.case, self.key, "injection_signal", {"score": round(score, 3), "source": "consumer"}, self._now())

    def set_status(self, case_id: str, status: str) -> None:
        self.case.status = CaseStatus(status)
        self.session.flush()


def refresh_readiness(session: Session, case: Case, reconcile=None) -> None:
    """A case is ready for a mandate when every critical fact has a value, is confirmed at its current version,
    and the narration agrees with the confirmed facts (reconcile returns the open disagreements)."""
    if case.status not in {CaseStatus.confirming, CaseStatus.ready_for_mandate}:
        return
    ok = True
    for field in CRITICAL:
        fact = current_fact(session, case.id, field)
        if fact is None or fact.confirmed_version != fact.version:
            ok = False
            break
    if ok and reconcile is not None and reconcile():
        ok = False
    case.status = CaseStatus.ready_for_mandate if ok else CaseStatus.confirming
    session.flush()


_ = (uuid, Event)  # imported for type context in callers
