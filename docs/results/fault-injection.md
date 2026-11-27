# Fault injection and vendor faults

Everything here is SIMULATED and offline: the Groq client is the real one on a mocked HTTP transport, the models behind the graphs are scripted, the database is real Postgres. No vendor was called, so nothing here says how Groq behaves live; it says how our code behaves when Groq behaves like this.

Code touched: `server/app/adapters/{groq_llm,groq_stt,cost,factory}.py`, `server/app/services/{outreach_store,evidence_store}.py`, `server/app/runtime/run_service.py`, `workflows/src/resolve_workflows/graphs/outreach.py`, `nodes/{call_lines,classify_turn}.py`, `ports.py`. Tests: `workflows/tests/test_fault_injection.py` (26), `server/tests/unit/test_groq_faults.py` (13), `server/tests/integration/test_fault_injection_api.py` (13).

## What was tested

| Fault | Where | Result |
|---|---|---|
| Worker killed at each store write of a provider call (`save_call`, `save_promise`, `save_summary`) | workflows, fake store | Resume gives one promise, one summary approval, one summary, one `outreach` status; a killed `save_call` leaves the stored state byte for byte as it was |
| Worker killed while a call closes, over REST (promise row written, then the process dies) | server, real DB, `BaseException` | Nothing half made: no promise, no approval, no effect key; the retried turn makes each once |
| Worker killed in the follow-up graph at `record_event`, `schedule_reminder`, `save`, and right after the approval row is made | workflows | Retry gives exactly one event, one approval, one reminder and a stored state with the handled event; a client retry after success returns the stored answer |
| Same, over REST, killed after the approval row and after the reminder row | server | The request's transaction rolls back (rows, state and effect keys together); the retry makes one of each |
| Kill while a choice is pending / while the consumer's choice is applied | workflows | The pending choice survives; no approval until the consumer chooses; one approval after |
| Groq 429, Retry-After honoured, two 429s then success | server unit | Waits 0.5 s then 1.0 s (or the header value), succeeds on the third try |
| 429 that does not clear | server unit | After 3 attempts a clear `model_busy` 503 error, not a generic 502 |
| 429 during a call (draft, classify or opening) | workflows and server | One holding line ("One moment please, I am checking that.", in the call's language) is said as soon as the wait begins and comes first in the reply; the real reply follows; if the retries give up the code's own wording follows. The call is never silent. The line is logged as `rate_limited_hold` with the number of seconds only |
| Withdrawn model id | server unit | The fallback model answers, one warning is logged naming both models, later calls go straight to the fallback |
| Spending cap (`GROQ_BUDGET_USD`) used up during a call | workflows and server | The call ends with a spoken message ("the usage limit of this service has been reached"), `end_reason = budget_exhausted`, one summary approval for the owner that says why, status `awaiting_consumer`, a later turn says nothing and makes nothing |
| Cap used up before a call opens | server | 402 `budget_exceeded` with spent and limit, nothing created |
| Cap used up when a follow-up reply arrives | server | The free keyword reader labels it and says so (`degraded`); no model call, no crash |

## Bugs found (each fixed and covered by a test)

Items 2, 4, 6 (the request shape only) and 7 were reproduced on the code as committed before this change with a small probe against the old adapter on a mocked transport. Items 1, 3, 5, 8 and 9 follow directly from reading the code and were not probed separately.

1. **Vision spend was not counted against the budget.** `evidence_store._vision` built a new `CostMeter(GROQ_BUDGET_USD)` for every image, so image reads never counted, and the cap applied per client instead of to the app. Fixed: one meter per app (`cost.shared_meter(state)`) used by the chat client, the vision client and speech. Test: `test_chat_vision_and_speech_share_one_budget`.
2. **A call that crossed the cap threw away its own answer.** `CostMeter.add` raised after the response had been paid for, discarding it. Fixed: `add` only records; the next call is the one refused. Test: `test_the_call_that_crosses_the_cap_keeps_its_answer_and_the_next_one_is_refused`.
3. **A used-up budget did not stop a call.** Every node that calls a model swallows its errors, so the call carried on silently on keyword fallbacks and code wording. Fixed: a budget error (recognised by its code) is re-raised by the turn classifier and the draft step, and `OutreachRunner` closes the call with a message and a summary. Other model errors still do not stop a call (unchanged, tested).
4. **429 handling could crash or hang.** A `Retry-After` that is a date (a legal HTTP form) raised `ValueError` out of the request; a `Retry-After` of 3600 was slept through inside the request (a call would sit silent for an hour); and after the last attempt the 429 became a generic `groq_error` 502. Fixed: unparsable header uses our own delay, a wait longer than 20 s is not waited out (immediate `model_busy` 503), and the final error says the service is busy.
5. **Whisper had no 429 handling at all.** `GroqTranscriber` posted once. Fixed: it goes through the same retry path, rebuilding the multipart body for each attempt so a retry sends the whole clip. Test checks the clip is sent twice.
6. **The fallback model was sent the primary model's reasoning setting.** `qwen/...` roles carry `reasoning_effort: none`; the fallback `openai/gpt-oss-*` was sent the same value. I believe gpt-oss does not accept `none` (it takes low, medium or high), which would turn the fallback into a 400. This is an inference from the model families, **not verified live**. Fixed in the safe direction: the fallback gets no reasoning setting unless the role names one (`fallback_reasoning_effort`).
7. **A withdrawn model was retried first on every call.** Each call spent a request, and logged a warning, finding out again. Fixed: the client remembers the withdrawn id for its lifetime.
8. **The once helper loses an effect that fails.** `run_service.once(key, fn)` commits the key before running `fn`, so a worker that dies inside `fn` has the key and not the effect, and the resume skips it. That is right for an effect that must never repeat and cannot be undone, wrong for one that writes through the request's own database session. Added `once_in_session(session, key, fn)`: the key and the effect commit or roll back together. The follow-up graph and the call's promise and offer records use it. `once` itself is unchanged (its behaviour is now pinned by a test and documented in its neighbour's docstring). Test: `test_once_commits_its_key_first_so_an_effect_that_fails_is_lost_and_once_in_session_is_not`.
9. **The server's call store ignored its idempotency keys.** `save_promise` and `record_offer` took a key and did nothing with it; the only thing preventing a duplicate was that the whole request is one transaction. They now honour the key through `once_in_session`.

No bug was found in the workflows-side kill/resume behaviour: the graphs keep all state through the store port and write it last, which is why every kill point above resumes cleanly.

## Not fixed, not done

- **`GraphRunner._execute` swallows every exception** (approval graph on a background thread) and leaves the run in `paused_for_approval` even when its approval was decided and the resume died. State is not lost (a second `resume` completes it, tested) but nothing tells the owner or retries it. There is no recovery sweep. Not changed: out of scope and the runner is still a stub for the one approval graph.
- **The tests never kill a real process.** Kills are an exception raised at a chosen point (`RuntimeError` in the workflows tests, a `BaseException` on the server, which skips every `except Exception`). The server relies on the request being one transaction; a kill after the commit and before the response is the client's retry, which the stored state answers (tested for follow-up; for a call turn a retry after a committed turn is a new turn, as it would be from a real provider).
- **Concurrent requests on one case** are serialised by a row lock in the follow-up endpoints only; call turns lock the call row (existing). No concurrency test was written.
- **The 429 holding line is spoken before the wait, the wait itself is still blocking** inside the request. In text mode the REST response arrives after the retries, with the holding line first; only the voice path (`on_sentence`) can speak it while waiting. Nothing here measures the voice path.
- **No live check.** Whether Groq's 429 carries `Retry-After` in seconds, what a daily-limit 429 looks like, and whether the gpt-oss fallback accepts our request shape were not tested against Groq.
- **Budget tracking lags** at Groq by 10 to 15 minutes (plan section 9.4), and our meter counts only what our calls report, so the cap here is the app's own guard, not Groq's `blocked_api_access`, which is handled separately (typed error, existing test).
