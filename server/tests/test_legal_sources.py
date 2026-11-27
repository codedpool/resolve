"""S0.5: legal source manifest and fictional provider fixtures."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import EntityType
from app.legal.providers import LEGAL_DIR, PROVIDERS_DIR, Provider, load_providers

SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    fetched_at: date
    status: str = Field(pattern=r"^(available|unavailable)$")
    sha256: str | None
    issuer: str | None = None
    content_type: str | None = None
    file: str | None = None
    size_bytes: int | None = None
    text_file: str | None = None
    text_sha256: str | None = None
    notes: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _status_rules(self) -> Source:
        if self.status == "available":
            if not self.sha256 or not SHA256.match(self.sha256):
                raise ValueError("available source needs a sha256")
            if not (self.file and self.text_file and self.text_sha256):
                raise ValueError("available source needs file, text_file and text_sha256")
            if not SHA256.match(self.text_sha256):
                raise ValueError("text_sha256 malformed")
        else:
            if self.sha256 is not None:
                raise ValueError("unavailable source must have sha256: null")
            if not self.reason:
                raise ValueError("unavailable source needs a reason")
        return self


def _load_sources() -> list[Source]:
    data = yaml.safe_load((LEGAL_DIR / "sources.yaml").read_text(encoding="utf-8"))
    return [Source.model_validate(item) for item in data["sources"]]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


SOURCES = _load_sources()
AVAILABLE = [s for s in SOURCES if s.status == "available"]
BY_URL = {s.url: s for s in SOURCES}


def test_sources_unique_ids_and_urls():
    assert len({s.id for s in SOURCES}) == len(SOURCES)
    assert len(BY_URL) == len(SOURCES)


def test_required_official_texts_are_present():
    ids = {s.id for s in AVAILABLE}
    assert {"cpa2019_egazette", "ecom_rules_2020_egazette", "nch_home"} <= ids


@pytest.mark.parametrize("source", AVAILABLE, ids=lambda s: s.id)
def test_available_source_hashes_match_files(source: Source):
    raw = LEGAL_DIR / source.file
    text = LEGAL_DIR / source.text_file
    assert raw.is_file() and text.is_file()
    assert _sha(raw) == source.sha256
    assert raw.stat().st_size == source.size_bytes
    assert _sha(text) == source.text_sha256


def test_official_acts_text_content():
    by_id = {s.id: s for s in AVAILABLE}
    cpa = (LEGAL_DIR / by_id["cpa2019_egazette"].text_file).read_text(encoding="utf-8")
    assert "THE CONSUMER PROTECTION ACT, 2019" in cpa
    cpa = " ".join(cpa.split())
    assert '"e-commerce" means buying or selling of goods or services' in cpa
    rules = (LEGAL_DIR / by_id["ecom_rules_2020_egazette"].text_file).read_text(encoding="utf-8")
    rules = " ".join(rules.split())
    assert "Consumer Protection (E-Commerce) Rules, 2020" in rules
    assert "grievance officer" in rules


def test_unavailable_sources_have_no_file_claims():
    for s in SOURCES:
        if s.status == "unavailable":
            assert s.file is None and s.text_file is None and s.sha256 is None


# provider fixtures

PROVIDERS = load_providers()


def test_four_fixtures_cover_each_entity_type():
    assert len(list(PROVIDERS_DIR.glob("*.yaml"))) == 4
    assert {p.entity_type for p in PROVIDERS} == {
        EntityType.marketplace,
        EntityType.seller_on_marketplace,
        EntityType.direct_seller,
        EntityType.payment_intermediary,
    }


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.slug)
def test_provider_is_fictional_and_escalation_sources_are_fetched(provider: Provider):
    assert provider.fictional is True
    assert "fictional" in provider.name.lower()
    for c in provider.contact_candidates:
        assert "example.invalid" in c.value or "FICTIONAL" in c.value
    for target in provider.escalation_targets:
        source = BY_URL.get(str(target.source_url))
        assert source is not None, f"{target.source_url} not in sources.yaml"
        assert source.status == "available"


def test_escalation_contacts_appear_in_fetched_pages():
    by_id = {s.id: s for s in AVAILABLE}

    def text(source_id: str) -> str:
        return (LEGAL_DIR / by_id[source_id].text_file).read_text(encoding="utf-8")

    nch = text("nch_home")
    for needle in ("1915", "1800114000", "8800001915"):
        assert needle in nch
    rbi = text("rbi_pr1184")
    for needle in ("https://cms.rbi.org.in", "14448", "Sector 17", "160017"):
        assert needle in rbi
    assert "e-Jagriti" in text("pib_ejagriti_2269994")
    assert "e-Daakhil" in text("pib_ejagriti_2269994")


def test_payment_intermediary_escalates_to_rbi_ombudsman():
    pay = next(p for p in PROVIDERS if p.entity_type is EntityType.payment_intermediary)
    assert "rbi_ombudsman" in {t.kind for t in pay.escalation_targets}


def test_provider_schema_rejects_unlabelled_or_real_looking_provider():
    data = yaml.safe_load((PROVIDERS_DIR / "marketplace.yaml").read_text(encoding="utf-8"))
    data["name"] = "Acme Mart"
    with pytest.raises(ValueError):
        Provider.model_validate(data)
    data["name"] = "FICTIONAL Acme Mart"
    data["entity_type"] = "unknown"
    with pytest.raises(ValueError):
        Provider.model_validate(data)
