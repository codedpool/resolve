"""Runs the approval graph on a background thread and resumes it from an approval."""

from __future__ import annotations

import json
import sys
import threading
import uuid
from datetime import datetime, timezone

import psycopg
from sqlalchemy.orm import Session

from app.config import SERVER_ROOT
from app.core.crypto import seal_text, unwrap_data_key
from app.db.models import Approval, ApprovalKind, ApprovalStatus, Case, Run, RunStatus, SideEffect
from app.runtime.checkpointer import PostgresThreadSaver

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from langgraph.types import Command  # noqa: E402
from resolve_workflows.graphs.approval import build_approval_graph  # noqa: E402


def once(session_factory, key: str, fn) -> bool:
    session = session_factory()
    try:
        if session.get(SideEffect, key) is not None:
            return False
        session.add(SideEffect(key=key, created_at=datetime.now(timezone.utc)))
        session.commit()
    finally:
        session.close()
    fn()
    return True


def _plain_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def drop_case_checkpoints(database_url: str, thread_ids: list[str]) -> None:
    if not thread_ids:
        return
    with psycopg.connect(_plain_url(database_url), autocommit=True) as conn:
        exists = conn.execute("SELECT to_regclass('checkpoints.threads')").fetchone()[0]
        if exists is None:
            return
        conn.execute("DELETE FROM checkpoints.threads WHERE thread_id = ANY(%s)", (thread_ids,))


def get_runner(request) -> GraphRunner:
    runner = getattr(request.app.state, "runner", None)
    if runner is None:
        runner = GraphRunner(
            request.app.state.session_factory,
            request.app.state.settings.database_url,
            request.app.state.master_key,
        )
        request.app.state.runner = runner
    return runner


class GraphRunner:
    def __init__(self, session_factory, database_url: str, master_key: bytes) -> None:
        self.session_factory = session_factory
        self.master_key = master_key
        self.saver = PostgresThreadSaver(database_url)
        self.effects: list[str] = []
        self.crash = False
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(self, run_id: str) -> None:
        self._spawn(run_id, None)

    def resume(self, run_id: str, decision: str) -> None:
        self._spawn(run_id, decision)

    def wait(self, run_id: str, timeout: float = 5) -> None:
        thread = self._threads.get(run_id)
        if thread is not None:
            thread.join(timeout)

    def _spawn(self, run_id: str, decision: str | None) -> None:
        thread = threading.Thread(target=self._execute, args=(run_id, decision), daemon=True)
        with self._lock:
            self._threads[run_id] = thread
        thread.start()

    def _execute(self, run_id: str, decision: str | None) -> None:
        session = self.session_factory()
        try:
            run = session.get(Run, uuid.UUID(run_id))
            if run is None:
                return
            graph = build_approval_graph(self.saver)
            config = {
                "configurable": {
                    "thread_id": run_id,
                    "once": lambda key, fn: once(self.session_factory, key, fn),
                    "effects": self.effects,
                    "crash": self.crash,
                }
            }
            if decision is None:
                graph.invoke({"case_id": str(run.case_id), "status": "start"}, config)
                state = graph.get_state(config)
                if state.interrupts:
                    self._pause_for_approval(session, run, state.interrupts[0].value["kind"])
                else:
                    run.status = RunStatus.completed
                    run.ended_at = datetime.now(timezone.utc)
            else:
                graph.invoke(Command(resume=decision), config)
                run.status = RunStatus.completed
                run.ended_at = datetime.now(timezone.utc)
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def _pause_for_approval(self, session: Session, run: Run, kind: str) -> None:
        case = session.get(Case, run.case_id)
        key = unwrap_data_key(case.data_key_enc, self.master_key)
        approval = Approval(
            case_id=run.case_id,
            kind=ApprovalKind(kind),
            payload_enc=seal_text(json.dumps({"run_id": str(run.id), "kind": kind}), key),
            status=ApprovalStatus.pending,
        )
        session.add(approval)
        run.status = RunStatus.paused_for_approval
