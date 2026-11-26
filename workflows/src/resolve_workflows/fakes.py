"""Stand-ins for the ports, for tests and for the text harness. They never touch a database or a vendor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from resolve_workflows.mandate import ALWAYS_ALLOWED, DisclosableFact, MandateView


def make_mandate(case_id: str = "case-1", version: int = 1, latest_version: int | None = None, disclosure=("order_id", "amount"),
                 now: datetime | None = None, days: float = 30, revoked: bool = False, goal: str = "refund of the order",
                 limits: dict | None = None) -> MandateView:
    now = now or datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
    return MandateView(
        case_id=case_id, version=version, latest_version=latest_version or version, goal=goal, disclosure=tuple(disclosure),
        allowed_actions=("ask_for_refund",), limits=limits or {"accept_partial": False}, channels=("simulated_call",),
        call_limit_seconds=600, expires_at=now + timedelta(days=days), revoked_at=now if revoked else None,
    )


class FakeCaseStore:
    """Holds mandate versions and every fact of one case, including the ones no mandate lists."""

    def __init__(self, facts: dict[str, str] | None = None, mandates: list[MandateView] | None = None,
                 certainty: dict[str, str] | None = None) -> None:
        self.facts = dict(facts or {})
        self.certainty = dict(certainty or {})
        self.mandates = list(mandates or [])
        self.events: list[tuple[str, str, dict]] = []

    def get_mandate(self, case_id: str, version: int | None = None) -> MandateView | None:
        if not self.mandates:
            return None
        latest = max(m.version for m in self.mandates)
        wanted = latest if version is None else version
        for m in self.mandates:
            if m.version == wanted:
                return MandateView(**{**m.__dict__, "latest_version": latest})
        return None

    def _allowed(self, version: int) -> set[str]:
        view = self.get_mandate("", version)
        return (set(view.disclosure) | set(ALWAYS_ALLOWED)) if view else set()

    def get_disclosable_facts(self, case_id: str, mandate_version: int) -> list[DisclosableFact]:
        allowed = self._allowed(mandate_version)
        return [DisclosableFact(f, v, self.certainty.get(f, "stated")) for f, v in self.facts.items() if f in allowed and v]

    def get_undisclosable_values(self, case_id: str, mandate_version: int) -> list[str]:
        allowed = self._allowed(mandate_version)
        return [v for f, v in self.facts.items() if f not in allowed and v]

    def record_event(self, case_id: str, kind: str, body: dict) -> None:
        self.events.append((case_id, kind, body))
