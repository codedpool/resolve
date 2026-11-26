"""A small Groq client for the eval runner only (the server has the production adapter)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import yaml


class GroqLLM:
    def __init__(self, models_path: Path, env_path: Path) -> None:
        self.models = yaml.safe_load(models_path.read_text(encoding="utf-8"))
        if env_path.is_file():
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        self.http = httpx.Client(
            base_url="https://api.groq.com/openai/v1",
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
            timeout=120,
        )
        self.cost = 0.0

    def model_for(self, role: str) -> str:
        return self.models["roles"][role]["model"]

    def structured(self, role: str, prompt_text: str, variables: dict, schema: dict, mode: str = "instruct"):
        spec = self.models["roles"][role]
        body = {
            "model": spec["model"],
            "temperature": 0,
            "messages": [{"role": "system", "content": prompt_text}, {"role": "user", "content": json.dumps(variables, ensure_ascii=False)}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": schema}},
        }
        if spec.get("reasoning_effort"):
            body["reasoning_effort"] = spec["reasoning_effort"]
        for attempt in range(6):
            response = self.http.post("/chat/completions", json=body)
            if response.status_code == 429:
                time.sleep(float(response.headers.get("retry-after", 2 + attempt * 2)))
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"groq {response.status_code}: {response.text[:200]}")
            payload = response.json()
            usage = payload.get("usage") or {}
            price = (self.models.get("prices") or {}).get(spec["model"], {})
            self.cost += usage.get("prompt_tokens", 0) / 1e6 * price.get("input_per_million", 0)
            self.cost += usage.get("completion_tokens", 0) / 1e6 * price.get("output_per_million", 0)
            return json.loads(payload["choices"][0]["message"]["content"]), usage
        raise RuntimeError("groq rate limited")
