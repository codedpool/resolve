"""Spend against the Groq budget. A call is refused once the cap is reached."""

from __future__ import annotations

from app.core.errors import AppError


class BudgetExceeded(AppError):
    def __init__(self, spent: float, limit: float) -> None:
        super().__init__(
            "budget_exceeded",
            "Groq budget is used up",
            status_code=402,
            details={"spent_usd": round(spent, 6), "limit_usd": limit},
        )


class BlockedApiAccess(AppError):
    def __init__(self) -> None:
        super().__init__("blocked_api_access", "Groq blocked the call", status_code=400)


class CostMeter:
    def __init__(self, limit_usd: float) -> None:
        self.limit_usd = limit_usd
        self.spent_usd = 0.0

    def ensure_open(self) -> None:
        if self.spent_usd >= self.limit_usd:
            raise BudgetExceeded(self.spent_usd, self.limit_usd)

    def add(self, usd: float) -> None:
        """Record what a finished call cost. The call that crosses the cap keeps its answer (it is already paid for); the next
        call is the one that is refused."""
        self.spent_usd += usd


def token_cost(prices: dict, model: str, usage: dict | None) -> float:
    if not usage:
        return 0.0
    row = prices.get(model) or {}
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    return (prompt * float(row.get("input_per_million") or 0) + completion * float(row.get("output_per_million") or 0)) / 1_000_000


def audio_cost(prices: dict, model: str, seconds: float) -> float:
    row = prices.get(model) or {}
    billed = max(seconds, 10.0)
    return float(row.get("per_audio_hour") or 0) * (billed / 3600)


def shared_meter(state) -> CostMeter:
    """One meter per app, so the chat, vision and speech clients all spend from the same budget."""
    meter = getattr(state, "cost_meter", None)
    if meter is None:
        meter = state.cost_meter = CostMeter(state.settings.groq_budget_usd)
    return meter
