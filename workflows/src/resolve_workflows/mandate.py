"""The mandate as the graphs see it, the checks that gate the outreach graph, and the provider-call context builder.

Data minimisation: the prompt for the provider call is built from the mandate and the disclosable facts only.
Values the mandate does not list are never loaded into the builder's inputs, except as a list of strings to remove
if one of them is found inside an allowed field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from resolve_workflows import prompts
from resolve_workflows.guards.matching import mask_values

# Fields the provider can see without a mandate entry: who we are calling and what kind of company it is.
ALWAYS_ALLOWED = ("company_name", "provider_entity_type")
WITHHELD = "[withheld]"


@dataclass(frozen=True)
class MandateView:
    case_id: str
    version: int
    latest_version: int
    goal: str
    disclosure: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    limits: dict
    channels: tuple[str, ...]
    call_limit_seconds: int
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class DisclosableFact:
    field: str
    value: str
    certainty: str = "stated"


class MandateBlocked(Exception):
    """Raised when the outreach graph may not run. `reason` is one of missing, revoked, expired, superseded, channel."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def mandate_problem(view: MandateView | None, now: datetime, channel: str = "simulated_call") -> str | None:
    """None when the mandate allows the call, otherwise why not."""
    if view is None:
        return "missing"
    if view.revoked_at is not None:
        return "revoked"
    if view.expires_at <= now:
        return "expired"
    if view.version != view.latest_version:
        return "superseded"  # a run pinned to an old version stops when the consumer changes the mandate
    if channel not in view.channels:
        return "channel"
    return None


@dataclass(frozen=True)
class CallContext:
    prompt: prompts.Prompt
    variables: dict
    mandate_version: int
    disclosed_fields: tuple[str, ...] = field(default_factory=tuple)

    @property
    def system_prompt(self) -> str:
        return self.prompt.text

    def render(self) -> str:
        """The exact text a model would receive: the system prompt and the case variables as JSON."""
        return self.system_prompt + "\n" + json.dumps(self.variables, ensure_ascii=False)


def build_call_context(store, case_id: str, mandate_version: int | None, now: datetime, provider_name: str, language: str = "en",
                       channel: str = "simulated_call") -> CallContext:
    """Assemble the provider-call prompt from disclosable facts only. Raises MandateBlocked if the mandate does not allow the call."""
    mandate = store.get_mandate(case_id, mandate_version)
    problem = mandate_problem(mandate, now, channel)
    if problem is not None:
        raise MandateBlocked(problem)
    facts = store.get_disclosable_facts(case_id, mandate.version)
    withheld = list(store.get_undisclosable_values(case_id, mandate.version))
    allowed = set(mandate.disclosure) | set(ALWAYS_ALLOWED)
    rows = [
        {"field": fact.field, "value": mask_values(fact.value, withheld, WITHHELD), "certainty": fact.certainty}
        for fact in sorted(facts, key=lambda f: f.field)
        if fact.field in allowed and fact.value
    ]
    variables = {
        "mandate_version": mandate.version,
        "language": language,
        "provider": mask_values(provider_name, withheld, WITHHELD),
        "goal": mask_values(mandate.goal, withheld, WITHHELD),
        "boundaries": {
            "accept_partial_settlement": False,  # never, with or without a mandate
            "accept_waiver": False,
            "call_limit_seconds": mandate.call_limit_seconds,
        },
        "disclosable_facts": rows,
    }
    return CallContext(prompts.load("provider_call"), variables, mandate.version, tuple(r["field"] for r in rows))
