"""Retrieval-augmented generation: ingest documents, retrieve relevant chunks.

Built for the "hand me 200 PDFs and become a marketer" case. The whole stack
runs with **zero extra dependencies** — a hashing embedder + BM25, fused with
reciprocal-rank fusion (the LlamaIndex/Haystack hybrid pattern) — and upgrades in
place to real embeddings (sentence-transformers / Voyage / OpenAI) by flipping
``SCION_EMBEDDING_BACKEND``.

Note: Anthropic has no embeddings endpoint, so the default is local. Voyage is
Anthropic's recommended embeddings partner if you want a hosted upgrade.
"""

from scion.rag.pipeline import IngestionPipeline, get_pipeline
from scion.rag.store import VectorStore, get_store

__all__ = ["IngestionPipeline", "get_pipeline", "VectorStore", "get_store"]
