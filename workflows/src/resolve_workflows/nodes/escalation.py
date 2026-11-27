"""select_escalation_target: where a complaint can go next, chosen from the provider's entity type.

Each entity type has its own ordered list of escalation routes (the first is the usual first step). When the type is
known and the case holds it with enough confidence, the first route of that type is selected and the rest of the
type's routes are shown as alternatives. When the type is `unknown`, missing or held with low confidence, nothing is
selected: every distinct route across all types is returned, and the consumer chooses. The graph never picks a route
on a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LOW_CONFIDENCE = 0.6
ENTITY_TYPES = ("marketplace", "seller_on_marketplace", "direct_seller", "payment_intermediary", "unknown")


@dataclass(frozen=True)
class Selection:
    entity_type: str
    needs_choice: bool
    selected: dict | None = None  # the route picked from the type, None when the consumer must choose
    candidates: tuple[dict, ...] = field(default_factory=tuple)  # every route the consumer may choose among
    reason: str = ""  # known | unknown_type | low_confidence | no_routes

    def as_dict(self) -> dict:
        return {
            "entity_type": self.entity_type, "needs_choice": self.needs_choice, "selected": self.selected,
            "candidates": list(self.candidates), "reason": self.reason,
        }


def _distinct(routes) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for route in routes:
        if route["kind"] not in seen:
            seen.add(route["kind"])
            out.append(dict(route))
    return out


def select_escalation_target(entity_type: str, confidence: float, routes_by_type: dict[str, list[dict]]) -> Selection:
    """`routes_by_type` maps an entity type to its ordered routes (each a dict with at least `kind` and `name`)."""
    everything = _distinct(r for routes in routes_by_type.values() for r in routes)
    known = entity_type in routes_by_type and entity_type != "unknown" and routes_by_type[entity_type]
    if not known:
        reason = "unknown_type" if entity_type in ("unknown", "", None) or entity_type not in ENTITY_TYPES else "no_routes"
        return Selection(entity_type or "unknown", True, None, tuple(everything), reason)
    if confidence < LOW_CONFIDENCE:
        return Selection(entity_type, True, None, tuple(everything), "low_confidence")
    own = _distinct(routes_by_type[entity_type])
    return Selection(entity_type, False, own[0], tuple(own), "known")


def choose(selection: Selection, kind: str) -> dict | None:
    """The route of that kind, if the consumer may choose it. The consumer picks among the candidates only."""
    return next((dict(r) for r in selection.candidates if r["kind"] == kind), None)
