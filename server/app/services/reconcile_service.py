"""Live reconciliation: compare the whole narration with the confirmed facts before the mandate unlocks."""

from __future__ import annotations

import hashlib
import json
import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.factory import get_llm
from app.config import SERVER_ROOT
from app.core.crypto import seal_text
from app.db.models import Case, Fact, Notification, User
from app.privacy.redact import Redactor
from app.services.fact_service import read_value
from app.services.intake_store import ServerIntakeStore

_SRC = SERVER_ROOT.parent / "workflows" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from resolve_workflows.nodes.extract import extract_facts  # noqa: E402
from resolve_workflows.nodes.reconcile import FactView, compare, question_for  # noqa: E402
from resolve_workflows.schemas import ExtractionResult  # noqa: E402

log = logging.getLogger("resolve")


def _facts(session: Session, case: Case, key: bytes) -> dict[str, FactView]:
    rows = session.scalars(select(Fact).where(Fact.case_id == case.id, Fact.superseded_by.is_(None))).all()
    return {r.field: FactView(read_value(r, key), r.certainty.value, r.version) for r in rows}


def reconcile_case(request, session: Session, user: User, case: Case, key: bytes) -> list[dict]:
    """Returns the open disagreements. Extraction is cached against the narration text, so a correction re-compares without a model call."""
    state = request.app.state
    store = ServerIntakeStore(session, case, user, key, state.clock.now)
    narration = store.narration_redacted(str(case.id))
    if not narration:
        return []
    body = store._load()
    digest = hashlib.sha256(narration.encode()).hexdigest()
    cache = body.get("reconcile") or {}
    if cache.get("hash") == digest:
        extraction = ExtractionResult.model_validate(cache["extraction"])
    else:
        try:
            extraction, _usage, _prompt = extract_facts(get_llm(request), narration, store.today())
        except Exception:  # noqa: BLE001 - the vendor being down must not trap the consumer
            log.warning("reconciliation could not run")
            return []
        tokens = store.tokens(str(case.id))
        redactor = Redactor()
        for name in type(extraction).model_fields:
            fact = getattr(extraction, name)
            fact.value = redactor.restore(fact.value, tokens)
        cache = {"hash": digest, "extraction": extraction.model_dump(), "notified": cache.get("notified", [])}
        body["reconcile"] = cache
        store._save()
    items = compare(extraction, _facts(session, case, key))
    result = []
    asked_now = False
    for item in items:
        signature = f"{item.field}:{item.kind}:{item.fact_value}:{item.narration_value}"
        question = question_for(item)
        if signature not in cache.get("notified", []) and not asked_now:
            asked_now = True
            session.add(Notification(
                user_id=user.id,
                kind="reconcile_question",
                payload_enc=seal_text(json.dumps({**item.as_dict(), "question": question, "case_id": str(case.id)}), state.master_key),
                channel="in_app",
                created_at=state.clock.now(),
            ))
            cache.setdefault("notified", []).append(signature)
            store._save()
        result.append({**item.as_dict(), "question": question})
    return result
