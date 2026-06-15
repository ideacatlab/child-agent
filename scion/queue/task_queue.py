"""SQLite-backed durable task queue."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scion.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          INTEGER NOT NULL,
  kind        TEXT    NOT NULL DEFAULT 'chat',
  source      TEXT    NOT NULL DEFAULT 'cli',
  external_id TEXT,
  origin      TEXT,                       -- JSON: where/how to reply
  text        TEXT    NOT NULL,
  payload     TEXT,                       -- JSON: extra structured input
  priority    INTEGER NOT NULL DEFAULT 0,
  status      TEXT    NOT NULL DEFAULT 'pending', -- pending|working|done|skipped|obsolete|failed
  attempts    INTEGER NOT NULL DEFAULT 0,
  claimed_at  INTEGER,
  done_at     INTEGER,
  result      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_src_ext
  ON tasks(source, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_status ON tasks(status, priority DESC, id);
"""


@dataclass
class Task:
    id: int
    ts: int
    kind: str
    source: str
    external_id: str | None
    origin: dict[str, Any]
    text: str
    payload: dict[str, Any]
    priority: int
    status: str
    attempts: int
    claimed_at: int | None
    done_at: int | None
    result: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Task":
        return cls(
            id=row["id"],
            ts=row["ts"],
            kind=row["kind"],
            source=row["source"],
            external_id=row["external_id"],
            origin=json.loads(row["origin"]) if row["origin"] else {},
            text=row["text"],
            payload=json.loads(row["payload"]) if row["payload"] else {},
            priority=row["priority"],
            status=row["status"],
            attempts=row["attempts"],
            claimed_at=row["claimed_at"],
            done_at=row["done_at"],
            result=row["result"],
        )


class TaskQueue:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or get_settings().queue_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    # ---- enqueue ---------------------------------------------------------- #
    def add(
        self,
        text: str,
        *,
        kind: str = "chat",
        source: str = "cli",
        external_id: str | None = None,
        origin: dict | None = None,
        payload: dict | None = None,
        priority: int = 0,
    ) -> tuple[int, bool]:
        """Enqueue a task. Returns ``(task_id, is_new)``.

        ``(source, external_id)`` makes inserts idempotent — re-queuing the same
        Telegram message is a no-op.
        """
        now = int(time.time())
        with self._conn() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO tasks
                   (ts, kind, source, external_id, origin, text, payload, priority, status)
                   VALUES (?,?,?,?,?,?,?,?, 'pending')""",
                (
                    now, kind, source, external_id,
                    json.dumps(origin or {}), text,
                    json.dumps(payload or {}), priority,
                ),
            )
            if cur.rowcount > 0:
                return cur.lastrowid, True
            # already existed — return its id
            row = c.execute(
                "SELECT id FROM tasks WHERE source=? AND external_id=?",
                (source, external_id),
            ).fetchone()
            return (row["id"] if row else -1), False

    # ---- claim / complete ------------------------------------------------- #
    def claim_next(self) -> Task | None:
        """Atomically claim the highest-priority oldest pending task."""
        now = int(time.time())
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM tasks WHERE status='pending' "
                "ORDER BY priority DESC, id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                c.execute("COMMIT")
                return None
            c.execute(
                "UPDATE tasks SET status='working', claimed_at=?, attempts=attempts+1 WHERE id=?",
                (now, row["id"]),
            )
            c.execute("COMMIT")
            return self.get(row["id"])

    def claim(self, task_id: int) -> bool:
        now = int(time.time())
        with self._conn() as c:
            cur = c.execute(
                "UPDATE tasks SET status='working', claimed_at=?, attempts=attempts+1 "
                "WHERE id=? AND status IN ('pending','failed')",
                (now, task_id),
            )
            return cur.rowcount > 0

    def complete(self, task_id: int, result: str = "") -> None:
        self._finish(task_id, "done", result)

    def skip(self, task_id: int, reason: str = "") -> None:
        self._finish(task_id, "skipped", reason)

    def fail(self, task_id: int, error: str = "", *, retry: bool = True, max_attempts: int = 3) -> None:
        with self._conn() as c:
            row = c.execute("SELECT attempts FROM tasks WHERE id=?", (task_id,)).fetchone()
            attempts = row["attempts"] if row else 0
            if retry and attempts < max_attempts:
                c.execute(
                    "UPDATE tasks SET status='pending', result=? WHERE id=?",
                    (f"retry after error: {error}", task_id),
                )
            else:
                c.execute(
                    "UPDATE tasks SET status='failed', done_at=?, result=? WHERE id=?",
                    (int(time.time()), error, task_id),
                )

    def _finish(self, task_id: int, status: str, result: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE tasks SET status=?, done_at=?, result=? WHERE id=?",
                (status, int(time.time()), result, task_id),
            )

    # ---- reads ------------------------------------------------------------ #
    def get(self, task_id: int) -> Task | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return Task.from_row(row) if row else None

    def pending(self, limit: int = 50) -> list[Task]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM tasks WHERE status='pending' "
                "ORDER BY priority DESC, id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [Task.from_row(r) for r in rows]

    def recent(self, limit: int = 20, status: str | None = None) -> list[Task]:
        with self._conn() as c:
            if status:
                rows = c.execute(
                    "SELECT * FROM tasks WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [Task.from_row(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status").fetchall()
            return {r["status"]: r["n"] for r in rows}

    # ---- maintenance ------------------------------------------------------ #
    def requeue_stuck(self, older_than_s: int = 1800) -> int:
        """Return tasks stuck in 'working' (crashed worker) to 'pending'."""
        cutoff = int(time.time()) - older_than_s
        with self._conn() as c:
            cur = c.execute(
                "UPDATE tasks SET status='pending' WHERE status='working' AND claimed_at < ?",
                (cutoff,),
            )
            return cur.rowcount

    def gc(self, max_age_hours: int = 72) -> int:
        """Obsolete trivially-empty pending items and very old pending noise.

        Conservative by design (ali-fleet-recovery): never deletes, never touches
        working/done rows.
        """
        cutoff = int(time.time()) - max_age_hours * 3600
        with self._conn() as c:
            cur = c.execute(
                "UPDATE tasks SET status='obsolete', done_at=? "
                "WHERE status='pending' AND (length(trim(text)) < 3 OR ts < ?)",
                (int(time.time()), cutoff),
            )
            return cur.rowcount


_QUEUE: TaskQueue | None = None


def get_queue() -> TaskQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = TaskQueue()
    return _QUEUE
