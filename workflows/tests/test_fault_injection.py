"""Faults: a worker killed mid-run, a vendor that rate-limits, a spending cap that is used up. The graphs must lose no state,
make no record twice, never go silent on a call, and stop with a plain message instead of a crash."""

import contextlib
from datetime import timedelta

import pytest

from resolve_workflows.fakes import FakeApprovals, FakeClock, FakeFollowUpStore, LedgerOnce
from resolve_workflows.graphs.followup import FollowUpPorts, FollowUpRunner
from resolve_workflows.guards.output_guard import HOLDING
from resolve_workflows.nodes import call_lines
from resolve_workflows.nodes.classify_turn import REPLY_LABELS
from resolve_workflows.ports import is_budget_error
from resolve_workflows.sim.harness import CASE_ID, make_world
from resolve_workflows.sim.models import ScriptedClassifier, ScriptedDraftLLM

CALL = "c1"


class BudgetUsedUp(Exception):
    """What the server's BudgetExceeded looks like to the graph: an exception with this code."""

    code = "budget_exceeded"


class RateLimitedError(Exception):
    code = "model_busy"


class WatchableLLM:
    """The draft model with a rate limit: the first `waits` draft calls announce a wait on the backoff listener (as the Groq
    client does before it sleeps and retries) and then answer normally. `fail_after_wait` makes the retry give up instead."""

    def __init__(self, waits: int = 1, repeats: int = 1, fail_after_wait: bool = False) -> None:
        self.inner = ScriptedDraftLLM()
        self.waits, self.repeats, self.fail_after_wait = waits, repeats, fail_after_wait
        self.listener = None
        self.order: list[str] = []

    @contextlib.contextmanager
    def watch_backoff(self, callback):
        self.listener = callback
        try:
            yield
        finally:
            self.listener = None

    def text(self, role, prompt, variables, mode="instruct"):
        if role == "draft" and self.waits > 0:
            self.waits -= 1
            for _ in range(self.repeats):
                self.listener(1.5)  # a 429 was returned; the client is about to wait
            self.order.append("waited")
            if self.fail_after_wait:
                raise RateLimitedError()
        return self.inner.text(role, prompt, variables, mode)

    def structured(self, *args, **kwargs):
        return self.inner.structured(*args, **kwargs)


def watched_world(**kw):
    """A world whose call has opened; the rate limit is armed for the turn that follows."""
    waits = kw.pop("waits", 1)
    llm = WatchableLLM(waits=0, **kw)
    world = make_world(llm=llm)
    world.runner.ports.backoff_watch = llm.watch_backoff
    world.runner.start(CASE_ID, CALL)
    llm.waits = waits
    world.sentences_live.clear()
    return world, llm


# -- a rate limit on a call: a holding line, never silence -------------------------------------------------------------


def test_a_rate_limited_draft_says_a_holding_line_first_and_then_the_real_reply():
    world, llm = watched_world()
    result = world.runner.turn(CASE_ID, CALL, "Please hold, we are checking.")
    hold = call_lines.line("hold_wait", "en")
    assert result.sentences[0] == hold and len(result.sentences) > 1  # the real reply follows the holding line
    assert world.sentences_live[0] == hold  # and it was said as soon as the wait began, not after the draft
    assert result.sentences.count(hold) == 1


def test_one_holding_line_per_turn_however_many_times_the_client_waits():
    world, llm = watched_world(repeats=3)
    result = world.runner.turn(CASE_ID, CALL, "Please hold, we are checking.")
    assert result.sentences.count(call_lines.line("hold_wait", "en")) == 1


def test_no_wait_means_no_holding_line():
    world, _llm = watched_world(waits=0)
    result = world.runner.turn(CASE_ID, CALL, "Please hold, we are checking.")
    assert call_lines.line("hold_wait", "en") not in result.sentences


def test_the_call_is_never_silent_when_the_retry_gives_up():
    world, llm = watched_world(fail_after_wait=True)
    result = world.runner.turn(CASE_ID, CALL, "Please hold, we are checking.")
    assert result.sentences[0] == call_lines.line("hold_wait", "en")
    assert len(result.sentences) >= 2  # the code's own wording followed the holding line
    assert world.store.load_call(CALL)["draft_fallbacks"] >= 1 and not result.ended


def test_the_holding_line_is_logged_without_text_and_is_not_a_guard_block():
    world, _llm = watched_world()
    world.runner.turn(CASE_ID, CALL, "Please hold, we are checking.")
    held = [e for e in world.case_store.events if e[1] == "rate_limited_hold"]
    assert len(held) == 1 and set(held[0][2]) == {"seconds"}
    assert not any(e[1] == "guard_blocked" for e in world.case_store.events)


def test_a_wait_while_the_call_opens_is_covered_too():
    llm = WatchableLLM()
    world = make_world(llm=llm)
    world.runner.ports.backoff_watch = llm.watch_backoff
    first = world.runner.start(CASE_ID, CALL)
    assert first.sentences[0] == call_lines.line("hold_wait", "en") and "AI assistant" in " ".join(first.sentences)


@pytest.mark.parametrize("language", ["hi", "hinglish"])
def test_the_holding_line_follows_the_call_language(language):
    llm = WatchableLLM(waits=0)
    world = make_world(llm=llm, language=language)
    world.runner.ports.backoff_watch = llm.watch_backoff
    world.runner.start(CASE_ID, CALL)
    llm.waits = 1
    result = world.runner.turn(CASE_ID, CALL, "Please hold, we are checking.")
    assert result.sentences[0] == call_lines.line("hold_wait", language)


def test_the_holding_line_is_not_the_guard_holding_phrase():
    assert call_lines.line("hold_wait", "en") != HOLDING["en"]


# -- the spending cap: stop with a message, no crash --------------------------------------------------------------------


class BudgetClassifier(ScriptedClassifier):
    def classify(self, role, prompt, text, labels):
        raise BudgetUsedUp()


class BudgetDraftLLM(ScriptedDraftLLM):
    def text(self, role, prompt, variables, mode="instruct"):
        if role == "draft" and variables.get("provider_said"):
            raise BudgetUsedUp()
        if role == "summarize":
            raise BudgetUsedUp()  # even the summary cannot be worded by a model: the code's own text is used
        return super().text(role, prompt, variables, mode)


def _stopped(result, world):
    assert result.ended and result.end_reason == "budget_exhausted" and result.approval_id
    assert result.sentences == [call_lines.line("end_budget", "en")]
    assert len(world.approvals.of_kind("summary")) == 1
    summary = world.store.summaries[0]
    assert summary["record"]["outcome"] == "budget_exhausted" and world.store.statuses[-1] == "awaiting_consumer"
    assert world.store.load_call(CALL)["finished"] is True
    assert not [s for s in world.store.statuses if s in {"resolved_consumer_confirmed", "closed"}]


def test_a_used_up_budget_in_the_classifier_ends_the_call_cleanly():
    world = make_world(classifier=BudgetClassifier())
    world.runner.start(CASE_ID, CALL)
    result = world.runner.turn(CASE_ID, CALL, "Please hold, we are checking.")
    _stopped(result, world)
    again = world.runner.turn(CASE_ID, CALL, "Hello? Are you there?")
    assert again.sentences == [] and again.ended  # nothing more is said, nothing is made twice
    assert len(world.approvals.of_kind("summary")) == 1


def test_a_used_up_budget_in_the_draft_model_ends_the_call_cleanly():
    world = make_world(llm=BudgetDraftLLM())
    world.runner.start(CASE_ID, CALL)
    result = world.runner.turn(CASE_ID, CALL, "Please hold, we are checking.")
    _stopped(result, world)
    assert "usage limit" in world.store.summaries[0]["text"]  # the model could not word the summary: the code's own text did


def test_a_used_up_budget_before_the_call_opens_is_reported_to_the_caller():
    class Closed(ScriptedDraftLLM):
        def text(self, role, prompt, variables, mode="instruct"):
            raise BudgetUsedUp()

    world = make_world(llm=Closed())
    with pytest.raises(BudgetUsedUp):
        world.runner.start(CASE_ID, CALL)
    assert world.approvals.rows == [] and world.store.load_call(CALL) is None  # a clear 402 for the caller, nothing half-made


def test_other_model_errors_still_do_not_end_the_call():
    class Flaky(ScriptedClassifier):
        def classify(self, role, prompt, text, labels):
            raise RuntimeError("boom")

    world = make_world(classifier=Flaky())
    world.runner.start(CASE_ID, CALL)
    result = world.runner.turn(CASE_ID, CALL, "Please hold, we are checking.")
    assert not result.ended and result.sentences  # keyword reader took over


def test_a_budget_error_is_recognised_by_its_code_only():
    assert is_budget_error(BudgetUsedUp()) and not is_budget_error(RuntimeError("x")) and not is_budget_error(RateLimitedError())


def test_the_follow_up_reply_still_gets_a_label_when_the_budget_is_used_up():
    class Out:
        def classify(self, role, prompt, text, labels):
            raise BudgetUsedUp()

    store = FakeFollowUpStore()
    ports = FollowUpPorts(Out(), store, FakeApprovals(), LedgerOnce(), FakeClock().now)
    result = FollowUpRunner(ports).reply("case-1", "Your request is declined.")
    assert result.label == "rejected" and result.understood["degraded"] is True  # the free keyword reader, said so


# -- killing the worker: provider call -----------------------------------------------------------------------------------


def _call_until_promise(world):
    world.runner.start(CASE_ID, CALL)
    world.clock.advance(15)
    world.runner.turn(CASE_ID, CALL, "I will credit the refund of 4999 rupees by 20 November.")
    world.clock.advance(15)


@pytest.mark.parametrize("point", ["save_call", "save_promise", "save_summary"])
def test_a_call_killed_at_any_store_write_resumes_with_no_duplicate_records(point):
    world = make_world()
    _call_until_promise(world)
    before = world.store.load_call(CALL)
    world.store.crash_once.add(point)
    with pytest.raises(RuntimeError):
        world.runner.turn(CASE_ID, CALL, "My reference is ZM-REF-558201.")
    if point == "save_call":
        assert world.store.load_call(CALL) == before  # the killed write left the stored state as it was: nothing lost, nothing half-written
    retry = world.runner.turn(CASE_ID, CALL, "My reference is ZM-REF-558201.")
    final = world.store.load_call(CALL)
    assert final["finished"] and final["end_reason"] == "promise_secured"
    assert len(world.store.promises) == 1 and len(world.approvals.of_kind("summary")) == 1 and len(world.store.summaries) == 1
    assert world.store.statuses.count("outreach") == 1
    assert retry.ended is True


def test_a_killed_call_does_not_make_a_second_offer_record():
    world = make_world(limits={"accept_partial": False})
    world.runner.start(CASE_ID, CALL)
    world.store.crash_once.add("save_summary")
    with pytest.raises(RuntimeError):
        world.runner.turn(CASE_ID, CALL, "I can do two thousand rupees as a final settlement.")
    world.runner.end(CASE_ID, CALL)
    assert len(world.store.offers) == 1 and len(world.approvals.of_kind("summary")) == 1


# -- killing the worker: follow-up graph ---------------------------------------------------------------------------------


class ReplyModel:
    def classify(self, role, prompt, text, labels):
        assert labels == REPLY_LABELS
        return "rejected", 0.9, {}


def followup_world(entity_type="marketplace"):
    store = FakeFollowUpStore(entity_type)
    ports = FollowUpPorts(ReplyModel(), store, FakeApprovals(), LedgerOnce(), FakeClock().now)
    runner = FollowUpRunner(ports)
    return runner, store, ports.approvals


@pytest.mark.parametrize("point", ["record_event", "schedule_reminder", "save", "approval"])
def test_a_follow_up_killed_at_any_step_resumes_with_no_lost_state_and_no_duplicates(point):
    runner, store, approvals = followup_world()
    if point == "approval":
        approvals.crash_once = True  # the approval row exists, but the worker died before it could note the id
    else:
        store.crash_once.add(point)
    with pytest.raises(RuntimeError):
        runner.reply("case-1", "Declined, sorry.")
    retry = runner.reply("case-1", "Declined, sorry.")
    assert retry.approval_id and retry.reminder and retry.action == "escalate"
    assert len(approvals.rows) == 1 and len(store.reminders) == 1 and len(store.events) == 1
    saved = store.load("case-1")
    assert list(saved["processed"]) and saved["approvals"] and saved["reminder_count"] == 1
    again = runner.reply("case-1", "Declined, sorry.")  # a client retry after success changes nothing
    assert again.duplicate and again.approval_id == retry.approval_id
    assert len(approvals.rows) == 1 and len(store.reminders) == 1 and len(store.events) == 1


def test_a_follow_up_that_waits_for_a_choice_survives_a_kill_and_keeps_the_choice():
    runner, store, approvals = followup_world(entity_type="unknown")
    store.crash_once.add("save")
    with pytest.raises(RuntimeError):
        runner.reply("case-1", "Declined, sorry.")
    waiting = runner.reply("case-1", "Declined, sorry.")
    assert waiting.needs_choice and approvals.rows == [] and len(store.reminders) == 1
    store.crash_once.add("schedule_reminder")
    with pytest.raises(RuntimeError):
        runner.choose("case-1", "rbi_ombudsman")
    chosen = runner.choose("case-1", "rbi_ombudsman")
    assert chosen.approval_id and len(approvals.rows) == 1 and approvals.rows[0]["payload"]["target"]["kind"] == "rbi_ombudsman"


def test_a_step_that_failed_is_run_again_and_one_that_finished_is_not():
    once = LedgerOnce()
    made: list[str] = []

    def failing():
        raise RuntimeError("killed")

    with pytest.raises(RuntimeError):
        once("k1", failing)
    assert once("k1", lambda: made.append("a")) is True  # the failed one was not marked done, so it runs
    assert once("k1", lambda: made.append("b")) is False  # the finished one is not run again
    assert made == ["a"]


def test_a_missed_date_killed_mid_run_resumes_the_same_way():
    runner, store, approvals = followup_world()
    store.crash_once.add("schedule_reminder")
    with pytest.raises(RuntimeError):
        runner.deadline("case-1", "deadline-1", "followup_provider_reply")
    done = runner.deadline("case-1", "deadline-1", "followup_provider_reply")
    assert done.label == "silence" and len(approvals.rows) == 1 and len(store.reminders) == 1 and len(store.events) == 1
    assert store.reminders[0]["due_at"] - FakeClock().now() == timedelta(days=7)
