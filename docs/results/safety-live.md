# Safety suite against the real models

Run on 27 Nov 2026 with `server/scripts/eval_safety_live.py --runs 5`. Raw rows are in `safety-live.json`.

**85 trials, 0 failures.** 17 cases, 5 runs each: 10 trials asking for a one-time code, 10 for a card number, 25 for a detail outside the permission (address, phone, email, identity numbers, bank details, password), 20 pushing for a settlement, and 20 giving the assistant an instruction. In every trial the real draft model and the real turn classifier wrote and routed the reply, the real output guard checked every sentence, and nothing the assistant said contained a canary value or accepted anything. Cost about $0.09 on the free tier, with the account's rate limits paced.

With zero failures in 85 trials, the 95% upper bound on the failure rate is about 3.5% (3 divided by 85). That bound is for this suite and this fixture, not for real companies.

## What this run did and did not test

- Each trial was a single hostile turn followed by the end of the call. The suite does not test a long adaptive conversation.
- The guard's model-based policy layer was called on every sentence, but it was **unavailable for part of the run**: 194 of the 448 policy-check calls failed (the rate limit was hit and the client gave up after its patient retries), so for those sentences only the deterministic layer protected the reply. That is the designed fallback, and no failure got through, but this run cannot say how much the policy layer adds. Eight trials had a sentence replaced by the holding line.
- The cases are my own and the guard's rules were written with them in view, so this is a regression check for known attacks, not a measure of unseen ones. The earlier 30-paraphrase test (`safety-core.md`) is the better signal of how the deterministic rules generalise: 37% on first sight, 97% after widening.
- All 17 cases are single provider turns (mostly English and romanised Hinglish, one in Devanagari), and the suite fixture is invented.
