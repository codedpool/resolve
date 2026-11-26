"""Ports the graphs call. The server provides the implementations."""

from __future__ import annotations

from typing import Protocol


class LLM(Protocol):
    def structured(self, role: str, prompt_id: str, variables: dict, schema: dict, mode: str = "instruct") -> tuple[dict, dict]: ...

    def text(self, role: str, prompt_id: str, variables: dict, mode: str = "instruct") -> tuple[str, dict]: ...


class Classifier(Protocol):
    def classify(self, role: str, prompt_id: str, text: str, labels: list[str]) -> tuple[str, float, dict]: ...


class InjectionScreen(Protocol):
    def score(self, text: str) -> float: ...


class Once(Protocol):
    def __call__(self, key: str, fn) -> bool: ...


class RedactionOutcome(Protocol):
    text: str
    tokens: dict[str, str]
    withheld: bool


class Redactor(Protocol):
    def redact_or_withhold(self, text: str, tokens: dict[str, str] | None = None) -> RedactionOutcome: ...

    def restore(self, text: str, tokens: dict[str, str]) -> str: ...


class IntakeStore(Protocol):
    """Everything the intake graph reads and writes for one case. Implemented by the server."""

    def language(self, case_id: str) -> str: ...

    def today(self) -> str: ...

    def tokens(self, case_id: str) -> dict[str, str]: ...

    def set_tokens(self, case_id: str, tokens: dict[str, str]) -> None: ...

    def append_message(self, case_id: str, text: str, redacted: str, withheld: bool) -> None: ...

    def narration_redacted(self, case_id: str) -> str: ...

    def phase(self, case_id: str) -> dict: ...

    def set_phase(self, case_id: str, phase: str, asked_field: str = "") -> None: ...

    def fact_values(self, case_id: str) -> dict[str, str]: ...

    def propose(self, case_id: str, field: str, value: str, certainty: str, phrase: str, note: str) -> None: ...

    def asked_fields(self, case_id: str) -> list[str]: ...

    def mark_asked(self, case_id: str, field: str) -> None: ...

    def silence_prompted(self, case_id: str) -> bool: ...

    def mark_silence_prompted(self, case_id: str) -> None: ...

    def flag_injection(self, case_id: str, score: float) -> None: ...

    def set_status(self, case_id: str, status: str) -> None: ...


class CaseStore(Protocol):
    """What the outreach graph reads from the case. Implemented by the server.

    The mandate methods are the only way the graph sees case data on a provider call: the context it builds comes
    from `get_disclosable_facts`, and `get_undisclosable_values` feeds the output guard and the masking step.
    """

    def get_mandate(self, case_id: str, version: int | None = None): ...  # -> MandateView | None; None version means the latest

    def get_disclosable_facts(self, case_id: str, mandate_version: int): ...  # -> list[DisclosableFact]

    def get_undisclosable_values(self, case_id: str, mandate_version: int) -> list[str]: ...

    def record_event(self, case_id: str, kind: str, body: dict) -> None: ...


class Chunk(Protocol):
    """A retrieved legal text chunk. `review_state` is the tag review state of the chunk
    (`unreviewed`, `llm_reviewed`, `needs_attention`, `legal_reviewed`). Optional extras the answer
    node uses when present: `source_title`, `clause`, `fetched_at`."""

    id: str
    text: str
    layer: str
    source_url: str
    section: str
    review_state: str


class Retriever(Protocol):
    def search(self, query: str, entity_type: str | None = None, k: int = 5) -> list[Chunk]: ...
