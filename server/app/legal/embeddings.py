"""Local multilingual embeddings through ONNX (fastembed). No PyTorch, no vendor call.

Models are cached under server/data/models (git-ignored). The registry lists the candidates that
were compared in docs/results/retrieval.md; the chosen one is DEFAULT_MODEL.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

MODEL_CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "models"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    dim: int
    query_prefix: str = ""
    passage_prefix: str = ""
    custom: dict | None = None  # extra arguments for fastembed's add_custom_model


MODELS: dict[str, ModelSpec] = {
    spec.name: spec
    for spec in (
        ModelSpec("intfloat/multilingual-e5-large", 1024, "query: ", "passage: "),
        ModelSpec(
            "intfloat/multilingual-e5-small",
            384,
            "query: ",
            "passage: ",
            custom={"model_file": "onnx/model.onnx", "hf": "intfloat/multilingual-e5-small", "pooling": "MEAN"},
        ),
        ModelSpec("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", 768),
        ModelSpec("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 384),
        ModelSpec("minishlab/potion-multilingual-128M", 256),
    )
}

DEFAULT_MODEL = "intfloat/multilingual-e5-small"


class Embedder(Protocol):
    name: str
    dim: int

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """ONNX embedder. Loads lazily so importing the module never touches the network."""

    def __init__(self, name: str = DEFAULT_MODEL, cache_dir: Path = MODEL_CACHE) -> None:
        if name not in MODELS:
            raise ValueError(f"unknown embedding model {name}")
        self.spec = MODELS[name]
        self.name = name
        self.dim = self.spec.dim
        self.cache_dir = cache_dir
        self._model = None
        slug = name.replace("/", "__")
        self._vector_file = cache_dir / "vectors" / f"{slug}.json"
        self._vectors: dict[str, list[float]] | None = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding
            from fastembed.common.model_description import ModelSource, PoolingType

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if self.spec.custom:
                supported = {m["model"] for m in TextEmbedding.list_supported_models()}
                if self.name not in supported:
                    TextEmbedding.add_custom_model(
                        model=self.name,
                        pooling=PoolingType[self.spec.custom["pooling"]],
                        normalization=True,
                        sources=ModelSource(hf=self.spec.custom["hf"]),
                        dim=self.spec.dim,
                        model_file=self.spec.custom["model_file"],
                    )
            self._model = TextEmbedding(model_name=self.name, cache_dir=str(self.cache_dir))
        return self._model

    def _cache(self) -> dict[str, list[float]]:
        if self._vectors is None:
            try:
                self._vectors = json.loads(self._vector_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._vectors = {}
        return self._vectors

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectors are cached on disk by text hash, so unchanged chunks are never embedded twice."""
        cache = self._cache()
        keys = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]
        missing = [(k, t) for k, t in dict(zip(keys, texts)).items() if k not in cache]
        if missing:
            vectors = self._load().embed([t for _, t in missing], batch_size=16)
            for (key, _), vec in zip(missing, vectors):
                cache[key] = [round(float(x), 6) for x in vec]
            try:
                self._vector_file.parent.mkdir(parents=True, exist_ok=True)
                self._vector_file.write_text(json.dumps(cache), encoding="utf-8")
            except OSError:
                pass
        return [cache[k] for k in keys]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([self.spec.passage_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.spec.query_prefix + text])[0]


class HashEmbedder:
    """Deterministic bag-of-words embedder for tests that must not download a model."""

    name = "test/hash-embedder"

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            vec[int.from_bytes(digest[:4], "big") % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
