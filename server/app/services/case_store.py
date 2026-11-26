"""The server's implementation of the outreach graph's case store port.

Only the mandate-facing reads live here. A fact reaches the provider call only if it is current, confirmed at its
current version, and on the mandate's disclosure list (or one of the fields the provider must know to be called).
"""

from __future__ import annotations

import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SERVER_ROOT
from app.db.models import Case, ConfirmationState, Fact, FactCertainty, User
from app.services.access import record_event
from app.services.fact_service import read_value
from app.services.mandate_service import mandate_view

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.mandate import ALWAYS_ALLOWED, DisclosableFact, MandateView  # noqa: E402


class ServerCaseStore:
    def __init__(self, session: Session, case: Case, key: bytes, now, user: User | None = None) -> None:
        self.session = session
        self.case = case
        self.key = key
        self._now = now
        self.user = user

    def _current_facts(self) -> list[Fact]:
        return list(self.session.scalars(select(Fact).where(Fact.case_id == self.case.id, Fact.superseded_by.is_(None))))

    def get_mandate(self, case_id: str, version: int | None = None) -> MandateView | None:
        return mandate_view(self.session, uuid.UUID(case_id), self.key, version)

    def _allowed_fields(self, mandate_version: int) -> set[str]:
        view = self.get_mandate(str(self.case.id), mandate_version)
        return set() if view is None else set(view.disclosure) | set(ALWAYS_ALLOWED)

    def get_disclosable_facts(self, case_id: str, mandate_version: int) -> list[DisclosableFact]:
        allowed = self._allowed_fields(mandate_version)
        out = []
        for fact in self._current_facts():
            if fact.field not in allowed or fact.certainty == FactCertainty.not_stated:
                continue
            if fact.confirmation_state != ConfirmationState.confirmed or fact.confirmed_version != fact.version:
                continue  # an unconfirmed or edited value is not something the agent may say
            value = read_value(fact, self.key)
            if value:
                out.append(DisclosableFact(fact.field, value, fact.certainty.value))
        return out

    def get_undisclosable_values(self, case_id: str, mandate_version: int) -> list[str]:
        """Every stored value the mandate does not list, plus the account email. Used to scan and to mask; never spoken."""
        allowed = self._allowed_fields(mandate_version)
        values = []
        for fact in self._current_facts():
            if fact.field in allowed:
                continue
            value = read_value(fact, self.key)
            if value:
                values.append(value)
        if self.user is not None and self.user.email:
            values.append(self.user.email)
        return values

    def record_event(self, case_id: str, kind: str, body: dict) -> None:
        record_event(self.session, self.case, self.key, kind, body, self._now())
