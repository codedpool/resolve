"""The server side of the output guard: builds the mandate context from the case store, wires the policy classifier to
the model client, and writes guard events to the case timeline (never the blocked sentence itself)."""

from __future__ import annotations

import sys

from app.config import SERVER_ROOT
from app.privacy.numbers import normalize_numbers
from app.services.case_store import ServerCaseStore

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.guards.output_guard import (  # noqa: E402
    GuardedSpeech, GuardVerdict, LLMPolicyClassifier, OutputGuard, build_guard_context, heard_from,
)


class ServerOutputGuard:
    """One guard per call. `llm` is the model client (None runs the deterministic layer alone and logs the degradation)."""

    def __init__(self, store: ServerCaseStore, case_id: str, mandate_version: int, llm=None, language: str = "en") -> None:
        self.store = store
        self.case_id = case_id
        self.mandate_version = mandate_version
        self.language = language
        self.heard: list[str] = []
        self.guard = OutputGuard(
            LLMPolicyClassifier(llm) if llm is not None else None,
            events=lambda kind, body: store.record_event(case_id, kind, body),
            normalise=normalize_numbers,
        )

    def hear(self, provider_text: str) -> None:
        """Remember numbers and ids the provider said, so the agent may repeat a reference or ticket back."""
        self.heard.extend(heard_from(provider_text, normalize_numbers))

    def check(self, text: str, provider_turn: str = "") -> GuardVerdict:
        ctx = build_guard_context(self.store, self.case_id, self.mandate_version, heard=tuple(self.heard))
        return self.guard.check(text, ctx, provider_turn)

    def speak(self, text: str, provider_turn: str = "") -> GuardedSpeech:
        ctx = build_guard_context(self.store, self.case_id, self.mandate_version, heard=tuple(self.heard))
        return self.guard.speak(text, ctx, provider_turn, self.language)
