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


# -- outreach ports ---------------------------------------------------------------------------------------------------


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.t = start or datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


class FakeOutreachStore:
    """Keeps call state as JSON text, so a test proves the state is serialisable and shares nothing by reference.
    `crash_once` names store methods that raise once, to simulate a worker killed in the middle of a step."""

    def __init__(self, evidence=None, language: str = "en", provider: dict | None = None) -> None:
        from resolve_workflows.nodes.evidence_check import CaseEvidence

        self.evidence = evidence or CaseEvidence(paid_amount="4999", order_date="2026-11-12", order_id="OD43817265")
        self._language = language
        self._provider = provider or {"name": "Zeta Mart", "entity_type": "marketplace"}
        self.calls: dict[str, str] = {}
        self.promises: list[dict] = []
        self.offers: list[dict] = []
        self.statuses: list[str] = []
        self.summaries: list[dict] = []
        self.crash_once: set[str] = set()
        self._keys: set[str] = set()

    def _maybe_crash(self, name: str) -> None:
        if name in self.crash_once:
            self.crash_once.discard(name)
            raise RuntimeError(f"worker killed in {name}")

    def load_call(self, call_id: str) -> dict | None:
        import json

        raw = self.calls.get(call_id)
        return json.loads(raw) if raw is not None else None

    def save_call(self, call_id: str, state: dict) -> None:
        import json

        self._maybe_crash("save_call")
        self.calls[call_id] = json.dumps(state)

    def language(self, case_id: str) -> str:
        return self._language

    def provider(self, case_id: str) -> dict:
        return dict(self._provider)

    def case_evidence(self, case_id: str):
        return self.evidence

    def save_promise(self, case_id, call_id, who, what, by_when, reference, key) -> str:
        self._maybe_crash("save_promise")
        if key not in self._keys:
            self._keys.add(key)
            self.promises.append({"case_id": case_id, "call_id": call_id, "who": who, "what": what, "by_when": by_when, "reference": reference})
        return key

    def record_offer(self, case_id, call_id, offer, key) -> None:
        if key not in self._keys:
            self._keys.add(key)
            self.offers.append({"case_id": case_id, "call_id": call_id, **offer})

    def set_status(self, case_id: str, status: str) -> None:
        self.statuses.append(status)

    def save_summary(self, case_id, call_id, summary) -> None:
        self._maybe_crash("save_summary")
        self.summaries.append({"call_id": call_id, **summary})


class FakeApprovals:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._by_key: dict[str, str] = {}

    def create(self, case_id: str, kind: str, payload: dict, key: str) -> str:
        if key not in self._by_key:
            approval_id = f"approval-{len(self.rows) + 1}"
            self._by_key[key] = approval_id
            self.rows.append({"id": approval_id, "case_id": case_id, "kind": kind, "payload": payload, "key": key, "status": "pending"})
        return self._by_key[key]

    def of_kind(self, kind: str) -> list[dict]:
        return [r for r in self.rows if r["kind"] == kind]


class FakeChunk:
    def __init__(self, id: str, text: str, layer: str, section: str, source_title: str, review_state: str = "llm_reviewed",
                 source_url: str = "https://example.test/source") -> None:
        self.id, self.text, self.layer, self.section = id, text, layer, section
        self.source_title, self.review_state, self.source_url = source_title, review_state, source_url
        self.clause, self.fetched_at = "", "2026-11-20"


DEFAULT_CHUNKS = (
    FakeChunk("chunk-law-refund", "A seller must refund the amount paid for a cancelled order without undue delay. Where the seller's own policy states a refund period, the refund is due within that period.",
              "consumer_law", "12", "Test fixture: consumer refund rule"),
    FakeChunk("chunk-law-policy", "A term that limits a refund to a shorter period than the seller's published policy does not change what the seller has published.",
              "consumer_law", "14", "Test fixture: published policy rule"),
    FakeChunk("chunk-zeta-policy", "Zeta Mart refunds a cancelled order to the original payment method within 7 days of the cancellation.",
              "provider_policy", "policy-1", "Zeta Mart refund policy (fictional)"),
)


class FakeRetriever:
    """Word-overlap search over a few fixed chunks; the second argument is ignored like an unavailable boost."""

    def __init__(self, chunks=DEFAULT_CHUNKS, fail: bool = False) -> None:
        self.chunks, self.fail = list(chunks), fail
        self.queries: list[str] = []

    def search(self, query: str, entity_type: str | None = None, k: int = 5):
        import re

        self.queries.append(query)
        if self.fail:
            raise RuntimeError("retrieval down")
        words = set(re.findall(r"[a-z]{3,}", query.lower()))
        scored = sorted(self.chunks, key=lambda c: -len(words & set(re.findall(r"[a-z]{3,}", c.text.lower()))))
        return scored[:k]
