# Resolve workflows

The LangGraph graphs (intake, evidence, discovery, outreach, follow-up, approval), their prompts and schemas, the output guard, and the evaluation datasets and runners. No database and no web framework here: a graph talks to the world through the ports in `src/resolve_workflows/ports.py`, and the server provides the implementations.

## Set up and test (PowerShell)

```powershell
cd workflows
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q
```

## Evaluations

Datasets are in `evals/datasets` (rebuild generated ones with the `evals\build_*.py` scripts). A live run calls Groq with the roles in `../server/config/models.yaml`, so the keys must be in `../.env`:

```powershell
.venv\Scripts\python -X utf8 -m resolve_workflows.evals.run --live --repeats 1 --max-cost 1.0 --out ..\docs\results\intake-extraction.md
```

Without `--live` the runner uses a scripted stand-in, which checks the harness for free. The Groq account's rate limits decide how long a live run takes.

## Layout

- `graphs/` one module per graph. Each handles one event per call, so the server can run it from a request, a socket, or a worker.
- `nodes/` shared steps: fact extraction, document field finder, contact ranking, reconciliation.
- `prompts/` versioned prompt files (the first line is `version: N`; the hash is logged with every call).
- `guards/` the output guard. `schemas/` the strict JSON schemas. `sim/personas` the provider behaviour cards used by the simulator.
