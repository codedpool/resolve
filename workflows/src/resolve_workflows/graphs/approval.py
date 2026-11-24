"""One graph that pauses until a person approves, then records a single side effect."""

from __future__ import annotations

from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from resolve_workflows.state import CaseState


def decide(state: CaseState) -> dict:
    decision = interrupt({"kind": "summary", "case_id": state["case_id"]})
    config = get_config()["configurable"]

    def effect() -> None:
        config["effects"].append(state["case_id"])
        if config.get("crash"):
            config["crash"] = False
            raise RuntimeError("worker killed")

    config["once"](f"decide:{state['case_id']}", effect)
    return {"status": "approved" if decision == "approve" else "rejected"}


def build_approval_graph(checkpointer):
    builder = StateGraph(CaseState)
    builder.add_node("decide", decide)
    builder.add_edge(START, "decide")
    builder.add_edge("decide", END)
    return builder.compile(checkpointer=checkpointer)
