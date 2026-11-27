# Final evaluation

Where every threshold in the plan stands, with run counts and what each number can and cannot tell you. Everything is **simulated**: fictional companies, synthetic or scripted inputs, and a developer or a script playing the company. Details and raw numbers are in the linked files.

## Against the thresholds

| Area | Threshold | Result | Verdict |
|---|---|---|---|
| Fact extraction (text) | at least 90% of critical fields; at most 2% invented on not-stated fields | 97.5%; 0% (20 runs, one repeat, Qwen 3.8) | met, `intake-extraction.md` |
| Spoken-number normaliser | 100% of the 60 cases | 60 of 60 | met |
| Redaction | no card, code or identity leak; under 2% of amounts, dates, years wrongly hidden | 0 leaks and 0 wrongly hidden on 150 strings; a held-out probe found six gaps, now fixed | met on the set, weak evidence: the set was written with the engine, `redaction.md` |
| Evidence extraction | at least 85% on 30 documents | 90% of fields (Hindi pages 71%); drawn documents, so an upper estimate | met, `ocr-bakeoff.md` |
| Retrieval, right chunk in top 3 | at least 85% (Hindi at least 70%) | main 28 of 30 (Hindi 9 of 10); held-out 9 of 10; a second Hindi held-out set of 12: 8 of 12 (Devanagari 3 of 6, Hinglish 5 of 6); Hindi and Hinglish pooled 19 of 25 (76%) | met pooled; Devanagari alone is weak and the second set alone is below the Hindi bar. `retrieval.md` |
| Legal check | agreement with labels reported; under 70% means tags are not used | 24 of 30 (80%) against labels written by an AI | reported; not a human or lawyer check, and boosting with the tags did not help retrieval. `legal-check.md` |
| Turn classification | at least 90% | 48 of 52 (92.3%) live on the original set; Devanagari on 42 new sentences: 39 of 42, plus 3 of 6 earlier (87.5% of 48) | met overall; Devanagari a few points lower; the prompt was not retuned. `turn-understanding.md` |
| Injection coverage | at least 90% | the model alone: 8 of 9 (89%), the miss is Devanagari; the whole system, with the keyword cross-check: 9 of 9, and still 9 of 9 when the model is made to miss every sentence | met for the system; the keyword rules were widened after seeing the three sentences they missed, so 9 of 9 is a fit to this set, not a held-out figure. `turn-understanding.md` |
| Output guard | blocks 100% of canary leaks and settlement acceptances; at most 5% false blocks on 50 ordinary sentences | 61 of 61 blocked; 0 of 50 falsely blocked (deterministic layer) | met on the suite; the rules and tests were written together, and on 30 later paraphrases the first rules caught 37% (97% after widening). `safety-core.md` |
| Behaviour suite | each card's expected outcome met at 5 runs | 15 cards x 5 runs and 12 held-out cards x 5 runs, all pass, with scripted models and the real guard and decision code; live only a 37-call sample on three cards, 7 of 7 | met offline, not run live in full. `outreach.md` |
| Safety suite | zero failures at 5 runs per case | 17 cases x 5 runs against the real models: 0 of 85 failed (95% bound about 3.5%) | met; the policy-check layer was unavailable for 43% of its calls because of rate limits, so part of the run relied on the deterministic layer alone. `safety-live.md` |
| Missing-field cap | 5 questions | enforced and tested | met |
| Speech to text (Gate A reference) | critical-field accuracy | 55% on synthetic Hinglish; order ids 20% | **below 80% on synthetic audio**; real voices untested. `bakeoff-speech-and-models.md`, `gate-a.md` |
| Latency, time to first audio p95 | under 4 s (Gate A), under 2.5 s (Gate B) | 1.3 s in the prototype with the guard, 12 turns | prototype only; the full system under load is not measured |
| Barge-in | agent stops within 500 ms in 90% of 30 trials | 30 of 30 within 500 ms, median 22 ms, slowest 30 ms, no audio after the flush (real Rumik synthesis, speech-like tone) | met on the server side; the browser's playback flush and the network are not in the figure. `barge-in.md` |
| Safety cases over the real voice path | no leak or acceptance | 14 trials, 0 failures (synthetic provider voice, one run each; 95% bound about 20%) | a smoke test of the whole path, not a rate; 3 of 17 cases not run. `voice-safety-live.md` |
| Speech, Gate B (40 recorded clips, 3 speakers) | within 10 points of the text reference | not run: needs real recordings | **open** |
| Judge calibration | each judge calibrated on 30 hand-labelled items | not done: no judge model was needed beyond the author-labelled checks | **open** |

## What was not measured

- **Barge-in in a browser.** The 30 trials are server-side with a tone; nobody has talked over the assistant through a microphone and speakers.
- **Real voices.** All speech numbers use synthetic voices. The voice path should be treated as working in simulation and unproven with real speakers, phones and rooms.
- **A real company.** No company has been contacted or has accepted an AI representative.
- **The full behaviour suite live.** The 75 + 60 behaviour runs use scripted models; only a small live sample was run on the real draft model.
- **Long conversations.** The live safety suite is one hostile turn per trial; the scripted behaviour cards are multi-turn.
- **Hand review.** No person has reviewed the failures, the safety items or a sample of the passes, as the plan intends for a first full run.

## Cost

All live runs together cost about $0.45 on Groq (extraction, bake-offs, classification, legal check, the outreach sample and the 85-trial safety suite) and about 19 thousand characters of Rumik synthesis (counted locally; the dashboard balance did not move for the first 700).
