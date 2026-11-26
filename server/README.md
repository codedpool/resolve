# Resolve server

The API, the voice gateway, privacy (redaction and encryption), the legal corpus and retrieval, and persistence. FastAPI, SQLAlchemy 2, Alembic, Postgres with pgvector.

The graphs live in the sibling `workflows` folder; the server loads them from `../workflows/src`, so keep the two folders side by side.

## Set up (PowerShell)

```powershell
cd server
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
docker compose up -d db                      # Postgres with pgvector on 127.0.0.1:5434
Copy-Item ..\.env.example ..\.env            # then fill GROQ_API_KEY, RUMIK_API_KEY, JWT_SECRET, MASTER_KEY
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:create_app --factory --reload --port 8000
```

`MASTER_KEY` is a base64 32-byte key. Generate one with `.venv\Scripts\python -c "from app.core.crypto import generate_key, encode_master_key; print(encode_master_key(generate_key()))"`. Keys live only in `.env`, which is never committed. `.venv\Scripts\python scripts\check_secrets.py` scans all four repos for key material.

## Local OCR

Evidence documents are read locally with Tesseract (English and Hindi). On Windows: `winget install UB-Mannheim.TesseractOCR`, then put `eng.traineddata`, `hin.traineddata` and `osd.traineddata` in `server\data\tessdata` (the Hindi file comes from the `tessdata_fast` repository of the Tesseract project). The Docker image does this for you.

## Test

```powershell
.venv\Scripts\python -m pytest -q             # free and deterministic; no vendor calls
$env:TEST_DB_NAME = "resolve_test_mine"       # optional: a separate test database name if you run suites in parallel
.venv\Scripts\python -m pytest -q -m live     # real Groq and Rumik calls; costs a few cents; needs the keys
```

The integration tests create and drop their own database (`resolve_test` by default) on the same Postgres.

## Layout

- `app/api` routes: auth, cases, facts, intake, evidence, mandates, approvals, runs, notifications, voice.
- `app/services` case logic: facts, intake store, evidence store, reconciliation, mandate service.
- `app/privacy` number normaliser and redaction. `app/voice` endpointing, speech gate, sentences, speech synthesis, call tokens and budgets.
- `app/legal` chunking, embeddings, retrieval and the legal check. `data/legal` holds the fetched official texts and fictional provider fixtures.
- `config/models.yaml` the Groq model for each role. `scripts/` bake-offs, smoke tests and evaluation scripts.
- `openapi.json` is the API snapshot the client builds against; a test fails when it drifts. Regenerate it after changing an endpoint.

## Notes

Voice and every graph run in simulation: a provider call is a practice call, never a real one. Personal text is sealed per case, and deleting a case destroys its key.
