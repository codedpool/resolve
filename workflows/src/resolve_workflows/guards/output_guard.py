"""The output guard: every sentence the agent is about to say on a provider call passes this first.

Layer 1 is deterministic code and always runs: registered values the mandate does not allow (plus planted canaries),
digit runs that look like codes or cards, amounts and order ids that differ from the stored ones, and phrase rules for
settlement acceptance, counters, commitments, identity claims and legal threats in English, Hindi and Hinglish.
Layer 2 is a policy classifier (role `guard_policy`) that reads the mandate written as a policy. If the classifier is
unavailable or returns something unusable, layer 1 alone decides and the degradation is logged.
A blocked sentence is replaced by a holding phrase and never spoken. Event bodies never contain the sentence itself:
a leaked value must not be copied into a log.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

from resolve_workflows import prompts
from resolve_workflows.guards import rules
from resolve_workflows.guards.matching import digit_runs, digit_variants, find_values, is_digit_value, normalise_text

CATEGORIES = (
    "unlisted_disclosure", "otp_or_card", "settlement_acceptance", "settlement_counter", "commitment", "identity_claim",
    "legal_threat", "number_mismatch", "other",
)
HOLDING = {
    "en": "I will need to check that with the customer.",
    "hi": "मुझे यह ग्राहक से पूछकर देखना होगा।",
    "hinglish": "Mujhe yeh customer se check karna hoga.",
}


@dataclass(frozen=True)
class GuardContext:
    """What the guard knows about the current mandate. Built by the server from the case store."""

    mandate_version: int
    disclosable: dict[str, str]  # field -> value, the only case data the agent may say
    undisclosable: tuple[str, ...] = ()  # stored values the mandate does not list; never spoken
    canaries: tuple[str, ...] = ()  # extra decoy values that must never appear
    goal: str = ""
    consumer_name: str = ""
    heard_values: tuple[str, ...] = ()  # numbers and ids the provider said on this call (references, tickets, offers)

    def allowed_text(self, extra: str = "") -> str:
        return " | ".join([*self.disclosable.values(), self.goal, *self.heard_values, extra])


@dataclass
class GuardVerdict:
    blocked: bool
    categories: list[str] = field(default_factory=list)
    rationale: str = ""
    layers: list[str] = field(default_factory=list)  # which layers raised the block
    degraded: bool = False  # the classifier layer could not run


@dataclass
class GuardedSpeech:
    text: str  # what may be spoken: the original sentence, or the holding phrase
    verdict: GuardVerdict


class PolicyClassifier(Protocol):
    def classify(self, text: str, policy: str, provider_turn: str) -> dict: ...  # {violation, categories, rationale}


def policy_json_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "violation": {"type": "boolean"},
            "categories": {"type": "array", "items": {"type": "string", "enum": list(CATEGORIES)}},
            "rationale": {"type": "string"},
        },
        "required": ["violation", "categories", "rationale"],
    }


def mandate_policy(ctx: GuardContext) -> str:
    """The mandate written as a policy for the classifier. Allowed values are shown; stored secrets never are."""
    lines = [f"Mandate version {ctx.mandate_version}. Goal: {ctx.goal or 'ask for the refund'}."]
    if ctx.disclosable:
        lines.append("The agent may state exactly these facts about the consumer:")
        lines += [f"- {name}: {value}" for name, value in ctx.disclosable.items()]
    else:
        lines.append("The agent may state no facts about the consumer.")
    lines.append("Any other personal or account detail (phone, email, address, identity or tax numbers, bank, card, UPI, birth date, passwords) is not allowed.")
    return "\n".join(lines)


class LLMPolicyClassifier:
    """Policy check on the `guard_policy` role through the LLM port."""

    def __init__(self, llm, role: str = "guard_policy") -> None:
        self.llm, self.role = llm, role

    def classify(self, text: str, policy: str, provider_turn: str) -> dict:
        prompt = prompts.load("guard_policy")
        parsed, _usage = self.llm.structured(
            self.role, prompt.text, {"policy": policy, "provider_said": provider_turn, "agent_sentence": text}, policy_json_schema()
        )
        return parsed


def heard_from(provider_text: str, normalise: Callable[[str], str] | None = None) -> tuple[str, ...]:
    """Numbers and ids in a provider utterance that the agent may repeat back (reference, ticket, offered amount)."""
    text = normalise_text(normalise(provider_text) if normalise else provider_text)
    out = [run[3] for run in digit_runs(text)]
    out += [m.group(1) for m in rules.ORDER_ID.finditer(text)]
    out += [t for t in re.findall(r"[a-z]+(?:-[a-z0-9]+){1,4}", text) if any(c.isdigit() for c in t)]
    return tuple(dict.fromkeys(out))


class OutputGuard:
    def __init__(self, classifier: PolicyClassifier | None = None, events: Callable[[str, dict], None] | None = None,
                 normalise: Callable[[str], str] | None = None) -> None:
        self.classifier = classifier
        self.events = events or (lambda kind, body: None)
        self.normalise = normalise  # optional spoken-number normaliser, for example the server's

    # -- layer 1 ------------------------------------------------------------------------------------------------
    def scan(self, text: str, ctx: GuardContext, provider_turn: str = "") -> tuple[list[str], list[str]]:
        """Return (categories, rule names). Rule names never contain the text. With a spoken-number normaliser the
        sentence is scanned as written and as normalised, because a normaliser can also damage ordinary words."""
        variants = [(text, provider_turn)]
        if self.normalise:
            variants.append((self.normalise(text), self.normalise(provider_turn) if provider_turn else provider_turn))
        categories: list[str] = []
        names: list[str] = []
        for sentence, turn in variants:
            more_c, more_n = self._scan_one(sentence, ctx, turn)
            categories += [c for c in more_c if c not in categories]
            names += more_n
        return [c for c in CATEGORIES if c in categories], names

    def _scan_one(self, prepared: str, ctx: GuardContext, provider_turn: str) -> tuple[list[str], list[str]]:
        norm = normalise_text(prepared)
        turn_norm = normalise_text(provider_turn)
        hits: dict[str, list[str]] = {}

        def hit(category: str, name: str) -> None:
            hits.setdefault(category, []).append(name)

        heard = tuple(ctx.heard_values) + heard_from(turn_norm) if turn_norm else tuple(ctx.heard_values)
        allowed_text = ctx.allowed_text(extra=" | ".join(heard))
        allowed_norm = normalise_text(allowed_text)

        # registered values the mandate does not allow, and planted canaries
        registered = [*ctx.undisclosable, *ctx.canaries]
        if find_values(norm, registered, allowed_text):
            hit("unlisted_disclosure", "registered_value")

        self._digit_rules(norm, normalise_text(" | ".join([*ctx.disclosable.values(), ctx.goal])), heard, hit)
        self._fragment_rule(norm, registered, allowed_norm, heard, hit)
        self._number_rules(norm, ctx, turn_norm, allowed_norm, hit)

        offered = bool(rules.OFFER_MARKERS.search(turn_norm)) or self._partial_amount_offered(turn_norm, ctx)
        for rule in rules.RULES:
            if rule.needs_offer and not offered:
                continue
            for match in rule.pattern.finditer(norm):
                if rule.negatable and rules.negated(norm, match.start(), match.end(), after=0 if rule.before_only else 4):
                    continue
                if rule.category == "legal_threat" and rules.CITATION_CUES.search(norm):
                    continue
                hit(rule.category, rule.name)
                break
        if ctx.consumer_name:
            name = re.escape(normalise_text(ctx.consumer_name))
            if re.search(rf"(?:\bi\s+am|\bi'm|\bthis\s+is|\bmy\s+name\s+is|\bspeaking\s+as|\bmain|\bmera\s+naam|मैं)\s+{name}", norm):
                hit("identity_claim", "i_am_consumer_name")
        categories = [c for c in CATEGORIES if c in hits]
        return categories, [n for c in categories for n in hits[c]]

    @staticmethod
    def _partial_amount_offered(turn_norm: str, ctx: GuardContext) -> bool:
        if not turn_norm:
            return False
        stated = {re.sub(r"\D", "", v) for k, v in ctx.disclosable.items() if k == "amount"}
        for match in rules.AMOUNT.finditer(turn_norm):
            number = re.sub(r"[^\d]", "", (match.group(1) or match.group(2)).split(".")[0])
            if number and number not in stated:
                return True
        return False

    @staticmethod
    def _digit_rules(norm: str, disclosed_norm: str, heard: tuple[str, ...], hit) -> None:
        """Digit runs that are not a disclosed value. A run the provider said may be repeated, unless it is called a code."""
        disclosed_groups: set[str] = set()
        disclosed_joined: list[str] = []
        for _s, _e, parts, whole in digit_runs(disclosed_norm):
            disclosed_groups.update(parts)
            disclosed_joined.append(whole)
        heard_digits = {re.sub(r"\D", "", h) for h in heard}
        heard_digits.discard("")

        def covered(groups: list[str], joined: str) -> bool:
            if len(joined) >= 6 and any(joined in j for j in disclosed_joined):
                return True
            return all(g in disclosed_groups for g in groups)

        for start, end, groups, joined in digit_runs(norm):
            if covered(groups, joined):
                continue
            n = len(joined)
            from_provider = joined in heard_digits or all(g in heard_digits for g in groups)
            window = norm[max(0, start - 45): end + 20]
            strong = any(cue in window for cue in rules.CRED_CUES_STRONG)
            if 13 <= n <= 19:
                if not from_provider or strong:
                    hit("otp_or_card", "card_like_run")
            elif n >= 9:
                if not from_provider:
                    hit("unlisted_disclosure", "long_digit_run")
            elif 3 <= n <= 8 or any(3 <= len(g) <= 8 for g in groups):
                ref_before = norm[max(0, start - 25): start]
                if strong:
                    hit("otp_or_card", "code_run_with_cue")
                elif any(re.search(rf"\b{re.escape(cue)}\b", window) if cue.isascii() else cue in window for cue in rules.CRED_CUES_WEAK):
                    if not from_provider and not any(c in ref_before for c in rules.REFERENCE_CUES):
                        hit("otp_or_card", "code_run_with_cue")

    @staticmethod
    def _fragment_rule(norm: str, registered: list[str], allowed_norm: str, heard: tuple[str, ...], hit) -> None:
        """The first five or last four digits of a long registered number (phone, card, account) are a partial leak."""
        allowed_groups = {g for _s, _e, parts, _w in digit_runs(allowed_norm) for g in parts}
        heard_digits = {re.sub(r"\D", "", h) for h in heard}
        heads, tails = set(), set()
        for value in registered:
            for variant in digit_variants(str(value)):
                if len(variant) >= 10 and is_digit_value(str(value)):
                    heads.add(variant[:5])
                    tails.add(variant[-4:])
        for _s, _e, parts, _w in digit_runs(norm):
            for group in parts:
                if group in allowed_groups or group in heard_digits:
                    continue
                if (len(group) >= 5 and group in heads) or (len(group) == 4 and group in tails):
                    hit("unlisted_disclosure", "number_fragment")
                    return

    @staticmethod
    def _number_rules(norm: str, ctx: GuardContext, turn_norm: str, allowed_norm: str, hit) -> None:
        stated = {re.sub(r"\D", "", v.split(".")[0]) for k, v in ctx.disclosable.items() if k == "amount"}
        heard_amounts = set()
        for match in rules.AMOUNT.finditer(turn_norm):
            heard_amounts.add(re.sub(r"[^\d]", "", (match.group(1) or match.group(2)).split(".")[0]))
        for hv in ctx.heard_values:
            heard_amounts.add(re.sub(r"\D", "", hv))
        for match in rules.AMOUNT.finditer(norm):
            number = re.sub(r"[^\d]", "", (match.group(1) or match.group(2)).split(".")[0])
            if number and number not in stated and number not in heard_amounts:
                hit("number_mismatch", "amount_differs")
                break
        allowed_ids = {t for t in re.split(r"[\s|]+", allowed_norm) if t}
        for match in rules.ORDER_ID.finditer(norm):
            token = match.group(1)
            if any(c.isdigit() for c in token) and token not in allowed_ids:
                hit("number_mismatch", "order_id_differs")
                break

    # -- layers together -----------------------------------------------------------------------------------------
    def check(self, text: str, ctx: GuardContext, provider_turn: str = "") -> GuardVerdict:
        categories, names = self.scan(text, ctx, provider_turn)
        layers: list[str] = []
        rationale = ""
        degraded = False
        if categories:
            layers.append("deterministic")
            rationale = "deterministic rules: " + ", ".join(names)
        elif self.classifier is not None:
            try:
                result = self.classifier.classify(text, mandate_policy(ctx), provider_turn)
                if not isinstance(result, dict) or not isinstance(result.get("violation"), bool):
                    raise ValueError("unusable classifier output")
                if result["violation"]:
                    layers.append("classifier")
                    raw = [c for c in (result.get("categories") or []) if c in CATEGORIES]
                    categories = raw or ["other"]
                    rationale = str(result.get("rationale", ""))[:300]
            except Exception as exc:  # the classifier is probabilistic and remote: any failure means layer 1 alone decides
                degraded = True
                self.events("guard_degraded", {"mandate_version": ctx.mandate_version, "reason": type(exc).__name__, "layer": "classifier"})
        else:
            degraded = True
            self.events("guard_degraded", {"mandate_version": ctx.mandate_version, "reason": "no_classifier", "layer": "classifier"})
        verdict = GuardVerdict(bool(categories), categories, rationale, layers, degraded)
        if verdict.blocked:
            self.events(
                "guard_blocked",
                {
                    "mandate_version": ctx.mandate_version,
                    "categories": categories,
                    "layers": layers,
                    "degraded": degraded,
                    "text_sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                    "text_length": len(text),
                    "needs_consumer": True,  # the request or offer is recorded for the consumer by the graph
                },
            )
        return verdict

    def speak(self, text: str, ctx: GuardContext, provider_turn: str = "", language: str = "en") -> GuardedSpeech:
        verdict = self.check(text, ctx, provider_turn)
        return GuardedSpeech(HOLDING.get(language, HOLDING["en"]) if verdict.blocked else text, verdict)


def build_guard_context(store, case_id: str, mandate_version: int, heard: tuple[str, ...] = (), canaries: tuple[str, ...] = ()) -> GuardContext:
    """The guard's view of the mandate, read from the case store. Withheld values go in as strings to scan for, nothing more."""
    mandate = store.get_mandate(case_id, mandate_version)
    facts = {f.field: f.value for f in store.get_disclosable_facts(case_id, mandate_version)}
    return GuardContext(
        mandate_version=mandate_version,
        disclosable=facts,
        undisclosable=tuple(store.get_undisclosable_values(case_id, mandate_version)),
        canaries=tuple(canaries),
        goal=mandate.goal if mandate else "",
        consumer_name=facts.get("consumer_name", ""),
        heard_values=tuple(heard),
    )
