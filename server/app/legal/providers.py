"""Provider fixture schema (plan section 5, Provider entity) and loader for data/legal/providers."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.db.models import EntityType

LEGAL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "legal"
PROVIDERS_DIR = LEGAL_DIR / "providers"

ContactKind = Literal["grievance_officer", "customer_care", "nodal_officer", "email", "postal_address"]
EscalationKind = Literal[
    "marketplace_grievance",
    "national_consumer_helpline",
    "consumer_commission_portal",
    "rbi_ombudsman",
]


class ContactCandidate(BaseModel):
    """A possible contact for the provider. Fixture values are fictional by construction."""

    model_config = ConfigDict(extra="forbid")

    kind: ContactKind
    value: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    fetched_at: date
    confidence: float = Field(ge=0, le=1)
    confirmed_by_user: bool = False


class EscalationTarget(BaseModel):
    """An escalation route copied from an official page (source_url must be in sources.yaml)."""

    model_config = ConfigDict(extra="forbid")

    kind: EscalationKind
    name: str = Field(min_length=1)
    source_url: HttpUrl
    url: HttpUrl | None = None
    contact: str | None = None


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    fictional_label: str = Field(min_length=1)
    text: str = Field(min_length=40)


class Provider(BaseModel):
    """Mirrors app.db.models.Provider: name, entity_type, entity_type_source, order id formats,
    contact candidates and escalation targets, plus the authored fictional policy."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1)
    fictional: Literal[True]
    entity_type: EntityType
    entity_type_source: str | None = None
    known_order_id_formats: list[str] = Field(default_factory=list)
    policy: Policy
    contact_candidates: list[ContactCandidate] = Field(min_length=1)
    escalation_targets: list[EscalationTarget] = Field(min_length=1)

    @model_validator(mode="after")
    def _clearly_fictional(self) -> Provider:
        if "fictional" not in self.name.lower():
            raise ValueError("provider name must contain the word 'fictional'")
        if "fictional" not in self.policy.fictional_label.lower():
            raise ValueError("policy must be labelled fictional")
        if self.entity_type is EntityType.unknown:
            raise ValueError("fixtures must use a concrete entity_type")
        return self


def load_providers(directory: Path = PROVIDERS_DIR) -> list[Provider]:
    providers = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        providers.append(Provider.model_validate(data))
    return providers
