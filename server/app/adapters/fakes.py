"""Stand-ins for tests. They never call a vendor."""

from __future__ import annotations


class FakeLLM:
    def __init__(self, parsed: dict | None = None, text: str = "ok", label: str = "refund", confidence: float = 0.9) -> None:
        self.parsed = parsed or {"value": ""}
        self.text_value = text
        self.label = label
        self.confidence = confidence
        self.calls: list[str] = []

    def structured(self, role: str, prompt_id: str, variables: dict, schema: dict, mode: str = "instruct") -> tuple[dict, dict]:
        self.calls.append(f"structured:{role}:{prompt_id}")
        return self.parsed, {"prompt_tokens": 1, "completion_tokens": 1}

    def text(self, role: str, prompt_id: str, variables: dict, mode: str = "instruct") -> tuple[str, dict]:
        self.calls.append(f"text:{role}:{prompt_id}")
        return self.text_value, {"prompt_tokens": 1, "completion_tokens": 1}

    def classify(self, role: str, prompt_id: str, text: str, labels: list[str]) -> tuple[str, float, dict]:
        self.calls.append(f"classify:{role}")
        return self.label, self.confidence, {"prompt_tokens": 1, "completion_tokens": 1}

    def score(self, text: str) -> float:
        self.calls.append("score")
        return 0.01


class FakeTranscriber:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.calls: list[str] = []

    def transcribe(self, role: str, audio: bytes, filename: str = "clip.wav") -> dict:
        self.calls.append(role)
        return {"text": self.text, "dropped_segments": 0, "duration_seconds": 0}
