"""Groq chat, classify, and prompt-guard calls. Model ids come from models.yaml."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import time

import httpx

from app.adapters.cost import BlockedApiAccess, CostMeter, token_cost
from app.core.errors import AppError

log = logging.getLogger("resolve")

MAX_ATTEMPTS = 3
FIRST_DELAY = 0.5
MAX_WAIT_SECONDS = 20.0  # a longer Retry-After than this is not waited out inside a request (a call would sit silent)
_backoff_listener: contextvars.ContextVar = contextvars.ContextVar("groq_backoff_listener", default=None)


class ModelRejected(AppError):
    def __init__(self, model: str) -> None:
        super().__init__("model_rejected", "Model is not available", status_code=502, details={"model": model})


class RateLimited(AppError):
    def __init__(self, retry_after: float | None = None) -> None:
        details = None if retry_after is None else {"retry_after_seconds": round(retry_after, 1)}
        super().__init__("model_busy", "The language service is busy right now; try again shortly", status_code=503, details=details)


def _wait_seconds(response: httpx.Response, fallback: float) -> float:
    """How long Groq asks us to wait. Retry-After is seconds; anything else (a date, text, nothing) uses our own delay."""
    raw = response.headers.get("retry-after")
    try:
        return max(0.0, float(raw)) if raw is not None else fallback
    except ValueError:
        return fallback


def _rejected(response: httpx.Response) -> bool:
    if response.status_code == 404:
        return True
    if response.status_code != 400:
        return False
    text = response.text.lower()
    return "model" in text and any(word in text for word in ("not found", "decommissioned", "does not exist", "invalid"))


class GroqClient:
    def __init__(self, models: dict, meter: CostMeter, http: httpx.Client, sleeper=time.sleep) -> None:
        self.models = models
        self.meter = meter
        self.http = http
        self.sleeper = sleeper
        self.withdrawn: set[str] = set()

    @contextlib.contextmanager
    def watch_backoff(self, callback):
        """Calls `callback(seconds)` just before this thread waits out a 429, so a call can say something instead of going
        silent. The callback is not called when the wait is too long to sit through."""
        token = _backoff_listener.set(callback)
        try:
            yield
        finally:
            _backoff_listener.reset(token)

    def structured(self, role: str, prompt_id: str, variables: dict, schema: dict, mode: str = "instruct") -> tuple[dict, dict]:
        content, usage, _model = self._complete(role, prompt_id, variables, schema=schema)
        return json.loads(content), usage

    def text(self, role: str, prompt_id: str, variables: dict, mode: str = "instruct") -> tuple[str, dict]:
        content, usage, _model = self._complete(role, prompt_id, variables)
        return content, usage

    def classify(self, role: str, prompt_id: str, text: str, labels: list[str]) -> tuple[str, float, dict]:
        parsed, usage = self.structured(
            role,
            prompt_id,
            {"text": text, "labels": ", ".join(labels)},
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string", "enum": labels},
                    "confidence": {"type": "number"},
                },
                "required": ["label", "confidence"],
            },
        )
        return parsed["label"], float(parsed["confidence"]), usage

    def score(self, text: str) -> float:
        """Prompt Guard's injection probability. The model reads the raw text as the only message and answers with a number."""
        content, _usage, _model = self._complete("injection", "", {}, raw_text=text[:2000])
        return float(content.strip())

    def _complete(self, role: str, prompt_id: str, variables: dict, schema: dict | None = None, raw_text: str | None = None) -> tuple[str, dict, str]:
        spec = self.models["roles"][role]
        models = [spec["model"]]
        if spec.get("fallback"):
            models.append(spec["fallback"])
        if models[0] in self.withdrawn and len(models) > 1:
            models = models[1:]  # already known to be gone: do not spend a request finding out again
        last_error: Exception | None = None
        for index, model in enumerate(models):
            # The reasoning setting belongs to the primary model: another family may not accept the same value.
            use = spec if model == spec["model"] else {**spec, "reasoning_effort": spec.get("fallback_reasoning_effort")}
            try:
                return self._call(model, use, prompt_id, variables, schema, raw_text)
            except ModelRejected as exc:
                last_error = exc
                self.withdrawn.add(model)
                if index == 0 and len(models) > 1:
                    log.warning("model %s was rejected; using %s", model, models[1])
                    continue
                raise
        raise last_error or ModelRejected(models[-1])

    def _call(self, model: str, spec: dict, prompt_id: str, variables: dict, schema: dict | None, raw_text: str | None = None) -> tuple[str, dict, str]:
        self.meter.ensure_open()
        body: dict = {
            "model": model,
            "temperature": 0,
            "messages": (
                [{"role": "user", "content": raw_text}]
                if raw_text is not None
                else [{"role": "system", "content": prompt_id}, {"role": "user", "content": json.dumps(variables)}]
            ),
        }
        if spec.get("reasoning_effort"):
            body["reasoning_effort"] = spec["reasoning_effort"]
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": schema},
            }
        response = self._post("/chat/completions", body)
        if "blocked_api_access" in response.text:
            raise BlockedApiAccess()
        if _rejected(response):
            raise ModelRejected(model)
        if response.status_code >= 400:
            raise AppError("groq_error", "Groq request failed", status_code=502, details={"status": response.status_code})
        payload = response.json()
        usage = payload.get("usage") or {}
        self.meter.add(token_cost(self.models.get("prices") or {}, model, usage))
        content = payload["choices"][0]["message"].get("content") or ""
        log.info("groq call model=%s prompt_tokens=%s completion_tokens=%s", model, usage.get("prompt_tokens"), usage.get("completion_tokens"))
        return content, usage, model

    def _post(self, path: str, body: dict) -> httpx.Response:
        return self.send(lambda: self.http.post(path, json=body))

    def send(self, request) -> httpx.Response:
        """Runs `request()` (which builds and sends one HTTP request) and waits out a 429 as Groq asks, up to MAX_ATTEMPTS.
        Gives up with RateLimited at once when the wait asked for is too long."""
        delay = FIRST_DELAY
        for attempt in range(MAX_ATTEMPTS):
            response = request()
            if response.status_code != 429:
                return response
            wait = _wait_seconds(response, delay)
            if attempt == MAX_ATTEMPTS - 1 or wait > MAX_WAIT_SECONDS:
                raise RateLimited(wait)
            listener = _backoff_listener.get()
            if listener is not None:
                try:
                    listener(wait)
                except Exception:  # noqa: BLE001 - a listener must never stop the retry
                    log.exception("backoff listener failed")
            log.warning("groq returned 429; waiting %ss (attempt %s of %s)", round(wait, 1), attempt + 1, MAX_ATTEMPTS)
            self.sleeper(wait)
            delay *= 2
        raise RateLimited()
