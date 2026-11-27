"""Provider policy capture: chunk each fictional provider's policy text with layer provider_policy.

The text, date and url come from the fixtures in data/legal/providers. The fixtures are authored and
labelled fictional; the chunks keep that label in their heading so an answer cannot pass them off as
a real company's policy.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.legal.chunker import Chunk, clean_for_search
from app.legal.providers import PROVIDERS_DIR, Provider, load_providers
from app.legal.quotecheck import normalise

POLICY_TARGET_CHARS = 380


def policy_source_id(provider: Provider) -> str:
    return f"provider_{provider.slug}"


def policy_url(provider: Provider) -> str:
    return f"{provider.contact_candidates[0].source_url}#{provider.slug}"


def policy_fetched_at(provider: Provider) -> str:
    return str(provider.contact_candidates[0].fetched_at)


def chunk_policy(provider: Provider, target: int = POLICY_TARGET_CHARS) -> list[Chunk]:
    text = normalise(provider.policy.text)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    groups: list[list[str]] = [[]]
    for sentence in sentences:
        if groups[-1] and len(" ".join(groups[-1])) + len(sentence) + 1 > target:
            groups.append([])
        groups[-1].append(sentence)
    heading = provider.policy.title
    chunks = []
    for index, group in enumerate(groups):
        body = " ".join(group)
        search = f"{provider.name}. {heading}. {clean_for_search(body)}"
        chunks.append(
            Chunk(
                source_id=policy_source_id(provider),
                layer="provider_policy",
                source_url=policy_url(provider),
                fetched_at=policy_fetched_at(provider),
                section=f"policy-{index + 1}",
                clause="",
                heading=heading,
                ordinal=index,
                text=body,
                search_text=search,
                entity_type_tags=(provider.entity_type.value,),
            )
        )
    return chunks


def policy_corpus(directory: Path = PROVIDERS_DIR) -> tuple[list[Chunk], dict[str, str]]:
    """Chunks and source texts for every fixture provider."""
    chunks: list[Chunk] = []
    sources: dict[str, str] = {}
    for provider in load_providers(directory):
        sources[policy_source_id(provider)] = provider.policy.text
        chunks.extend(chunk_policy(provider))
    return chunks, sources
