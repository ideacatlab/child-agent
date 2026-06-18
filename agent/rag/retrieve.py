"""Hybrid retrieval: dense cosine + BM25, fused with reciprocal-rank fusion."""

from __future__ import annotations

import math
from dataclasses import dataclass

from agent.rag.embeddings import Embedder, get_embedder, tokenize
from agent.rag.store import Chunk, VectorStore, get_store


@dataclass
class Result:
    text: str
    score: float
    doc_id: str
    ord: int
    path: str = ""

    def cite(self) -> str:
        loc = self.path or self.doc_id
        return f"[{loc}#{self.ord}]"


def _cosine(a: list[float], b: list[float]) -> float:
    # vectors are stored L2-normalized, so dot == cosine
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


def _bm25_scores(query_terms: list[str], chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(chunks)
    if n == 0:
        return []
    docs_tokens = [tokenize(c.text) for c in chunks]
    lengths = [len(t) for t in docs_tokens]
    avgdl = (sum(lengths) / n) or 1.0
    # document frequency
    df: dict[str, int] = {}
    for toks in docs_tokens:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    scores = [0.0] * n
    for term in set(query_terms):
        if term not in df:
            continue
        idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
        for i, toks in enumerate(docs_tokens):
            tf = toks.count(term)
            if tf == 0:
                continue
            denom = tf + k1 * (1 - b + b * lengths[i] / avgdl)
            scores[i] += idf * (tf * (k1 + 1)) / denom
    return scores


def _rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


def search(
    query: str,
    *,
    collection: str = "default",
    k: int = 6,
    store: VectorStore | None = None,
    embedder: Embedder | None = None,
) -> list[Result]:
    """Hybrid search over a collection. Returns the top-*k* fused chunks."""
    store = store or get_store()
    embedder = embedder or get_embedder()
    chunks = store.load_chunks(collection)
    if not chunks:
        return []

    qvec = embedder.embed_query(query)
    dense = sorted(range(len(chunks)), key=lambda i: _cosine(qvec, chunks[i].embedding), reverse=True)

    bm25 = _bm25_scores(tokenize(query), chunks)
    lexical = sorted(range(len(chunks)), key=lambda i: bm25[i], reverse=True)

    # only fuse meaningful candidates from each modality
    top = max(k * 5, 25)
    fused = _rrf([dense[:top], lexical[:top]])
    order = sorted(fused, key=lambda i: fused[i], reverse=True)[:k]

    # resolve doc paths for citations
    paths = _doc_paths(store, {chunks[i].doc_id for i in order})
    return [
        Result(
            text=chunks[i].text,
            score=round(fused[i], 5),
            doc_id=chunks[i].doc_id,
            ord=chunks[i].ord,
            path=paths.get(chunks[i].doc_id, ""),
        )
        for i in order
    ]


def _doc_paths(store: VectorStore, doc_ids: set[str]) -> dict[str, str]:
    if not doc_ids:
        return {}
    with store._conn() as c:  # noqa: SLF001 - internal access is fine within the package
        qmarks = ",".join("?" * len(doc_ids))
        rows = c.execute(
            f"SELECT doc_id, path FROM docs WHERE doc_id IN ({qmarks})", tuple(doc_ids)
        ).fetchall()
    return {r["doc_id"]: (r["path"] or "") for r in rows}
