"""Vector + lexical store backed by SQLite. Pure stdlib; numpy used if present."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from scion.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  doc_id     TEXT PRIMARY KEY,
  collection TEXT NOT NULL DEFAULT 'default',
  path       TEXT,
  hash       TEXT,
  meta       TEXT,
  ts         INTEGER
);
CREATE TABLE IF NOT EXISTS chunks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id     TEXT NOT NULL,
  collection TEXT NOT NULL DEFAULT 'default',
  ord        INTEGER NOT NULL,
  text       TEXT NOT NULL,
  embedding  TEXT NOT NULL,
  meta       TEXT
);
CREATE INDEX IF NOT EXISTS ix_chunks_coll ON chunks(collection);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(doc_id);
"""


@dataclass
class Chunk:
    id: int
    doc_id: str
    ord: int
    text: str
    embedding: list[float]
    meta: dict


class VectorStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or get_settings().vectors_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ---- writes ----------------------------------------------------------- #
    def document_hash(self, doc_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT hash FROM docs WHERE doc_id=?", (doc_id,)).fetchone()
            return row["hash"] if row else None

    def upsert_document(
        self,
        doc_id: str,
        *,
        path: str,
        content_hash: str,
        collection: str,
        chunks: list[str],
        embeddings: list[list[float]],
        meta: dict | None = None,
    ) -> int:
        """Replace a document's chunks. Returns the number of chunks written."""
        now = int(time.time())
        meta_json = json.dumps(meta or {})
        with self._conn() as c:
            c.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            c.execute(
                "INSERT OR REPLACE INTO docs(doc_id, collection, path, hash, meta, ts) "
                "VALUES (?,?,?,?,?,?)",
                (doc_id, collection, path, content_hash, meta_json, now),
            )
            c.executemany(
                "INSERT INTO chunks(doc_id, collection, ord, text, embedding, meta) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (doc_id, collection, i, text, json.dumps(emb), meta_json)
                    for i, (text, emb) in enumerate(zip(chunks, embeddings))
                ],
            )
            return len(chunks)

    def delete_document(self, doc_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            c.execute("DELETE FROM docs WHERE doc_id=?", (doc_id,))

    # ---- reads ------------------------------------------------------------ #
    def load_chunks(self, collection: str = "default") -> list[Chunk]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, doc_id, ord, text, embedding, meta FROM chunks WHERE collection=?",
                (collection,),
            ).fetchall()
        out: list[Chunk] = []
        for r in rows:
            out.append(
                Chunk(
                    id=r["id"],
                    doc_id=r["doc_id"],
                    ord=r["ord"],
                    text=r["text"],
                    embedding=json.loads(r["embedding"]),
                    meta=json.loads(r["meta"]) if r["meta"] else {},
                )
            )
        return out

    def collections(self) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT DISTINCT collection FROM docs").fetchall()
            return [r["collection"] for r in rows]

    def stats(self) -> dict:
        with self._conn() as c:
            docs = c.execute("SELECT COUNT(*) n FROM docs").fetchone()["n"]
            chunks = c.execute("SELECT COUNT(*) n FROM chunks").fetchone()["n"]
            by_coll = c.execute(
                "SELECT collection, COUNT(*) n FROM docs GROUP BY collection"
            ).fetchall()
        return {
            "documents": docs,
            "chunks": chunks,
            "collections": {r["collection"]: r["n"] for r in by_coll},
        }


_STORE: VectorStore | None = None


def get_store() -> VectorStore:
    global _STORE
    if _STORE is None:
        _STORE = VectorStore()
    return _STORE
