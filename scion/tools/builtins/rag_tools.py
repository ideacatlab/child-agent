"""RAG tools: ingest documents and search the knowledge base."""

from __future__ import annotations

from scion.rag.pipeline import get_pipeline
from scion.rag.retrieve import search as rag_search_fn
from scion.rag.store import get_store
from scion.security.policy import MODERATE, SAFE
from scion.tools.base import ToolError, tool


@tool(risk=MODERATE)
def rag_ingest(path: str, collection: str = "default") -> str:
    """Ingest a file or folder into the vector knowledge base.

    Supports txt/md/pdf/html/json/csv. Re-ingesting only re-embeds changed files.

    Args:
        path: a file or directory to ingest.
        collection: named collection to store under (keep topics separate).
    """
    try:
        stats = get_pipeline().ingest_path(path, collection=collection)
    except Exception as exc:
        raise ToolError(f"ingest failed: {exc}")
    return f"ingested into '{collection}': {stats}"


@tool(risk=SAFE, parallel_safe=True)
def rag_search(query: str, collection: str = "default", k: int = 6) -> str:
    """Search the knowledge base; returns the top chunks with citations.

    Args:
        query: what to look for.
        collection: which collection to search.
        k: number of chunks to return.
    """
    results = rag_search_fn(query, collection=collection, k=k)
    if not results:
        return "(no matches — is anything ingested into this collection?)"
    return "\n\n".join(f"{r.cite()} (score {r.score})\n{r.text[:800]}" for r in results)


@tool(risk=SAFE, parallel_safe=True)
def rag_stats() -> str:
    """Report what's in the knowledge base (documents, chunks, collections)."""
    return str(get_store().stats())
