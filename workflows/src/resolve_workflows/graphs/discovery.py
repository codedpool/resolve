"""Discovery graph: find the right place to send a complaint, and store it only after the owner approves it.

`start` searches the company's pages, ranks the contacts it finds, and either asks the owner to approve the clear
winner or asks the consumer to choose when the pages do not give one. Rejecting a contact searches again without it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from resolve_workflows.nodes.contacts import Candidate, Page, confident, extract, rank

MAX_ROUNDS = 2


class PageSource(Protocol):
    def search(self, company: str) -> tuple[str, list[Page]]:
        """Returns (the company's own domain, pages found). Saved pages in tests, the web later."""


class ContactStore(Protocol):
    def company_name(self, case_id: str) -> str: ...

    def contact(self, case_id: str) -> dict | None: ...

    def rejected(self, case_id: str) -> list[str]: ...

    def add_rejected(self, case_id: str, value: str) -> None: ...

    def pending(self, case_id: str) -> dict | None: ...

    def set_pending(self, case_id: str, candidate: dict | None) -> None: ...

    def request_approval(self, case_id: str, candidate: dict) -> str: ...

    def approval_status(self, case_id: str) -> str | None: ...

    def save_contact(self, case_id: str, candidate: dict) -> None: ...

    def ask_consumer(self, case_id: str, options: list[dict]) -> None: ...


class DiscoveryState(TypedDict, total=False):
    case_id: str
    event: str  # start | approval_decided | consumer_choice
    choice: dict
    state: str  # contact_known | waiting_approval | needs_consumer | stored | gave_up
    options: list[dict]


@dataclass
class DiscoveryPorts:
    pages: PageSource
    store: ContactStore


def build_discovery_graph(ports: DiscoveryPorts):
    store = ports.store

    def route(state: DiscoveryState) -> str:
        return {"start": "start", "approval_decided": "decided", "consumer_choice": "choice"}[state["event"]]

    def _find(case_id: str) -> list[Candidate]:
        domain, pages = ports.pages.search(store.company_name(case_id))
        found: list[Candidate] = []
        for page in pages:
            found.extend(extract(page, domain))
        return rank(found, store.rejected(case_id))

    def _propose(case_id: str) -> dict:
        ranked = _find(case_id)
        if confident(ranked):
            candidate = ranked[0].as_dict()
            store.set_pending(case_id, candidate)
            store.request_approval(case_id, candidate)
            return {"state": "waiting_approval", "options": [candidate]}
        options = [c.as_dict() for c in ranked[:3]]
        store.ask_consumer(case_id, options)
        return {"state": "needs_consumer", "options": options}

    def start(state: DiscoveryState) -> dict:
        if store.contact(state["case_id"]):
            return {"state": "contact_known"}
        return _propose(state["case_id"])

    def decided(state: DiscoveryState) -> dict:
        case_id = state["case_id"]
        pending = store.pending(case_id)
        status = store.approval_status(case_id)  # read from the stored Approval, never from the event
        if pending is None or status not in {"approved", "rejected"}:
            return {"state": "waiting_approval" if pending else "gave_up"}
        if status == "approved":
            store.save_contact(case_id, pending)
            store.set_pending(case_id, None)
            return {"state": "stored", "options": [pending]}
        store.add_rejected(case_id, pending["value"])
        store.set_pending(case_id, None)
        if len(store.rejected(case_id)) >= MAX_ROUNDS + 1:
            return {"state": "gave_up"}
        return _propose(case_id)

    def choice(state: DiscoveryState) -> dict:
        case_id = state["case_id"]
        candidate = dict(state["choice"], official=state["choice"].get("official", False))
        store.set_pending(case_id, candidate)
        store.request_approval(case_id, candidate)  # a contact the consumer typed still needs the approval before it is stored
        return {"state": "waiting_approval", "options": [candidate]}

    b = StateGraph(DiscoveryState)
    b.add_node("start", start)
    b.add_node("decided", decided)
    b.add_node("choice", choice)
    b.add_conditional_edges(START, route, {"start": "start", "decided": "decided", "choice": "choice"})
    for node in ("start", "decided", "choice"):
        b.add_edge(node, END)
    return b.compile()
