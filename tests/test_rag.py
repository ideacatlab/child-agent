from scion.rag.chunkers import chunk_text
from scion.rag.embeddings import HashingEmbedder
from scion.rag.pipeline import IngestionPipeline
from scion.rag.retrieve import search
from scion.rag.store import VectorStore


def test_hashing_embedder_deterministic():
    e = HashingEmbedder(dim=256)
    a = e.embed_query("hello world")
    b = e.embed_query("hello world")
    assert a == b and len(a) == 256
    # normalized
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


def test_chunking_overlap():
    text = "\n\n".join(f"Paragraph number {i} with some filler words." for i in range(40))
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 260 for c in chunks)


def test_ingest_and_search(tmp_path):
    store = VectorStore(tmp_path / "v.db")
    pipe = IngestionPipeline(store=store, embedder=HashingEmbedder(dim=512))
    pipe.ingest_text(
        "Our refund policy allows returns within 30 days of purchase with a receipt.",
        doc_id="policy",
        collection="kb",
    )
    pipe.ingest_text(
        "The office is open Monday to Friday from nine to five.",
        doc_id="hours",
        collection="kb",
    )
    results = search("how many days for a refund", collection="kb", k=2, store=store,
                     embedder=HashingEmbedder(dim=512))
    assert results
    assert "refund" in results[0].text.lower()

    stats = store.stats()
    assert stats["documents"] == 2


def test_ingest_dedup(tmp_path):
    store = VectorStore(tmp_path / "v.db")
    pipe = IngestionPipeline(store=store, embedder=HashingEmbedder(dim=128))
    f = tmp_path / "doc.txt"
    f.write_text("some stable content about widgets")
    s1 = pipe.ingest_path(f, collection="c")
    assert s1.added == 1
    s2 = pipe.ingest_path(f, collection="c")  # unchanged -> skipped
    assert s2.skipped == 1 and s2.added == 0
