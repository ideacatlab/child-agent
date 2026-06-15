"""Ingestion pipeline: load -> chunk -> embed -> upsert, with content-hash dedup.

Re-ingesting a folder only re-embeds the documents that actually changed
(LlamaIndex's hash-cache + upsert pattern), so it's cheap to run on a cron.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from scion.config import Settings, get_settings
from scion.logging import get_logger
from scion.rag.chunkers import chunk_markdown, chunk_text
from scion.rag.embeddings import Embedder, get_embedder
from scion.rag.loaders import iter_documents, load_document
from scion.rag.store import VectorStore, get_store

log = get_logger("rag.pipeline")


@dataclass
class IngestStats:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    chunks: int = 0
    errors: int = 0

    def __str__(self) -> str:
        return (
            f"added={self.added} updated={self.updated} skipped={self.skipped} "
            f"chunks={self.chunks} errors={self.errors}"
        )


class IngestionPipeline:
    def __init__(
        self,
        store: VectorStore | None = None,
        embedder: Embedder | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.s = settings or get_settings()
        self.store = store or get_store()
        self.embedder = embedder or get_embedder(self.s)

    def ingest_path(
        self,
        path: Path | str,
        *,
        collection: str = "default",
        chunk_size: int = 1200,
        overlap: int = 150,
    ) -> IngestStats:
        stats = IngestStats()
        root = Path(path)
        for doc in iter_documents(root):
            try:
                self._ingest_one(doc, collection, chunk_size, overlap, stats)
            except Exception as exc:
                stats.errors += 1
                log.error("ingest failed for %s: %s", doc, exc)
        return stats

    def _ingest_one(
        self, doc: Path, collection: str, chunk_size: int, overlap: int, stats: IngestStats
    ) -> None:
        raw = load_document(doc)
        if not raw.strip():
            stats.skipped += 1
            return
        doc_id = str(doc.resolve())
        content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        existing = self.store.document_hash(doc_id)
        if existing == content_hash:
            stats.skipped += 1
            return

        if doc.suffix.lower() in (".md", ".markdown"):
            pieces = chunk_markdown(raw, chunk_size=chunk_size, overlap=overlap)
        else:
            pieces = chunk_text(raw, chunk_size=chunk_size, overlap=overlap)
        if not pieces:
            stats.skipped += 1
            return

        embeddings = self.embedder.embed(pieces)
        self.store.upsert_document(
            doc_id,
            path=str(doc),
            content_hash=content_hash,
            collection=collection,
            chunks=pieces,
            embeddings=embeddings,
            meta={"filename": doc.name, "suffix": doc.suffix},
        )
        stats.chunks += len(pieces)
        if existing is None:
            stats.added += 1
        else:
            stats.updated += 1

    def ingest_text(
        self, text: str, *, doc_id: str, collection: str = "default", meta: dict | None = None
    ) -> IngestStats:
        stats = IngestStats()
        pieces = chunk_text(text)
        if not pieces:
            return stats
        embeddings = self.embedder.embed(pieces)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existed = self.store.document_hash(doc_id) is not None
        self.store.upsert_document(
            doc_id,
            path=doc_id,
            content_hash=content_hash,
            collection=collection,
            chunks=pieces,
            embeddings=embeddings,
            meta=meta or {},
        )
        stats.chunks = len(pieces)
        stats.updated += int(existed)
        stats.added += int(not existed)
        return stats


_PIPELINE: IngestionPipeline | None = None


def get_pipeline() -> IngestionPipeline:
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = IngestionPipeline()
    return _PIPELINE
