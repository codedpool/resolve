"""The first step of the outreach graph: no call runs without a mandate that is present, unexpired and current.

The full outreach graph starts from this gate. A blocked run does nothing else; it records one event and tells the
consumer a mandate is needed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from resolve_workflows.mandate import mandate_problem
from resolve_workflows.ports import CaseStore


class GateState(TypedDict, total=False):
    case_id: str
    mandate_version: int | None
    status: str  # ready | mandate_required
    block_reason: str


def build_mandate_gate(store: CaseStore, now: Callable[[], datetime]):
    def check_mandate(state: GateState) -> dict:
        view = store.get_mandate(state["case_id"], state.get("mandate_version"))
        problem = mandate_problem(view, now())
        if problem is None:
            return {"status": "ready", "block_reason": "", "mandate_version": view.version}
        return {"status": "mandate_required", "block_reason": problem}

    def route(state: GateState) -> str:
        return "ready" if state["status"] == "ready" else "request_mandate"

    def request_mandate(state: GateState) -> dict:
        store.record_event(state["case_id"], "outreach_blocked", {"reason": state["block_reason"]})
        return {}

    builder = StateGraph(GateState)
    builder.add_node("check_mandate", check_mandate)
    builder.add_node("request_mandate", request_mandate)
    builder.add_node("ready", lambda state: {})
    builder.add_edge(START, "check_mandate")
    builder.add_conditional_edges("check_mandate", route, {"ready": "ready", "request_mandate": "request_mandate"})
    builder.add_edge("ready", END)
    builder.add_edge("request_mandate", END)
    return builder.compile()
