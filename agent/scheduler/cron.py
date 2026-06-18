"""A small persisted scheduler: interval + daily jobs that enqueue tasks.

Each firing drops a task on the durable queue (so the worker runs it like any
other request). Supports ``every <N>{s,m,h,d}`` intervals and ``at HH:MM`` daily.
Cron-expression support is a documented extension point.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from agent.config import get_settings
from agent.logging import get_logger
from agent.queue.task_queue import get_queue

log = get_logger("scheduler.cron")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  name      TEXT UNIQUE NOT NULL,
  kind      TEXT NOT NULL,           -- interval | daily
  spec      TEXT NOT NULL,           -- seconds (interval) or HH:MM (daily)
  text      TEXT NOT NULL,
  priority  INTEGER NOT NULL DEFAULT 0,
  enabled   INTEGER NOT NULL DEFAULT 1,
  last_run  INTEGER,
  next_run  INTEGER NOT NULL
);
"""


@dataclass
class Job:
    id: int
    name: str
    kind: str
    spec: str
    text: str
    priority: int
    enabled: int
    last_run: int | None
    next_run: int


def parse_interval(spec: str) -> int:
    """Parse '30s'/'15m'/'2h'/'1d' (or a bare number of seconds) to seconds."""
    spec = spec.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if spec[-1] in units:
        return max(1, int(float(spec[:-1]) * units[spec[-1]]))
    return max(1, int(float(spec)))


def _next_daily(hhmm: str, now: float | None = None) -> int:
    now = now or time.time()
    h, m = (int(x) for x in hhmm.split(":"))
    base = datetime.fromtimestamp(now)
    target = base.replace(hour=h, minute=m, second=0, microsecond=0)
    if target.timestamp() <= now:
        target += timedelta(days=1)
    return int(target.timestamp())


class CronScheduler:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or get_settings().scheduler_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- management ------------------------------------------------------- #
    def add_interval(self, name: str, every: str, text: str, *, priority: int = 0) -> int:
        seconds = parse_interval(every)
        return self._upsert(name, "interval", str(seconds), text, priority, int(time.time()) + seconds)

    def add_daily(self, name: str, at: str, text: str, *, priority: int = 0) -> int:
        return self._upsert(name, "daily", at, text, priority, _next_daily(at))

    def _upsert(self, name, kind, spec, text, priority, next_run) -> int:
        with self._conn() as c:
            c.execute(
                "INSERT INTO jobs(name, kind, spec, text, priority, enabled, next_run) "
                "VALUES (?,?,?,?,?,1,?) "
                "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, spec=excluded.spec, "
                "text=excluded.text, priority=excluded.priority, enabled=1, next_run=excluded.next_run",
                (name, kind, spec, text, priority, next_run),
            )
            row = c.execute("SELECT id FROM jobs WHERE name=?", (name,)).fetchone()
            return row["id"]

    def remove(self, name: str) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM jobs WHERE name=?", (name,)).rowcount > 0

    def list_jobs(self) -> list[Job]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM jobs ORDER BY next_run").fetchall()
            return [Job(**dict(r)) for r in rows]

    # ---- firing ----------------------------------------------------------- #
    def _compute_next(self, job: Job, now: int) -> int:
        if job.kind == "interval":
            return now + int(job.spec)
        return _next_daily(job.spec, now)

    def tick(self) -> int:
        now = int(time.time())
        fired = 0
        queue = get_queue()
        with self._conn() as c:
            due = c.execute(
                "SELECT * FROM jobs WHERE enabled=1 AND next_run<=?", (now,)
            ).fetchall()
            for r in due:
                job = Job(**dict(r))
                queue.add(
                    job.text,
                    kind="cron",
                    source="cron",
                    external_id=f"{job.name}@{job.next_run}",
                    priority=job.priority,
                )
                c.execute(
                    "UPDATE jobs SET last_run=?, next_run=? WHERE id=?",
                    (now, self._compute_next(job, now), job.id),
                )
                fired += 1
                log.info("fired cron job %s", job.name)
        return fired

    def run(self, *, poll: float = 30.0) -> None:
        log.info("cron scheduler started (%d job(s))", len(self.list_jobs()))
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("cron tick error")
            time.sleep(poll)


_SCHED: CronScheduler | None = None


def get_scheduler() -> CronScheduler:
    global _SCHED
    if _SCHED is None:
        _SCHED = CronScheduler()
    return _SCHED
