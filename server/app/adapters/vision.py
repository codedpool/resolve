"""Vision read through Groq. Called only after the owner approves that specific image."""

from __future__ import annotations

import base64

import httpx

from app.adapters.cost import CostMeter, token_cost
from app.core.errors import AppError

PROMPT = "Read all the text in this image exactly as written. Return only the text, line by line. If there is no text, return nothing."


class GroqVision:
    def __init__(self, models: dict, meter: CostMeter, http: httpx.Client) -> None:
        self.models, self.meter, self.http = models, meter, http

    def read_text(self, image: bytes) -> str:
        self.meter.ensure_open()
        spec = self.models["roles"]["extract"]
        encoded = base64.b64encode(image).decode()
        body = {
            "model": spec["model"],
            "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ]}],
        }
        if spec.get("reasoning_effort"):
            body["reasoning_effort"] = spec["reasoning_effort"]
        response = self.http.post("/chat/completions", json=body)
        if response.status_code >= 400:
            raise AppError("groq_error", "Vision request failed", status_code=502, details={"status": response.status_code})
        payload = response.json()
        self.meter.add(token_cost(self.models.get("prices") or {}, spec["model"], payload.get("usage") or {}))
        return payload["choices"][0]["message"].get("content") or ""
