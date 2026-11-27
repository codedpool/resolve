# Legal corpus and retrieval

Built on 27 Nov 2026. Code is in `server/app/legal`, the questions in `workflows/evals/datasets/retrieval.json`, the scripts in `server/scripts/bake_embeddings.py` and `eval_retrieval.py`.

## Corpus

Seven fetched sources are chunked (`server/data/legal/chunking.yaml`): the Consumer Protection Act 2019 (167 chunks, one or more per section, long sections split at numbered sub-clauses), the E-Commerce Rules 2020 (English half only, 20 chunks; the Hindi half of that gazette PDF extracts as garbage and is skipped), three RBI pages (16 chunks) and three escalation pages (NCH home and about, the PIB e-Jagriti release; 11 chunks). `ejagriti_home` has no readable text and is not chunked. Four fictional provider policies add 8 chunks with layer `provider_policy`. Every chunk text is an exact, whitespace-normalised slice of the extracted source text and every chunk passes `quotecheck`; a chunk altered by one character fails it.

Known limits of the chunking. PDF page furniture ("--- page 9 ---", the running gazette header) and the marginal notes of the Act (printed as stray lines of section titles) stay inside a chunk when they fall inside it, because a chunk must be an exact quote; they are removed from the text that is embedded and indexed. Section titles of the Act are therefore not available as headings; the heading is the chapter.

## Embedding model

Chosen: `intfloat/multilingual-e5-small`, run through fastembed on ONNX Runtime on CPU. No PyTorch is installed. fastembed 0.9.1 and the ONNX file (465 MB, from the model's own Hugging Face repo, registered as a fastembed custom model) install and run on Windows with Python 3.12. The model is cached under `server/data/models` (git-ignored); vectors of unchanged text are also cached there, so re-ingestion embeds nothing twice. 384 dimensions, about 0.08 s per query and about 30 s for the whole corpus on this CPU.

Bake-off on the 30 main questions (10 of them Hindi: 6 Devanagari, 4 Hinglish), right chunk in the top 3:

| Model (ONNX) | Size | Dim | Dense only, all | Dense only, Hindi | Hybrid, all | Hybrid, Hindi |
|---|---|---|---|---|---|---|
| multilingual-e5-large | 2.2 GB | 1024 | 26/30 (87%) | 8/10 | 25/30 | 7/10 |
| **multilingual-e5-small** | 0.47 GB | 384 | 24/30 (80%) | 7/10 | **28/30 (93%)** | **9/10** |
| paraphrase-multilingual-mpnet-base-v2 | 1.0 GB | 768 | 17/30 (57%) | 5/10 | 21/30 | 8/10 |
| paraphrase-multilingual-MiniLM-L12-v2 | 0.22 GB | 384 | 18/30 (60%) | 6/10 | 23/30 | 8/10 |
| potion-multilingual-128M | 0.5 GB | 256 | 16/30 (53%) | 6/10 | 23/30 | 7/10 |

"Hybrid" is the final retrieval (vector plus full-text, reciprocal rank fusion, Hindi word list; see below), same weights for every model. e5-large is the best dense model but, in the hybrid with the weights tuned on e5-small, e5-small scored higher; the differences between e5-small and e5-large are two or three questions out of 30, within noise for a set this small. e5-small was chosen because it is a fifth of the download, a third of the vector width and as accurate here. `BAAI/bge-m3` was not run: fastembed does not list it and its ONNX export is a multi-gigabyte download. The model id is `DEFAULT_MODEL` in `app/legal/embeddings.py`; changing it needs a new migration for the vector width and a re-ingest.

## Hybrid retrieval and its numbers

Retrieval (`server/app/legal/retrieval.py`): pgvector cosine (HNSW index) and Postgres full-text search (GIN on a generated tsvector, English config) each give their top 40; the two lists are fused by reciprocal rank fusion (k = 60, equal weights); then an entity-type boost multiplies the fused score by 1.25 for a chunk whose tags contain the question's entity type. The boost never filters, a chunk marked `needs_attention` gets no boost, and a question whose entity type is `unknown` boosts nothing. Results carry id, text, layer, source id and url, fetched date, section and clause, heading, tag review state and both ranks.

Two things were tuned on the 30 main questions, after seeing the first untuned run (dense 24/30, plain hybrid 21/30, which was worse than dense alone):

- The full-text half ranks chunks by the summed inverse document frequency of the query words they contain, instead of plain `ts_rank_cd`, because words such as "complaint" and "commission" appear in most chunks and swamped the rare ones. English questions went from 10/20 to 16/20 on full-text alone.
- A small Hindi and Hinglish word list (`lexicon.py`, about 60 Devanagari stems and 20 Latin-script words, general consumer vocabulary) adds English equivalents to the full-text query only, because the sources are English and a Devanagari question has no words in common with them. Hindi on the main set went from 7/10 to 9/10. The word list was written after seeing the main questions, so it is not independent of them; the held-out numbers below are the fair test.

The held-out questions were run once, after the tuning was finished, and were not used to change anything.

| Set | Questions | Right chunk in top 3 | Threshold |
|---|---|---|---|
| Main, all | 30 | 28/30 (93%) | at least 85%: met |
| Main, Hindi (6 Devanagari, 4 Hinglish) | 10 | 9/10 (90%) | at least 70%: met |
| Held-out, all | 10 | 9/10 (90%) | at least 85%: met |
| Held-out, Hindi (2 Devanagari, 1 Hinglish) | 3 | 2/3 (67%) | at least 70%: **missed by one question**; three questions is too few to mean much |
| Main and held-out together, Hindi | 13 | 11/13 (85%) | at least 70%: met |
| Main and held-out together, all | 40 | 37/40 (93%) | |

By language over all 40: English 26/27, Devanagari 8/8, Hinglish 3/5.

The three misses. m05 (which District Commission can I file in if the company is in another city): the answer is section 34(2) and the model ranks sections about transfer and the State Commission above it. m27 (Hinglish, refund and compensation orders): the full-text words "refund" and "order" pull the e-commerce cancellation rule above section 39(1). h09 (Hinglish, what if the commission does not decide admissibility on time): sections 38 and 69 outrank section 36(3).

What the numbers do not show. The questions were written by the implementing agent, from the fetched texts, with one or two correct locators each. 40 questions is a small set: one question moves the overall rate by 2.5 points and the pooled Hindi rate by 7.7 points. Entity-type tags were all empty during these runs (the legal check, which assigns them, ran afterwards), so the boost played no part in any number above. A human should read the question set and add questions before these numbers are relied on.

Tests: `tests/integration/test_legal_eval.py` (thresholds with the real model), `test_legal_retrieval.py` (fusion contributions, a wrong entity tag still returns the right chunk, a `needs_attention` chunk gets no boost, `unknown` boosts nothing), `tests/unit/test_legal_dataset.py` (every question has an answering chunk and its quoted basis is in the source).

## Later changes, and provider policies

After the numbers above two code changes were made for other reasons and the main and held-out sets were run again; the counts did not change (main 28/30, Hindi 9/10; held-out 9/10, Hindi 2/3). Nothing was tuned on the held-out questions.

- Hindi words in the word list are now matched longest first and consumed, so "शिकायत अधिकारी" (grievance officer) no longer also adds "rights" through the shorter stem "अधिकार".
- Provider policy capture. Each fictional provider's policy text is chunked by sentence group (about 380 characters; 8 chunks over 4 providers) with layer `provider_policy`, the policy title as heading, the entity type of the provider as its tag, the fetched date and the `fixture://fictional#<slug>` url taken from the provider fixture's first contact candidate. The policy fixtures carry no url of their own. A provider's policy is a retrieval candidate only when the question names the provider (the words of its slug, for example "Demo Bazaar") or the caller passes the source in `prefer_sources`, which also boosts it. Without this rule the four policies, which talk about returns and refunds, pushed the statute out of the top 3 for generic refund questions (main set 27/30 with the policies unscoped, 28/30 with the scope). Tests: a refund question naming each provider returns that provider's policy first; another provider's policy and the provider policies in general do not answer a statute question.
