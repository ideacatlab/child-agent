"""Durable per-run performance store for the fleet (SQLite).

Every spawned worker is one ``runs`` row: which role, what it was asked, how long
it took, whether it succeeded, and a one-line summary. The supervisor reads the
aggregates to decide which agents need improving. Same connection discipline as the
task queue (WAL + busy_timeout) so the daemon and orchestrator can write
concurrently.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from agent.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  role         TEXT    NOT NULL,
  task_id      INTEGER,
  prompt       TEXT    NOT NULL,
  model        TEXT,
  started_at   INTEGER NOT NULL,
  ended_at     INTEGER,
  duration_ms  INTEGER,
  exit_code    INTEGER,
  status       TEXT    NOT NULL DEFAULT 'running', -- running|ok|error|timeout
  summary      TEXT,
  score        INTEGER,                            -- optional, set by the supervisor
  pid          INTEGER,
  log_path     TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_role ON runs(role, id DESC);
CREATE INDEX IF NOT EXISTS ix_runs_status ON runs(status, id DESC);
"""


@dataclass
class RunRecord:
    id: int
    role: str
    task_id: int | None
    prompt: str
    model: str | None
    started_at: int
    ended_at: int | None
    duration_ms: int | None
    exit_code: int | None
    status: str
    summary: str | None
    score: int | None
    pid: int | None
    log_path: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "RunRecord":
        return cls(**{k: row[k] for k in row.keys()})


class FleetMetrics:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or get_settings().fleet_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Enable WAL once (it's a persistent, db-level setting); doing it on every
        # connection contends under the concurrent writes of run_parallel().
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")  # wait on the writer lock, don't fail
        return conn

    # ---- lifecycle -------------------------------------------------------- #
    def start_run(
        self, role: str, prompt: str, *, model: str | None = None,
        task_id: int | None = None, pid: int | None = None, log_path: str | None = None,
    ) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO runs(role, task_id, prompt, model, started_at, status, pid, log_path) "
                "VALUES (?,?,?,?,?, 'running', ?, ?)",
                (role, task_id, prompt, model, int(time.time()), pid, log_path),
            )
            return cur.lastrowid

    def finish_run(
        self, run_id: int, *, status: str, exit_code: int | None = None,
        summary: str | None = None, duration_ms: int | None = None,
    ) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE runs SET status=?, exit_code=?, summary=?, duration_ms=?, ended_at=? "
                "WHERE id=?",
                (status, exit_code, summary, duration_ms, int(time.time()), run_id),
            )

    def set_score(self, run_id: int, score: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET score=? WHERE id=?", (score, run_id))

    # ---- reads ------------------------------------------------------------ #
    def get(self, run_id: int) -> RunRecord | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            return RunRecord.from_row(row) if row else None

    def recent(self, limit: int = 20, role: str | None = None) -> list[RunRecord]:
        with self._conn() as c:
            if role:
                rows = c.execute(
                    "SELECT * FROM runs WHERE role=? ORDER BY id DESC LIMIT ?", (role, limit)
                ).fetchall()
            else:
                rows = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [RunRecord.from_row(r) for r in rows]

    def running(self) -> list[RunRecord]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM runs WHERE status='running' ORDER BY id").fetchall()
            return [RunRecord.from_row(r) for r in rows]

    # ---- aggregates ------------------------------------------------------- #
    def aggregate(self, role: str | None = None) -> list[dict]:
        """Per-role performance summary: counts, success rate, avg duration."""
        where = "WHERE role=?" if role else ""
        params = (role,) if role else ()
        with self._conn() as c:
            rows = c.execute(
                f"""SELECT role,
                          COUNT(*) AS total,
                          SUM(status='ok') AS ok,
                          SUM(status='error') AS error,
                          SUM(status='timeout') AS timeout,
                          SUM(status='running') AS running,
                          AVG(duration_ms) AS avg_ms,
                          AVG(score) AS avg_score
                   FROM runs {where}
                   GROUP BY role ORDER BY role""",
                params,
            ).fetchall()
            out = []
            for r in rows:
                total = r["total"] or 0
                done = total - (r["running"] or 0)
                out.append({
                    "role": r["role"],
                    "total": total,
                    "ok": r["ok"] or 0,
                    "error": r["error"] or 0,
                    "timeout": r["timeout"] or 0,
                    "running": r["running"] or 0,
                    "success_rate": round((r["ok"] or 0) / done, 3) if done else None,
                    "avg_ms": int(r["avg_ms"]) if r["avg_ms"] is not None else None,
                    "avg_score": round(r["avg_score"], 2) if r["avg_score"] is not None else None,
                })
            return out

    def recent_failures(self, limit: int = 5, role: str | None = None) -> list[RunRecord]:
        where = "status IN ('error','timeout')" + (" AND role=?" if role else "")
        params = ((role, limit) if role else (limit,))
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM runs WHERE {where} ORDER BY id DESC LIMIT ?", params
            ).fetchall()
            return [RunRecord.from_row(r) for r in rows]

    def digest(self) -> str:
        """A compact Markdown performance digest — what the supervisor reads."""
        agg = self.aggregate()
        if not agg:
            return "No fleet runs recorded yet."
        lines = ["# Fleet performance digest", ""]
        for a in agg:
            sr = "n/a" if a["success_rate"] is None else f"{a['success_rate'] * 100:.0f}%"
            avg = "n/a" if a["avg_ms"] is None else f"{a['avg_ms'] / 1000:.1f}s"
            lines.append(
                f"- **{a['role']}** — {a['total']} runs, success {sr}, "
                f"errors {a['error']}, timeouts {a['timeout']}, avg {avg}"
            )
        fails = self.recent_failures(limit=8)
        if fails:
            lines += ["", "## Recent failures"]
            for f in fails:
                lines.append(f"- [{f.role}] {(f.summary or f.prompt)[:140]}")
        return "\n".join(lines)


_METRICS: FleetMetrics | None = None


def get_metrics() -> FleetMetrics:
    global _METRICS
    if _METRICS is None:
        _METRICS = FleetMetrics()
    return _METRICS
