from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from resolve_workflows.graphs.approval import build_approval_graph


def _once_store():
    seen: set[str] = set()

    def once(key: str, fn) -> bool:
        if key in seen:
            return False
        seen.add(key)
        fn()
        return True

    return once


def test_graph_pauses_for_approval_and_resumes():
    graph = build_approval_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "t1", "once": _once_store(), "effects": [], "crash": False}}
    graph.invoke({"case_id": "case-1", "status": "start"}, config)
    paused = graph.get_state(config)
    assert paused.interrupts
    assert paused.interrupts[0].value["kind"] == "summary"
    graph.invoke(Command(resume="approve"), config)
    assert graph.get_state(config).values["status"] == "approved"
    assert config["configurable"]["effects"] == ["case-1"]


def test_killed_worker_does_not_repeat_the_side_effect():
    graph = build_approval_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "t2", "once": _once_store(), "effects": [], "crash": False}}
    graph.invoke({"case_id": "case-2", "status": "start"}, config)
    config["configurable"]["crash"] = True
    try:
        graph.invoke(Command(resume="approve"), config)
    except RuntimeError as exc:
        assert "killed" in str(exc)
    assert config["configurable"]["effects"] == ["case-2"]
    graph.invoke(Command(resume="approve"), config)
    assert config["configurable"]["effects"] == ["case-2"]
    assert graph.get_state(config).values["status"] == "approved"
