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
