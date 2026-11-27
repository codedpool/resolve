# Legal check (LLM tagger and reviewer)

Run on 27 Nov 2026. Code: `server/app/legal/verifier.py`. Raw results for every reviewed chunk: `docs/results/legal-check.json`. Scripts: `server/scripts/run_legal_check.py` (live run), `summarise_legal_check.py` (agreement), `load_legal_corpus.py --reviews` (put the saved tags back into a database without calling a model again).

## What was built

- `LegalVerifier.verify(item) -> LegalVerdict(verdict, rationale, confidence, evidence, ...)`, with items of two kinds: `chunk_tags` (are these entity-type tags right for this chunk?) and `answer` (does this chunk answer this question?).
- `LlmLegalVerifier`: the tagger role (`legal_tagger`, Qwen 3.8 27B) proposes tags from `marketplace`, `seller_on_marketplace`, `direct_seller`, `payment_intermediary` (an empty list means a general chunk); the reviewer role (`legal_reviewer`, gpt-oss-120b, a different model family) checks them against the chunk text. A chunk becomes `llm_reviewed` only when the reviewer agrees, both confidences are at least 0.7, the reviewer's own tag list equals the proposal and the tagger used no tag outside the list. Anything else is `needs_attention`, which turns the chunk's retrieval boost off. The reviewer's `evidence` must be a real quote of the chunk (checked by code); an invented quote cannot support an agreement. Models, prompt hashes, rationale and confidence are stored on the chunk row. Nothing sets `legal_reviewed`.
- `WebSearchLegalVerifier`: disabled; constructing it, or selecting `LEGAL_VERIFIER=llm_web` through `build_verifier`, raises `NotConfigured`. The code comment with the Groq `browser_search` link and the plan for the later hook is in the class.
- Prompts: `legal_tag_chunk` v1, `legal_review_tags` v2, `legal_review_answer` v1 in `workflows/src/resolve_workflows/prompts`.
- Tests (all with a scripted model, no network): `tests/unit/test_legal_verifier.py` (13) and `tests/integration/test_legal_verifier_db.py` (3): agreement, disagreement, low confidence, a reviewer who "agrees" with different tags, unknown tag, invented evidence, empty tag list, answer verdict mapping, roles and model ids recorded, the config switch, a disagreement stored as `needs_attention` removes the boost, nothing sets `legal_reviewed`.

## Live run and cost

The review ran on 54 chunks: the 30 author-labelled chunks (below) plus every other chunk of the e-commerce rules, the three RBI pages and the three escalation pages. The 167 statute chunks beyond the 7 labelled ones were not reviewed and stay `unreviewed` with no tags, as are the 8 provider-policy chunks (their tag comes from the provider fixture). 78 calls in the final run (57,894 tokens); about 0.025 USD on the run's own meter, and about 0.06 USD over all attempts of the day including two interrupted runs and a first run discarded after the reviewer prompt was found to be wrong (below). Groq's limits on this key are shared with other work: the run waited out several `retry-after` pauses of up to 295 seconds and never exceeded them.

A first version of the reviewer prompt (v1) answered "unsure" for nearly every general chunk, because it asked for evidence that a chunk names no provider. That run was thrown away after 7 chunks and the prompt rewritten (v2: an empty tag list is a valid answer and `agree` with empty evidence is allowed). The labelled chunks were not shown to the model; they were looked at to judge the failure after seeing it on seven statute chunks, which is a mild form of tuning on the test set. Prompt v2 was not changed after that.

## Agreement with the hand labels

**Caveat that matters most: the 30 labelled pairs were written by the implementing AI agent after reading each chunk, not by a human and not by a legal professional** (`workflows/evals/datasets/legal_tags_author_labelled.json`, marked as such inside the file). The agent and the tagger are both language models, so this measures consistency between two models' readings, not legal correctness. A human has to relabel the pairs before the numbers mean more.

| Measure | Result |
|---|---|
| Final tags equal the author's tags exactly | 24 of 30 (80%) |
| Tag precision, tag recall | 0.80, 0.84 |
| Chunks `llm_reviewed` / `needs_attention` (of the 30) | 18 / 12 |
| `llm_reviewed` chunks whose tags equal the author's | 16 of 18 |
| `needs_attention` chunks whose tags were really different from the author's | 4 of 12 (the other 8 had the author's tags: the reviewer was stricter than needed) |

Plan threshold: below 70% the tags would not be used for boosting. 80% is above it, so the tags are kept and used. Over the 54 reviewed chunks 33 are `llm_reviewed` and 21 `needs_attention`.

The six disagreements with the author: rule 4(11) (tagger: marketplace only; author: marketplace and direct seller; flagged); rules 5(1)-(2), 5(3) and 5(4)-(5) (the tagger added `seller_on_marketplace`, and for 5(3) also `payment_intermediary`, because those chunks mention sellers and payment providers; the author tagged only `marketplace`; all three flagged `needs_attention`); RBI press release paragraph 6 and the 2022 amendment paragraph 2 (tagger: no tags; author: `payment_intermediary`; the reviewer agreed with the tagger, so these two are `llm_reviewed` and wrong against the labels). The last two show the failure that matters: the reviewer can share the tagger's mistake.

## Does the boost help?

With the saved tags applied (`eval_retrieval.py --reviews`), same questions, same code:

| Boost | Main (30) | Held-out (10) |
|---|---|---|
| none | 28/30, Hindi 9/10 | 9/10, Hindi 2/3 |
| 0.25 (the default) | 27/30, Hindi 8/10 | 9/10, Hindi 2/3 |

The boost did not help on these questions and cost one Hindi question on the main set. Only 54 chunks carry tags, no statute chunk besides the labelled ones, so the test is thin. The boost stays in because the plan asks for it and it is harmless to the held-out set, but nothing here shows a benefit; a larger tagged corpus and more questions with a real entity type are needed to judge it.

## Answer check

The reviewer also judged, for each of the 30 main questions, whether the top retrieved chunk answers it (`legal_review_answer`):

| Top chunk is the labelled right chunk | reviewer: supports | partial | unrelated |
|---|---|---|---|
| yes (21 questions) | 7 | 14 | 0 |
| no (9 questions) | 2 | 4 | 3 |

The reviewer never called a right chunk unrelated, and called wrong chunks unrelated in 3 of 9, but it says "partial" for two thirds of right chunks and "supports" for 2 wrong ones, so it is not a usable filter on its own. Treat it as a weak signal.

## What this does not establish

No human legal review exists. The tags rest on two models and one AI-written label set, and the 167 statute chunks are largely untagged. Answers built from these chunks must keep the wording "AI-checked, not legal advice" (the grounded-answer node adds it for any source that is not `legal_reviewed`).
