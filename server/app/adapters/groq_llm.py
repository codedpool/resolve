"""Groq chat, classify, and prompt-guard calls. Model ids come from models.yaml."""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.adapters.cost import BlockedApiAccess, CostMeter, token_cost
from app.core.errors import AppError

log = logging.getLogger("resolve")


class ModelRejected(AppError):
    def __init__(self, model: str) -> None:
        super().__init__("model_rejected", "Model is not available", status_code=502, details={"model": model})


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
        content, _usage, _model = self._complete("injection", "injection", {"text": text})
        return float(content.strip())

    def _complete(self, role: str, prompt_id: str, variables: dict, schema: dict | None = None) -> tuple[str, dict, str]:
        spec = self.models["roles"][role]
        models = [spec["model"]]
        if spec.get("fallback"):
            models.append(spec["fallback"])
        last_error: Exception | None = None
        for index, model in enumerate(models):
            try:
                return self._call(model, spec, prompt_id, variables, schema)
            except ModelRejected as exc:
                last_error = exc
                if index == 0 and len(models) > 1:
                    log.warning("model %s was rejected; using %s", model, models[1])
                    continue
                raise
        raise last_error or ModelRejected(models[-1])

    def _call(self, model: str, spec: dict, prompt_id: str, variables: dict, schema: dict | None) -> tuple[str, dict, str]:
        self.meter.ensure_open()
        body: dict = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": prompt_id},
                {"role": "user", "content": json.dumps(variables)},
            ],
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
        delay = 0.5
        response: httpx.Response | None = None
        for attempt in range(3):
            response = self.http.post(path, json=body)
            if response.status_code != 429 or attempt == 2:
                return response
            retry_after = response.headers.get("retry-after")
            self.sleeper(float(retry_after) if retry_after else delay)
            delay *= 2
        return response
