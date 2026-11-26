"""Live legal check: tag and review chunks with the tagger and reviewer models, then compare with the
author labels. Respects the Groq free tier (about 8000 tokens per minute, 1000 requests per day) and
stops at a hard spend cap. Results go to docs/results/legal-check.json and are resumable.

Usage: python scripts/run_legal_check.py --db resolve_test_legal [--max-usd 0.28] [--phases tags,rest,answers]
Costs real money on a paid account (a few cents). Never prints the key.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.adapters.cost import BudgetExceeded, CostMeter  # noqa: E402
from app.adapters.factory import GROQ_BASE  # noqa: E402
from app.adapters.groq_llm import GroqClient  # noqa: E402
from app.config import Settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.db.models import LegalChunk  # noqa: E402
from app.legal.chunker import build_corpus  # noqa: E402
from app.legal.embeddings import FastEmbedder  # noqa: E402
from app.legal.evalset import is_hit, load_questions  # noqa: E402
from app.legal.ingest import ingest  # noqa: E402
from app.legal.retrieval import RetrievalService  # noqa: E402
from app.legal.chunker import source_titles  # noqa: E402
from app.legal.verifier import LlmLegalVerifier, VerifyItem, item_for_chunk  # noqa: E402
from eval_retrieval import prepare  # noqa: E402

LABELS = ROOT.parent / "workflows" / "evals" / "datasets" / "legal_tags_author_labelled.json"
OUT = ROOT.parent / "docs" / "results" / "legal-check.json"


class Throttled:
    """Keeps the token rate under the account's per-minute limit and waits out a 429."""

    def __init__(self, inner: GroqClient, tpm: int = 6500) -> None:
        self.inner, self.tpm = inner, tpm
        self.window: deque[tuple[float, int]] = deque()
        self.calls = 0
        self.tokens = 0

    def _room(self, need: int) -> None:
        while True:
            now = time.time()
            while self.window and now - self.window[0][0] > 60:
                self.window.popleft()
            if sum(t for _, t in self.window) + need <= self.tpm:
                return
            time.sleep(2)

    def structured(self, role, prompt_text, variables, schema, mode="instruct"):
        need = int((len(prompt_text) + len(json.dumps(variables))) / 3.2) + 450
        for attempt in range(6):
            self._room(need)
            try:
                parsed, usage = self.inner.structured(role, prompt_text, variables, schema, mode)
            except AppError as exc:
                if (exc.details or {}).get("status") == 429 and attempt < 5:
                    time.sleep(25)
                    continue
                raise
            used = int(usage.get("total_tokens") or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)))
            self.window.append((time.time(), used))
            self.calls += 1
            self.tokens += used
            return parsed, usage
        raise RuntimeError("rate limit did not clear")


def find_row(rows: list[LegalChunk], pair: dict) -> LegalChunk:
    class View:
        def __init__(self, row):
            self.source_id, self.section = row.source_id, row.section
            self.clause_numbers = [int(n) for n in __import__("re").findall(r"\((\d+)\)", row.clause)]

    expect = [{"source": pair["source"], "section": pair["section"], "clause": pair["clause"]}]
    for row in sorted(rows, key=lambda r: r.ordinal):
        if is_hit(View(row), expect):
            return row
    raise LookupError(f"no chunk for {pair['id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--max-usd", type=float, default=0.28)
    parser.add_argument("--phases", default="tags,rest,answers")
    args = parser.parse_args()
    phases = set(args.phases.split(","))

    settings = Settings()
    if not settings.groq_api_key:
        raise SystemExit("GROQ_API_KEY is not set")
    models = settings.load_models()
    meter = CostMeter(args.max_usd)
    http = httpx.Client(base_url=GROQ_BASE, headers={"Authorization": f"Bearer {settings.groq_api_key}"}, timeout=90)
    llm = Throttled(GroqClient(models, meter, http))
    verifier = LlmLegalVerifier(llm, models)

    results = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"chunks": {}, "answers": {}}
    results["run"] = {
        "tagger": models["roles"]["legal_tagger"], "reviewer": models["roles"]["legal_reviewer"],
        "prompt_hash": verifier.prompt_hash, "answer_prompt_hash": verifier._answer_prompt.sha,
    }

    def save() -> None:
        results["run"].update({"calls_this_run": llm.calls, "tokens_this_run": llm.tokens,
                               "spent_usd_this_run": round(meter.spent_usd, 4)})
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    url = prepare(args.db)
    embedder = FastEmbedder()
    labels = json.loads(LABELS.read_text(encoding="utf-8"))["pairs"]
    titles = source_titles()
    with Session(create_engine(url)) as session:
        ingest(session, build_corpus(), embedder)
        session.commit()
        rows = list(session.scalars(select(LegalChunk)))
        labelled = {find_row(rows, p).content_hash: p for p in labels}

        def review(row: LegalChunk, pair: dict | None) -> None:
            if row.content_hash in results["chunks"]:
                return
            r = verifier.review_chunk(item_for_chunk(row, titles.get(row.source_id, "")))
            results["chunks"][row.content_hash] = {
                "locator": f"{row.source_id}:{row.section}{row.clause}", "tags": list(r.tags), "state": r.state.value,
                "reviewer_confidence": r.reviewer_confidence, "rationale": r.rationale, "reasons": list(r.reasons),
                "tagger_model": r.tagger_model, "reviewer_model": r.reviewer_model, "prompt_hash": r.prompt_hash,
                "label_id": pair["id"] if pair else None, "expected_tags": pair["expected_tags"] if pair else None,
            }
            save()
            print(row.source_id, row.section, r.state.value, list(r.tags), f"${meter.spent_usd:.4f}", flush=True)

        try:
            if "tags" in phases:
                for row in rows:
                    if row.content_hash in labelled:
                        review(row, labelled[row.content_hash])
            if "rest" in phases:
                for row in sorted(rows, key=lambda r: (r.source_id, r.ordinal)):
                    if row.content_hash not in labelled and row.layer in ("rules", "regulator", "escalation"):
                        review(row, None)
            if "answers" in phases:
                service = RetrievalService(session, embedder)
                for q in load_questions(subset="main"):
                    if q["id"] in results["answers"]:
                        continue
                    top = service.search(q["question"], q["entity_type"], k=1)[0]
                    verdict = verifier.verify(VerifyItem("answer", top.text, titles.get(top.source_id, ""),
                                                         f"{top.section}{top.clause}", question=q["question"]))
                    results["answers"][q["id"]] = {
                        "locator": top.locator, "top1_is_right_chunk": is_hit(top, q["expect"]),
                        "verdict": verdict.verdict, "confidence": verdict.confidence, "rationale": verdict.rationale,
                    }
                    save()
                    print(q["id"], verdict.verdict, f"${meter.spent_usd:.4f}", flush=True)
        except BudgetExceeded:
            print("stopped: spend cap reached", flush=True)
        finally:
            save()
    print(f"calls {llm.calls} tokens {llm.tokens} spent ${meter.spent_usd:.4f}")


if __name__ == "__main__":
    main()
