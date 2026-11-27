import json
from datetime import timedelta

import pytest

from resolve_workflows.fakes import DEFAULT_ROUTES, FakeApprovals, FakeClock, FakeFollowUpStore, LedgerOnce
from resolve_workflows.graphs.followup import (
    GRAPH_STATUSES, KIND_PREFIX, MAX_REMINDERS, FollowUpPorts, FollowUpRunner, set_status,
)
from resolve_workflows.nodes.classify_turn import REPLY_LABELS
from resolve_workflows.nodes.escalation import LOW_CONFIDENCE, select_escalation_target
from resolve_workflows.nodes.evidence_check import CaseEvidence, Credit

CASE = "case-1"
CLAIM = "Your refund of Rs 4999 was processed on 20 November 2026, reference ZM-REF-558201."
PAID = CaseEvidence(paid_amount="4999", order_date="2026-11-12", order_id="OD43817265")
PAID_WITH_CREDIT = CaseEvidence(paid_amount="4999", order_date="2026-11-12", order_id="OD43817265", credits=(Credit("4999", "2026-11-20", "ZM-REF-558201"),))


class ReplyModel:
    """Labels a reply the way the test says. `down` raises, like a withdrawn model with no working fallback."""

    def __init__(self, label: str = "", mode: str = "label", confidence: float = 0.9) -> None:
        self.label, self.mode, self.confidence = label, mode, confidence
        self.seen: list[str] = []

    def classify(self, role, prompt, text, labels):
        self.seen.append(text)
        assert labels == REPLY_LABELS
        if self.mode == "down":
            raise RuntimeError("classifier unavailable")
        return self.label, self.confidence, {}


class MaskingRedactor:
    """Stands in for the server's redactor: hides every digit run of six or more."""

    def __init__(self, withhold: bool = False) -> None:
        self.withhold = withhold

    def redact_or_withhold(self, text, tokens=None):
        import re

        class Outcome:
            pass

        out = Outcome()
        out.withheld = self.withhold
        out.text = "" if self.withhold else re.sub(r"\d{6,}", "[NUM]", text)
        out.tokens = {}
        return out


def world(label="resolved_claimed", entity_type="marketplace", confidence=0.9, evidence=PAID_WITH_CREDIT, status="awaiting_provider", model=None, redactor=None):
    store = FakeFollowUpStore(entity_type, confidence, evidence, status)
    ports = FollowUpPorts(model or ReplyModel(label), store, FakeApprovals(), LedgerOnce(), FakeClock().now, redactor)
    ports.clock = FakeClock()
    ports.now = ports.clock.now
    runner = FollowUpRunner(ports)
    runner.store, runner.approvals = store, ports.approvals
    return runner


# -- reply classes ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("label,text,action,status,approval", [
    ("resolved_claimed", CLAIM, "confirm_receipt", "provider_claimed_resolved", False),
    ("partial", "We can offer a voucher of Rs 2000 instead.", "review_offer", "awaiting_consumer", True),
    ("rejected", "Your request is declined, it is outside the policy.", "escalate", "awaiting_consumer", True),
    ("needs_info", "Please share a screenshot of the payment.", "provide_info", "awaiting_consumer", False),
    ("silence", "", "escalate", "awaiting_consumer", True),
])
def test_each_reply_class_leads_to_its_next_step(label, text, action, status, approval):
    w = world(label)
    result = w.reply(CASE, text)
    assert result.label == label and result.action == action and result.status == status
    assert bool(result.approval_id) is approval
    assert w.store.status == status
    assert result.reminder is not None  # something always brings the case back
    assert w.store.events and w.store.events[0][0] == "follow_up"


def test_an_empty_reply_is_silence_without_a_model_call():
    model = ReplyModel("resolved_claimed")
    result = world(model=model).reply(CASE, "   ")
    assert result.label == "silence" and model.seen == []
    assert result.understood["source"] == "rule"


@pytest.mark.parametrize("text,label", [
    ("Your refund has been processed and the case is closed.", "resolved_claimed"),
    ("We can only give a voucher instead of the money.", "partial"),
    ("Your request is declined as it is outside the return window.", "rejected"),
    ("Please send a photo of the damaged item.", "needs_info"),
])
def test_the_keyword_reader_labels_the_reply_when_the_model_is_down(text, label):
    w = world(model=ReplyModel(mode="down"))
    result = w.reply(CASE, text)
    assert result.label == label
    assert result.understood["degraded"] is True and result.understood["source"] == "keywords" and result.understood["low_confidence"] is True


def test_a_label_outside_the_list_falls_back_to_the_keyword_reader():
    result = world(model=ReplyModel("banana")).reply(CASE, "Your request is declined.")
    assert result.label == "rejected" and result.understood["degraded"] is True


def test_the_reply_is_redacted_before_the_model_sees_it_and_withheld_text_never_reaches_it():
    model = ReplyModel("resolved_claimed")
    world(model=model, redactor=MaskingRedactor()).reply(CASE, "Refund sent to card 4111111111111111, reference ZM-REF-558201.")
    assert model.seen and "4111111111111111" not in model.seen[0]
    withheld_model = ReplyModel("resolved_claimed")
    result = world(model=withheld_model, redactor=MaskingRedactor(withhold=True)).reply(CASE, "Your refund has been processed.")
    assert withheld_model.seen == [] and result.understood["source"] == "keywords"


def test_the_stored_event_holds_the_redacted_reply_not_the_raw_one():
    w = world(model=ReplyModel("rejected"), redactor=MaskingRedactor())
    w.reply(CASE, "Declined. Your card 4111111111111111 will not be refunded.")
    blob = json.dumps(w.store.events) + json.dumps(w.store.states)
    assert "4111111111111111" not in blob and "[NUM]" in blob


# -- verification against the case's evidence -----------------------------------------------------------------------


def test_a_claim_that_matches_the_evidence_is_verified_but_never_resolved():
    w = world("resolved_claimed", evidence=PAID_WITH_CREDIT)
    result = w.reply(CASE, CLAIM)
    assert result.verdict["overall"] == "match"
    assert result.status == "provider_claimed_resolved" and w.store.status != "resolved_consumer_confirmed"
    assert result.approval_id == ""  # nothing to approve: the consumer confirms in the app when the money arrives


def test_a_claim_that_contradicts_the_evidence_is_disputed_not_accepted():
    w = world("resolved_claimed", evidence=PAID_WITH_CREDIT)
    result = w.reply(CASE, "Your refund of Rs 4500 was processed on 20 November 2026, reference ZM-REF-558201.")
    assert result.verdict["overall"] == "mismatch" and {f["field"] for f in result.verdict["fields"] if f["verdict"] == "mismatch"} >= {"amount_received"}
    assert result.action == "ask_proof" and result.status == "awaiting_consumer" and result.approval_id


def test_a_claim_with_nothing_to_compare_it_with_stays_a_claim():
    w = world("resolved_claimed", evidence=PAID)
    result = w.reply(CASE, CLAIM)
    assert result.verdict["overall"] == "missing"
    assert result.action == "ask_proof" and result.status == "awaiting_consumer"
    assert any(f["verdict"] == "missing" for f in result.verdict["fields"])


def test_the_model_never_decides_the_verdict_even_if_it_is_confident():
    # the model says "resolved" with full confidence about a wrong number: code still returns a mismatch
    w = world(model=ReplyModel("resolved_claimed", confidence=1.0), evidence=PAID_WITH_CREDIT)
    assert w.reply(CASE, "We refunded Rs 1200 on 20 November 2026.").verdict["overall"] == "mismatch"


def test_a_partial_offer_is_compared_with_what_was_paid():
    result = world("partial", evidence=PAID).reply(CASE, "We can refund Rs 2000 as a voucher instead.")
    owed = result.verdict["fields"]
    assert any(f["field"] == "amount_owed" and f["verdict"] == "mismatch" for f in owed)


# -- escalation target ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("entity_type,first", [
    ("marketplace", "national_consumer_helpline"), ("direct_seller", "national_consumer_helpline"),
    ("seller_on_marketplace", "marketplace_grievance"), ("payment_intermediary", "rbi_ombudsman"),
])
def test_a_known_entity_type_selects_its_own_first_route_and_lists_only_its_routes(entity_type, first):
    w = world("rejected", entity_type=entity_type)
    result = w.reply(CASE, "Declined.")
    esc = result.escalation
    assert esc["needs_choice"] is False and esc["selected"]["kind"] == first
    assert [r["kind"] for r in esc["candidates"]] == [r["kind"] for r in DEFAULT_ROUTES[entity_type]]
    assert result.approval_id
    payload = w.approvals.rows[0]["payload"]
    assert payload["target"]["kind"] == first and payload["simulated"] is True


@pytest.mark.parametrize("entity_type,confidence", [("unknown", 0.9), ("marketplace", LOW_CONFIDENCE - 0.01), ("", 0.9), ("something_new", 0.9)])
def test_unknown_or_low_confidence_returns_all_candidates_and_picks_none(entity_type, confidence):
    w = world("rejected", entity_type=entity_type, confidence=confidence)
    result = w.reply(CASE, "Declined.")
    esc = result.escalation
    assert esc["needs_choice"] is True and esc["selected"] is None
    assert {r["kind"] for r in esc["candidates"]} == {r["kind"] for routes in DEFAULT_ROUTES.values() for r in routes}
    assert len(esc["candidates"]) == 4  # distinct routes, none repeated
    assert result.needs_choice is True and result.approval_id == "" and w.approvals.rows == []  # nothing is asked until the consumer chooses
    assert result.reminder["kind"] == KIND_PREFIX + "choose_route"


def test_the_consumer_chooses_among_the_candidates_and_the_approval_names_that_route():
    w = world("rejected", entity_type="unknown")
    w.reply(CASE, "Declined.")
    chosen = w.choose(CASE, "rbi_ombudsman")
    assert chosen.approval_id and chosen.needs_choice is False and chosen.escalation["selected"]["kind"] == "rbi_ombudsman"
    assert chosen.escalation["chosen_by_consumer"] is True
    assert w.approvals.rows[0]["payload"]["target"]["kind"] == "rbi_ombudsman"
    again = w.choose(CASE, "rbi_ombudsman")
    assert again.ignored is True and len(w.approvals.rows) == 1  # no second approval


def test_a_route_that_was_not_offered_cannot_be_chosen():
    w = world("rejected", entity_type="unknown")
    w.reply(CASE, "Declined.")
    with pytest.raises(ValueError):
        w.choose(CASE, "made_up_route")
    assert w.approvals.rows == []
    assert w.choose(CASE, "national_consumer_helpline").approval_id  # the pending choice survived the bad one


def test_a_choice_with_nothing_pending_does_nothing():
    w = world("rejected", entity_type="marketplace")
    result = w.choose(CASE, "rbi_ombudsman")
    assert result.ignored is True and w.approvals.rows == []


def test_selection_function_handles_a_type_without_routes_like_unknown():
    picked = select_escalation_target("marketplace", 0.9, {"direct_seller": DEFAULT_ROUTES["direct_seller"]})
    assert picked.needs_choice and picked.selected is None and picked.reason == "no_routes"


# -- deadlines and reminders ------------------------------------------------------------------------------------------


def test_a_missed_deadline_is_silence_and_proposes_escalation():
    w = world(entity_type="direct_seller")
    result = w.deadline(CASE, "deadline-9", KIND_PREFIX + "provider_reply")
    assert result.label == "silence" and result.action == "escalate" and result.approval_id
    assert result.escalation["selected"]["kind"] == "national_consumer_helpline" and result.understood["source"] == "rule"


def test_a_reminder_that_waits_on_the_consumer_reminds_instead_of_escalating():
    w = world(status="provider_claimed_resolved")
    result = w.deadline(CASE, "deadline-3", KIND_PREFIX + "check_refund")
    assert result.action == "confirm_or_dispute" and result.status == "provider_claimed_resolved" and result.approval_id == ""
    assert w.approvals.rows == []


def test_the_reminder_is_scheduled_in_the_future_through_the_store():
    w = world("rejected", entity_type="marketplace")
    result = w.reply(CASE, "Declined.")
    reminder = w.store.reminders[0]
    assert reminder["due_at"] == w.ports.clock.now() + timedelta(days=7) and reminder["kind"] == KIND_PREFIX + "escalation_check"
    assert result.reminder["id"] == reminder["id"]


def test_the_same_reply_twice_makes_one_approval_one_reminder_and_one_event():
    w = world("rejected")
    first = w.reply(CASE, "Declined.")
    second = w.reply(CASE, "  declined.  ")
    assert second.duplicate is True and second.approval_id == first.approval_id
    assert len(w.approvals.rows) == 1 and len(w.store.reminders) == 1 and len(w.store.events) == 1


def test_reminders_are_capped_per_case():
    w = world("rejected")
    for i in range(MAX_REMINDERS + 3):
        w.reply(CASE, f"Declined for reason number {i}.")
    assert len(w.store.reminders) == MAX_REMINDERS


# -- status rules -----------------------------------------------------------------------------------------------------


def test_the_graph_cannot_set_the_consumer_confirmed_status():
    w = world()
    for status in ("resolved_consumer_confirmed", "closed", "deleted", "outreach", "anything"):
        with pytest.raises(ValueError):
            set_status(w.ports, CASE, status)
    assert "resolved_consumer_confirmed" not in GRAPH_STATUSES and w.store.statuses == []


@pytest.mark.parametrize("label", REPLY_LABELS)
@pytest.mark.parametrize("entity_type", ["marketplace", "unknown"])
def test_no_reply_class_and_no_evidence_leads_to_a_resolved_status(label, entity_type):
    for evidence in (PAID, PAID_WITH_CREDIT):
        w = world(label, entity_type=entity_type, evidence=evidence)
        w.reply(CASE, CLAIM)
        w.deadline(CASE, "d1", KIND_PREFIX + "provider_reply")
        assert set(w.store.statuses) <= GRAPH_STATUSES and w.store.status not in {"resolved_consumer_confirmed", "closed"}


@pytest.mark.parametrize("terminal", ["resolved_consumer_confirmed", "closed", "deleted"])
def test_a_late_reply_does_not_reopen_a_resolved_or_closed_case(terminal):
    w = world("rejected", status=terminal)
    result = w.reply(CASE, "Declined, sorry.")
    assert w.store.status == terminal and w.store.statuses == [] and result.status == terminal
    assert w.store.events  # the reply is still recorded on the timeline
