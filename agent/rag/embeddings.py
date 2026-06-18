"""Pluggable embedders. The default needs nothing installed."""

from __future__ import annotations

import math
import re
from typing import Protocol

from agent.config import Settings, get_settings
from agent.logging import get_logger

log = get_logger("rag.embeddings")

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def _l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class HashingEmbedder:
    """Feature-hashing bag-of-words embedder — deterministic, dependency-free.

    Not semantic, but combined with BM25 in the hybrid retriever it gives solid
    lexical recall and lets the whole RAG path work out of the box. Swap to a
    real backend for semantic search.
    """

    name = "hashing"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in tokenize(text):
            h = hash(("agent", tok))
            idx = h % self.dim
            sign = 1.0 if (h >> 32) & 1 else -1.0
            v[idx] += sign
        return _l2(v)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class _APIEmbedder:
    """Base for hosted embedders with a stable, normalized interface."""

    name = "api"
    dim = 0

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


class SentenceTransformerEmbedder(_APIEmbedder):
    name = "sentence-transformers"

    def __init__(self, model: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer  # lazy

        self.model = SentenceTransformer(model or "all-MiniLM-L6-v2")
        self.dim = self.model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = self.model.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vecs]


class VoyageEmbedder(_APIEmbedder):
    name = "voyage"

    def __init__(self, model: str | None = None) -> None:
        import voyageai  # lazy

        self.client = voyageai.Client()
        self.model_name = model or "voyage-3"
        self.dim = 1024

    def embed(self, texts: list[str]) -> list[list[float]]:
        res = self.client.embed(texts, model=self.model_name, input_type="document")
        return [_l2(v) for v in res.embeddings]


class OpenAIEmbedder(_APIEmbedder):
    name = "openai"

    def __init__(self, model: str | None = None) -> None:
        from openai import OpenAI  # lazy

        self.client = OpenAI()
        self.model_name = model or "text-embedding-3-small"
        self.dim = 1536

    def embed(self, texts: list[str]) -> list[list[float]]:
        res = self.client.embeddings.create(model=self.model_name, input=texts)
        return [_l2(list(d.embedding)) for d in res.data]


def get_embedder(settings: Settings | None = None) -> Embedder:
    s = settings or get_settings()
    backend = (s.embedding_backend or "hashing").lower()
    try:
        if backend in ("sentence-transformers", "st", "local"):
            return SentenceTransformerEmbedder(s.embedding_model)
        if backend == "voyage":
            return VoyageEmbedder(s.embedding_model)
        if backend == "openai":
            return OpenAIEmbedder(s.embedding_model)
    except Exception as exc:
        log.warning("embedding backend %r unavailable (%s); falling back to hashing", backend, exc)
    return HashingEmbedder(dim=s.embedding_dim)
