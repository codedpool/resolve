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
