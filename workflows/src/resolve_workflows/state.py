"""Graph state is ids and cursors. Personal text stays in the case store."""

from __future__ import annotations

from typing import TypedDict


class CaseState(TypedDict, total=False):
    case_id: str
    fact_ids: list[str]
    evidence_ids: list[str]
    mandate_version: int
    chunk_ids: list[str]
    provider_entity_type: str
    call_plan_id: str
    promise_ids: list[str]
    approval_id: str
    status: str
