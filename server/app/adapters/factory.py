"""Builds the real Groq client once per app. Tests put a fake on app.state.intake_llm instead."""

from __future__ import annotations

import httpx

from app.adapters.cost import CostMeter
from app.adapters.groq_llm import GroqClient

GROQ_BASE = "https://api.groq.com/openai/v1"


def get_llm(request):
    state = request.app.state
    if getattr(state, "intake_llm", None) is None:
        settings = state.settings
        http = httpx.Client(base_url=GROQ_BASE, headers={"Authorization": f"Bearer {settings.groq_api_key}"}, timeout=60)
        state.intake_llm = GroqClient(settings.load_models(), CostMeter(settings.groq_budget_usd), http)
    return state.intake_llm
